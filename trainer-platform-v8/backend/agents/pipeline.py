"""
LangGraph Orchestrator
Agents: Parser → Validation → Ranking → Email → Reply Monitor → Retry Scheduler
"""

from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from datetime import datetime
from utils.time_utils import utc_now
from config import get_settings
import anthropic
import json
import os
import re


# ─── State Schema ────────────────────────────────────────────────────────────

class PipelineState(TypedDict):
    trainers: List[Dict[str, Any]]
    requirements: Dict[str, Any]
    validated_trainers: List[Dict[str, Any]]
    ranked_trainers: List[Dict[str, Any]]
    top_trainers: List[Dict[str, Any]]
    email_payloads: List[Dict[str, Any]]
    errors: List[str]
    status: str
    category_filter_applied: bool
    no_category_match: bool
    category_match_count: int


MATCHING_MODEL = "claude-sonnet-4-20250514"


def _anthropic_client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    api_key = (os.getenv("ANTHROPIC_API_KEY", "") or getattr(settings, "anthropic_api_key", "")).strip()
    return anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()


def _text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {val}" for key, val in value.items())
    return str(value or "")


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", _text(value).lower()).strip()


def _token_overlap(left: str, right: str) -> bool:
    left_words = {word for word in left.split() if len(word) > 2}
    right_words = {word for word in right.split() if len(word) > 2}
    if not left_words or not right_words:
        return False
    overlap = left_words & right_words
    return len(overlap) / max(min(len(left_words), len(right_words)), 1) >= 0.5


def _category_matches_requirement(trainer: Dict[str, Any], technology_needed: str) -> bool:
    needle = _norm(technology_needed)
    if not needle:
        return True

    category_values = [
        trainer.get("primary_category", ""),
        trainer.get("technology_category", ""),
        trainer.get("category", ""),
        *trainer.get("secondary_categories", []),
    ]
    for value in category_values:
        hay = _norm(value)
        if not hay:
            continue
        if needle == hay or needle in hay or hay in needle or _token_overlap(needle, hay):
            return True
    return False


def _category_filter_agent(state: PipelineState) -> PipelineState:
    technology = state["requirements"].get("technology_needed", "")
    trainers = state["trainers"]
    category_matches = [
        trainer for trainer in trainers
        if _category_matches_requirement(trainer, technology)
    ]

    state["category_match_count"] = len(category_matches)
    if category_matches:
        state["trainers"] = category_matches
        state["category_filter_applied"] = True
        state["no_category_match"] = False
    else:
        state["category_filter_applied"] = False
        state["no_category_match"] = True
    state["status"] = "category_filtered"
    return state


# ─── Agent 1: Validation Agent ───────────────────────────────────────────────

def validation_agent(state: PipelineState) -> PipelineState:
    """Validates each trainer against job requirements using rule engine"""
    trainers = state["trainers"]
    req = state["requirements"]

    required_skills = [s.lower() for s in req.get("required_skills", [])]
    preferred_skills = [s.lower() for s in req.get("preferred_skills", [])]
    required_certs = [c.lower() for c in req.get("required_certifications", [])]
    min_exp = req.get("min_experience_years", 2)
    pref_location = req.get("preferred_location", "").lower().strip()
    must_linkedin = req.get("must_have_linkedin", False)
    must_resume = req.get("must_have_resume", False)

    validated = []

    for t in trainers:
        score = 0
        breakdown = {}
        combined = t.get("combined_text", "")
        if not combined:
            skills = t.get("skills", [])
            skills_text = " ".join(skills) if isinstance(skills, list) else str(skills)
            tags = t.get("specialty_tags", [])
            tags_text = " ".join(tags) if isinstance(tags, list) else str(tags)
            secondary = t.get("secondary_categories", [])
            secondary_text = " ".join(secondary) if isinstance(secondary, list) else str(secondary)
            combined_parts = [
                t.get("technologies", ""),
                skills_text,
                " ".join(t.get("certifications", []) if isinstance(t.get("certifications"), list) else [str(t.get("certifications", ""))]),
                tags_text,
                t.get("technology_category", ""),
                secondary_text,
                t.get("summary", ""),
            ]
            combined = " ".join(combined_parts)
        combined = " ".join([
            combined,
            t.get("primary_category", ""),
            t.get("domain", ""),
            _text(t.get("secondary_categories", [])),
            _text(t.get("specialisation_tags", [])),
            _text(t.get("specialty_tags", [])),
            _text(t.get("industry_focus", [])),
            _text(t.get("language_of_delivery", [])),
            _text(t.get("skill_level_map", {})),
        ])
        combined = combined.lower()

        # ── Technology Match (35 pts) ──
        tech_keyword = req.get("technology_needed", "").lower()
        if tech_keyword in combined:
            tech_score = 35
        else:
            words = [w for w in tech_keyword.split() if len(w) > 2]
            matches = sum(1 for w in words if w in combined)
            tech_score = round((matches / max(len(words), 1)) * 20)
        breakdown["technology"] = {"score": tech_score, "max": 35, "keyword": tech_keyword}
        score += tech_score

        # ── Skills Match (30 pts) ──
        if required_skills:
            matched_req = [s for s in required_skills if s in combined]
            matched_pref = [s for s in preferred_skills if s in combined]
            skill_score = round(
                (len(matched_req) / max(len(required_skills), 1)) * 24 +
                (len(matched_pref) / max(len(preferred_skills), 1)) * 6
            )
        else:
            matched_req, matched_pref = [], []
            skill_score = 30
        breakdown["skills"] = {"score": skill_score, "max": 30,
                               "matched_required": matched_req, "matched_preferred": matched_pref}
        score += skill_score

        # ── Experience (20 pts) ──
        exp = t.get("experience_years", 0)
        if exp >= min_exp:
            extra = min(exp - min_exp, 10)
            exp_score = min(20, round(15 + extra * 0.5))
        elif exp > 0:
            exp_score = round((exp / max(min_exp, 1)) * 10)
        else:
            exp_score = 0
        breakdown["experience"] = {"score": exp_score, "max": 20, "actual": exp, "required": min_exp}
        score += exp_score

        # ── Certifications (10 pts) ──
        certs = t.get("certifications", "")
        certs_text = " ".join(certs).lower() if isinstance(certs, list) else str(certs).lower()
        if not required_certs:
            cert_score = 7 if len(certs_text) > 10 else 0
        else:
            matched_c = [c for c in required_certs if c in certs_text]
            cert_score = round((len(matched_c) / max(len(required_certs), 1)) * 10)
        breakdown["certifications"] = {"score": cert_score, "max": 10}
        score += cert_score

        # ── Location (5 pts) ──
        loc_score = 5 if (not pref_location or pref_location in t.get("location", "").lower()) else 0
        breakdown["location"] = {"score": loc_score, "max": 5, "trainer_location": t.get("location", "")}
        score += loc_score

        # ── Filters ──
        has_linkedin = bool(t.get("linkedin") and len(t["linkedin"]) > 5)
        has_resume = bool(t.get("resume") and len(t["resume"]) > 5)
        passed_filters = (not must_linkedin or has_linkedin) and (not must_resume or has_resume)

        validated.append({
            **t,
            "match_score": score,
            "score_breakdown": breakdown,
            "has_linkedin": has_linkedin,
            "has_resume": has_resume,
            "passed_filters": passed_filters,
        })

    state["validated_trainers"] = validated
    state["status"] = "validated"
    return state


# ─── Agent 2: Claude Scoring Agent ────────────────────────────────────────────

def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    return data if isinstance(data, list) else []


def _ai_scoring_prompt(requirements: Dict[str, Any], trainers: List[Dict[str, Any]]) -> str:
    trainer_summaries = []
    for trainer in trainers[:30]:
        trainer_summaries.append({
            "trainer_id": trainer.get("trainer_id"),
            "name": trainer.get("name"),
            "rule_score": trainer.get("match_score", 0),
            "primary_category": trainer.get("primary_category") or trainer.get("technology_category"),
            "secondary_categories": trainer.get("secondary_categories", []),
            "domain": trainer.get("domain", ""),
            "skills": trainer.get("skills", [])[:20],
            "specialisation_tags": trainer.get("specialisation_tags") or trainer.get("specialty_tags", []),
            "industry_focus": trainer.get("industry_focus", []),
            "skill_level_map": trainer.get("skill_level_map", {}),
            "experience_years": trainer.get("experience_years", 0),
            "certifications": trainer.get("certifications", [])[:12],
            "summary": trainer.get("summary", "")[:800],
            "past_clients": trainer.get("past_clients", [])[:10],
        })

    return f"""You are scoring trainers for a training requirement.
Use precise fit, specialisation tags, industry focus, category fit, seniority, certifications, and skill evidence.
Return ONLY valid JSON array. No markdown. No extra text.

Requirement:
{json.dumps(requirements, ensure_ascii=False, default=str)}

Candidate trainers:
{json.dumps(trainer_summaries, ensure_ascii=False, default=str)}

Return an array of objects exactly like:
[
  {{"trainer_id": "TR-123", "ai_match_score": 0-100, "ai_reason": "one concise reason"}}
]"""


async def claude_scoring_agent(state: PipelineState) -> PipelineState:
    """Uses Claude to refine high-potential candidates; falls back to rule scores if unavailable."""
    candidates = [
        t for t in state["validated_trainers"]
        if t.get("passed_filters") and t.get("match_score", 0) > 0
    ]
    if not candidates:
        state["status"] = "ai_scoring_skipped"
        return state

    candidates = sorted(candidates, key=lambda x: x.get("match_score", 0), reverse=True)
    score_targets = candidates[:30]

    try:
        client = _anthropic_client()
        message = await client.messages.create(
            model=MATCHING_MODEL,
            max_tokens=1800,
            temperature=0,
            messages=[{"role": "user", "content": _ai_scoring_prompt(state["requirements"], score_targets)}],
        )
        raw = "".join(
            block.text for block in message.content
            if getattr(block, "type", "") == "text"
        )
        ai_scores = {
            item.get("trainer_id"): item
            for item in _extract_json_array(raw)
            if item.get("trainer_id")
        }

        for trainer in state["validated_trainers"]:
            ai_item = ai_scores.get(trainer.get("trainer_id"))
            if not ai_item:
                continue
            try:
                ai_score = max(0, min(float(ai_item.get("ai_match_score", 0)), 100))
            except (TypeError, ValueError):
                continue
            trainer["ai_match_score"] = round(ai_score, 2)
            trainer["ai_match_reason"] = str(ai_item.get("ai_reason", "")).strip()
            trainer["match_score"] = round((trainer.get("match_score", 0) * 0.55) + (ai_score * 0.45), 2)
        state["status"] = "ai_scored"
    except Exception as exc:
        state["errors"].append(f"Claude scoring unavailable: {exc}")
        state["status"] = "ai_scoring_fallback"

    return state


# ─── Agent 3: Ranking Agent ───────────────────────────────────────────────────

def ranking_agent(state: PipelineState) -> PipelineState:
    """Ranks validated trainers by score, picks top N"""
    top_n = state["requirements"].get("top_n", 5)

    passed = [t for t in state["validated_trainers"]
              if t.get("passed_filters") and t.get("match_score", 0) > 0]

    ranked = sorted(passed, key=lambda x: x["match_score"], reverse=True)
    for i, t in enumerate(ranked):
        t["rank"] = i + 1

    state["ranked_trainers"] = ranked
    state["top_trainers"] = ranked[:top_n]
    state["status"] = "ranked"
    return state


# ─── Agent 3: Email Composer Agent ───────────────────────────────────────────

def email_composer_agent(state: PipelineState) -> PipelineState:
    """Composes personalized outreach emails for top trainers"""
    req = state["requirements"]
    tech = req.get("technology_needed", "the required technology")
    req_id = req.get("requirement_id", "REQ-001")
    job_title = req.get("job_title", f"{tech} Trainer")

    payloads = []
    for t in state["top_trainers"]:
        if not t.get("email"):
            continue

        skills_preview = ", ".join(t.get("skills", [])[:3]) or tech
        subject = f"Training Opportunity — {tech} | Ref: {req_id}"

        body = f"""Dear {t['name']},

I hope this message finds you well.

We came across your profile and are impressed with your expertise in {t.get('technologies', tech)[:120]}.

We have an exciting training requirement for **{tech}** and believe your {t.get('experience_raw', '')} of experience makes you an outstanding candidate.

**Opportunity Details:**
- Technology: {tech}
- Role: {job_title}
- Reference: {req_id}
- Your Match Score: {t['match_score']}/100 (Rank #{t['rank']})

We would love to schedule a brief call to discuss:
✅ Training duration and batch details
✅ Online / Offline / Hybrid mode
✅ Your availability and engagement terms

Could you please reply to this email with your available time slots, or book directly here:
📅 https://calendly.com/trainersync/{req_id}

We look forward to hearing from you!

Warm regards,
TrainerSync Coordination Team
support@trainersync.io
"""

        payloads.append({
            "trainer_id": t["trainer_id"],
            "trainer_name": t["name"],
            "to": t["email"],
            "subject": subject,
            "body": body,
            "requirement_id": req_id,
            "rank": t["rank"],
            "match_score": t["match_score"],
            "email_stage": 1,  # Stage 1: Initial inquiry
            "status": "pending",
            "retry_count": 0,
            "composed_at": utc_now().isoformat(),
        })

    state["email_payloads"] = payloads
    state["status"] = "emails_composed"
    return state


# ─── Build LangGraph ─────────────────────────────────────────────────────────

def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("category_filter_agent", _category_filter_agent)
    graph.add_node("validation_agent", validation_agent)
    graph.add_node("claude_scoring_agent", claude_scoring_agent)
    graph.add_node("ranking_agent", ranking_agent)
    graph.add_node("email_composer_agent", email_composer_agent)

    graph.set_entry_point("category_filter_agent")
    graph.add_edge("category_filter_agent", "validation_agent")
    graph.add_edge("validation_agent", "claude_scoring_agent")
    graph.add_edge("claude_scoring_agent", "ranking_agent")
    graph.add_edge("ranking_agent", "email_composer_agent")
    graph.add_edge("email_composer_agent", END)

    return graph.compile()


async def run_pipeline(trainers: List[Dict], requirements: Dict) -> Dict[str, Any]:
    """Entry point: run the full LangGraph pipeline"""
    pipeline = build_pipeline()

    initial_state: PipelineState = {
        "trainers": trainers,
        "requirements": requirements,
        "validated_trainers": [],
        "ranked_trainers": [],
        "top_trainers": [],
        "email_payloads": [],
        "errors": [],
        "status": "started",
        "category_filter_applied": False,
        "no_category_match": False,
        "category_match_count": 0,
    }

    final_state = await pipeline.ainvoke(initial_state)
    return final_state

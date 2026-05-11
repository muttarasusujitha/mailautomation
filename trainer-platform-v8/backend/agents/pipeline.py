"""
LangGraph Orchestrator
Agents: Parser → Validation → Ranking → Email → Reply Monitor → Retry Scheduler
"""

from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from datetime import datetime
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
        combined = t.get("combined_text", "").lower()

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
        certs_text = t.get("certifications", "").lower()
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


# ─── Agent 2: Ranking Agent ───────────────────────────────────────────────────

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
            "status": "pending",
            "retry_count": 0,
            "composed_at": datetime.utcnow().isoformat(),
        })

    state["email_payloads"] = payloads
    state["status"] = "emails_composed"
    return state


# ─── Build LangGraph ─────────────────────────────────────────────────────────

def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("validation_agent", validation_agent)
    graph.add_node("ranking_agent", ranking_agent)
    graph.add_node("email_composer_agent", email_composer_agent)

    graph.set_entry_point("validation_agent")
    graph.add_edge("validation_agent", "ranking_agent")
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
    }

    final_state = await pipeline.ainvoke(initial_state)
    return final_state

"""
Professional trainer matching pipeline.

Flow:
1. Normalize requirement input.
2. Narrow candidates by category/technology without dropping all trainers on a weak match.
3. Score candidates with transparent rule-based evidence.
4. Optionally refine high-potential matches with Claude when Anthropic is configured.
5. Rank, shortlist, and prepare outreach payloads.
"""

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Sequence, Set, TypedDict

import anthropic
from langgraph.graph import END, StateGraph

from config import get_settings
from utils.time_utils import utc_now


MATCHING_MODEL = "claude-sonnet-4-20250514"
PIPELINE_VERSION = "trainer-match-v2"
CODE_FENCE = chr(96) * 3

TECHNOLOGY_WEIGHT = 35
SKILLS_WEIGHT = 25
EXPERIENCE_WEIGHT = 15
DELIVERY_WEIGHT = 10
CREDIBILITY_WEIGHT = 10
AVAILABILITY_WEIGHT = 5

MAX_AI_CANDIDATES = 30
DEFAULT_TOP_N = 5

TECH_ALIASES: Dict[str, List[str]] = {
    "full stack": ["fullstack", "mern", "mean", "react node", "frontend backend"],
    "frontend": ["front end", "react", "angular", "vue", "javascript ui"],
    "backend": ["back end", "api", "spring boot", "django", "fastapi", "node.js", "node js"],
    "devops": ["ci cd", "ci/cd", "kubernetes", "docker", "jenkins", "terraform", "sre"],
    "cloud": ["aws", "azure", "gcp", "google cloud", "cloud computing"],
    "data science": ["machine learning", "ml", "statistics", "predictive modelling"],
    "machine learning": ["ml", "deep learning", "model training", "model deployment"],
    "gen ai": ["genai", "generative ai", "llm", "large language model", "rag", "prompt engineering"],
    "agentic ai": ["ai agents", "autonomous agents", "multi agent", "langchain", "crewai"],
    "power bi": ["powerbi", "business intelligence", "bi reporting", "dax"],
    "cybersecurity": ["cyber security", "ethical hacking", "vapt", "soc", "appsec"],
    "salesforce": ["crm", "sales cloud", "service cloud", "apex"],
    "servicenow": ["service now", "it service management", "itsm"],
}


class PipelineState(TypedDict, total=False):
    trainers: List[Dict[str, Any]]
    requirements: Dict[str, Any]
    normalized_requirements: Dict[str, Any]
    validated_trainers: List[Dict[str, Any]]
    ranked_trainers: List[Dict[str, Any]]
    top_trainers: List[Dict[str, Any]]
    email_payloads: List[Dict[str, Any]]
    errors: List[str]
    warnings: List[str]
    status: str
    category_filter_applied: bool
    no_category_match: bool
    category_match_count: int
    total_candidates: int
    ai_scoring_applied: bool
    ai_scoring_candidate_count: int
    stage_log: List[Dict[str, Any]]
    pipeline_summary: Dict[str, Any]


def _anthropic_api_key() -> str:
    settings = get_settings()
    return (os.getenv("ANTHROPIC_API_KEY", "") or getattr(settings, "anthropic_api_key", "")).strip()


def _anthropic_client(api_key: str) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=api_key)


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_text(val)}" for key, val in value.items())
    return _clean_string(value)


def _as_list(value: Any, limit: int | None = None) -> List[str]:
    if value is None:
        raw_items: Sequence[Any] = []
    elif isinstance(value, list):
        raw_items = value
    elif isinstance(value, tuple):
        raw_items = list(value)
    elif isinstance(value, set):
        raw_items = list(value)
    elif isinstance(value, str):
        raw_items = re.split(r",|;|\n|\|", value)
    else:
        raw_items = [value]

    cleaned: List[str] = []
    seen: Set[str] = set()
    for item in raw_items:
        text = _clean_string(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned[:limit] if limit else cleaned


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", _text(value).lower()).strip()


def _tokens(value: Any) -> Set[str]:
    return {token for token in _norm(value).split() if len(token) > 1}


def _contains_term(text_norm: str, term: str) -> bool:
    term_norm = _norm(term)
    if not term_norm:
        return False
    if len(term_norm) <= 2:
        return term_norm in set(text_norm.split())
    return f" {term_norm} " in f" {text_norm} "


def _matching_terms(terms: Sequence[str], text_norm: str) -> List[str]:
    matched: List[str] = []
    seen: Set[str] = set()
    for term in terms:
        if not term:
            continue
        if _contains_term(text_norm, term):
            key = _norm(term)
            if key not in seen:
                seen.add(key)
                matched.append(term)
    return matched


def _expanded_terms(*values: Any) -> List[str]:
    seeds: List[str] = []
    for value in values:
        seeds.extend(_as_list(value))

    expanded: List[str] = []
    seen: Set[str] = set()

    def add(term: Any) -> None:
        cleaned = _clean_string(term)
        key = _norm(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            expanded.append(cleaned)

    for seed in seeds:
        add(seed)
        seed_norm = _norm(seed)
        for canonical, aliases in TECH_ALIASES.items():
            alias_norms = {_norm(alias) for alias in aliases}
            if seed_norm == _norm(canonical) or seed_norm in alias_norms:
                add(canonical)
                for alias in aliases:
                    add(alias)
            elif _norm(canonical) in seed_norm or any(alias in seed_norm for alias in alias_norms):
                add(canonical)
                for alias in aliases:
                    add(alias)

    return expanded


def _best_token_overlap(terms: Sequence[str], text_norm: str) -> float:
    text_tokens = set(text_norm.split())
    best = 0.0
    for term in terms:
        term_tokens = _tokens(term)
        if not term_tokens:
            continue
        overlap = len(term_tokens & text_tokens) / max(len(term_tokens), 1)
        best = max(best, overlap)
    return best


def _append_stage(state: PipelineState, stage: str, status: str, detail: Dict[str, Any] | None = None) -> None:
    state.setdefault("stage_log", []).append({
        "stage": stage,
        "status": status,
        "detail": detail or {},
        "at": utc_now().isoformat(),
    })


def _normalise_requirements(requirements: Dict[str, Any]) -> Dict[str, Any]:
    req = dict(requirements or {})
    technology = _clean_string(
        req.get("technology_needed")
        or req.get("domain")
        or req.get("job_title")
        or req.get("technology")
    )

    secondary_technologies = _as_list(req.get("secondary_technologies"), limit=8)
    required_skills = _as_list(req.get("required_skills"), limit=20)
    preferred_skills = _as_list(req.get("preferred_skills"), limit=20)

    if technology and all(_norm(technology) != _norm(skill) for skill in required_skills):
        required_skills.insert(0, technology)
    for tech in secondary_technologies:
        if all(_norm(tech) != _norm(skill) for skill in preferred_skills):
            preferred_skills.append(tech)

    top_n = _safe_int(req.get("top_n"), DEFAULT_TOP_N)
    req.update({
        "technology_needed": technology,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "required_certifications": _as_list(req.get("required_certifications"), limit=12),
        "preferred_location": _clean_string(req.get("preferred_location") or req.get("location")),
        "mode": _clean_string(req.get("mode") or req.get("training_mode")),
        "audience_level": _clean_string(req.get("audience_level")),
        "language_of_training": _clean_string(req.get("language_of_training")),
        "min_experience_years": _safe_float(req.get("min_experience_years"), 2.0),
        "top_n": max(1, min(top_n or DEFAULT_TOP_N, 20)),
    })
    return req


def requirement_normalizer_agent(state: PipelineState) -> PipelineState:
    normalized = _normalise_requirements(state.get("requirements", {}))
    state["normalized_requirements"] = normalized
    state["total_candidates"] = len(state.get("trainers", []))
    state.setdefault("errors", [])
    state.setdefault("warnings", [])
    state.setdefault("stage_log", [])

    if not normalized.get("technology_needed"):
        state["warnings"].append("Requirement has no technology/domain; matching will use the remaining requirement details.")

    state["status"] = "requirements_normalized"
    _append_stage(
        state,
        "requirements",
        "completed",
        {
            "technology_needed": normalized.get("technology_needed", ""),
            "required_skills": normalized.get("required_skills", []),
            "top_n": normalized.get("top_n", DEFAULT_TOP_N),
            "candidate_count": state["total_candidates"],
        },
    )
    return state


def _trainer_category_values(trainer: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for field in (
        "primary_category",
        "technology_category",
        "category",
        "domain",
        "secondary_categories",
        "specialisation_tags",
        "specialty_tags",
        "technologies",
        "skills",
    ):
        values.extend(_as_list(trainer.get(field)))
    return values


def _trainer_category_text(trainer: Dict[str, Any]) -> str:
    return _norm(_trainer_category_values(trainer))


def _category_matches_requirement(trainer: Dict[str, Any], requirement: Dict[str, Any]) -> bool:
    technology = requirement.get("technology_needed", "")
    required_terms = _expanded_terms(technology, requirement.get("required_skills", []))
    if not required_terms:
        return True

    category_text = _trainer_category_text(trainer)
    if _matching_terms(required_terms, category_text):
        return True
    return _best_token_overlap(required_terms, category_text) >= 0.6


def _category_filter_agent(state: PipelineState) -> PipelineState:
    requirement = state.get("normalized_requirements", state.get("requirements", {}))
    trainers = state.get("trainers", [])
    category_matches = [
        trainer for trainer in trainers
        if _category_matches_requirement(trainer, requirement)
    ]

    state["category_match_count"] = len(category_matches)
    if category_matches:
        state["trainers"] = category_matches
        state["category_filter_applied"] = True
        state["no_category_match"] = False
        status = "completed"
    else:
        state["category_filter_applied"] = False
        state["no_category_match"] = True
        state.setdefault("warnings", []).append(
            "No trainer category matched the requirement exactly; ranking continued across all available trainers."
        )
        status = "fallback_all_candidates"

    state["status"] = "category_filtered"
    _append_stage(
        state,
        "category_filter",
        status,
        {
            "input_count": len(trainers),
            "matched_count": len(category_matches),
            "filter_applied": state["category_filter_applied"],
        },
    )
    return state


def _trainer_experience_years(trainer: Dict[str, Any]) -> float:
    direct = _safe_float(trainer.get("experience_years"), -1)
    if direct >= 0:
        return direct

    raw = _text([trainer.get("experience_raw"), trainer.get("summary"), trainer.get("combined_text")])
    match = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", raw, flags=re.IGNORECASE)
    return _safe_float(match.group(1), 0.0) if match else 0.0


def _trainer_profile_text(trainer: Dict[str, Any]) -> str:
    combined = trainer.get("combined_text")
    parts = [
        combined[:8000] if isinstance(combined, str) else combined,
        trainer.get("name"),
        trainer.get("trainer_name"),
        trainer.get("technologies"),
        trainer.get("skills"),
        trainer.get("certifications"),
        trainer.get("primary_category"),
        trainer.get("technology_category"),
        trainer.get("category"),
        trainer.get("domain"),
        trainer.get("secondary_categories"),
        trainer.get("specialisation_tags"),
        trainer.get("specialty_tags"),
        trainer.get("industry_focus"),
        trainer.get("language_of_delivery"),
        trainer.get("skill_level_map"),
        trainer.get("summary"),
        trainer.get("past_clients"),
        trainer.get("resume", "")[:5000] if isinstance(trainer.get("resume"), str) else "",
    ]
    return _norm(parts)


def _trainer_name(trainer: Dict[str, Any]) -> str:
    return _clean_string(trainer.get("name") or trainer.get("trainer_name") or "Trainer")


def _trainer_email(trainer: Dict[str, Any]) -> str:
    return _clean_string(trainer.get("email") or trainer.get("trainer_email")).lower()


def _score_technology(requirement: Dict[str, Any], trainer: Dict[str, Any], profile_text: str) -> Dict[str, Any]:
    technology = requirement.get("technology_needed", "")
    terms = _expanded_terms(technology, requirement.get("required_skills", []))
    category_text = _trainer_category_text(trainer)

    category_matches = _matching_terms(terms, category_text)
    profile_matches = _matching_terms(terms, profile_text)
    overlap = _best_token_overlap(terms, profile_text)

    if not terms:
        score = 0
        reason = "No technology supplied"
    elif category_matches:
        score = TECHNOLOGY_WEIGHT
        reason = "Category/tag match"
    elif profile_matches:
        score = 30
        reason = "Profile evidence match"
    elif overlap >= 0.75:
        score = 25
        reason = "Strong token overlap"
    elif overlap >= 0.45:
        score = 16
        reason = "Partial token overlap"
    else:
        score = 0
        reason = "No clear technology evidence"

    return {
        "score": min(score, TECHNOLOGY_WEIGHT),
        "max": TECHNOLOGY_WEIGHT,
        "keyword": technology,
        "matched_terms": category_matches or profile_matches,
        "reason": reason,
    }


def _score_skills(requirement: Dict[str, Any], profile_text: str) -> Dict[str, Any]:
    required_skills = _as_list(requirement.get("required_skills"))
    preferred_skills = _as_list(requirement.get("preferred_skills"))

    matched_required = [
        skill for skill in required_skills
        if _matching_terms(_expanded_terms(skill), profile_text)
    ]
    matched_preferred = [
        skill for skill in preferred_skills
        if _matching_terms(_expanded_terms(skill), profile_text)
    ]

    required_ratio = len(matched_required) / max(len(required_skills), 1)
    preferred_ratio = len(matched_preferred) / max(len(preferred_skills), 1) if preferred_skills else 0

    if required_skills:
        score = round(required_ratio * 20 + preferred_ratio * 5)
    else:
        score = 10

    return {
        "score": min(score, SKILLS_WEIGHT),
        "max": SKILLS_WEIGHT,
        "matched_required": matched_required,
        "matched_preferred": matched_preferred,
        "required_count": len(required_skills),
        "preferred_count": len(preferred_skills),
    }


def _score_experience(requirement: Dict[str, Any], trainer: Dict[str, Any]) -> Dict[str, Any]:
    min_exp = max(_safe_float(requirement.get("min_experience_years"), 2.0), 0.0)
    actual = _trainer_experience_years(trainer)

    if min_exp <= 0 and actual > 0:
        score = EXPERIENCE_WEIGHT
    elif actual >= min_exp:
        score = min(EXPERIENCE_WEIGHT, round(11 + min(actual - min_exp, 8) * 0.5))
    elif actual > 0:
        score = round((actual / max(min_exp, 1.0)) * 10)
    else:
        score = 0

    return {
        "score": min(score, EXPERIENCE_WEIGHT),
        "max": EXPERIENCE_WEIGHT,
        "actual": actual,
        "required": min_exp,
    }


def _score_delivery(requirement: Dict[str, Any], trainer: Dict[str, Any], profile_text: str) -> Dict[str, Any]:
    pref_location = _norm(requirement.get("preferred_location", ""))
    trainer_location = _norm(trainer.get("location", ""))
    mode = _norm(requirement.get("mode", ""))
    audience_level = _norm(requirement.get("audience_level", ""))
    language = _norm(requirement.get("language_of_training", ""))

    score = 0
    detail: Dict[str, Any] = {}

    if pref_location:
        location_match = pref_location in trainer_location or trainer_location in pref_location
        score += 4 if location_match else 0
        detail["location_match"] = location_match
    else:
        score += 3
        detail["location_match"] = "not_required"

    if mode:
        online_terms = {"online", "remote", "virtual"}
        offline_terms = {"offline", "classroom", "onsite", "on site"}
        mode_match = (
            _contains_term(profile_text, mode)
            or (mode in online_terms and any(_contains_term(profile_text, term) for term in online_terms))
            or (mode in offline_terms and any(_contains_term(profile_text, term) for term in offline_terms))
        )
        score += 3 if mode_match else 1
        detail["mode_match"] = mode_match
    else:
        score += 2
        detail["mode_match"] = "not_required"

    context_terms = [term for term in [audience_level, language] if term]
    context_matches = [term for term in context_terms if _contains_term(profile_text, term)]
    if context_terms:
        score += round((len(context_matches) / len(context_terms)) * 3)
    else:
        score += 2

    detail["context_matches"] = context_matches
    return {
        "score": min(score, DELIVERY_WEIGHT),
        "max": DELIVERY_WEIGHT,
        "trainer_location": trainer.get("location", ""),
        **detail,
    }


def _score_credibility(requirement: Dict[str, Any], trainer: Dict[str, Any], profile_text: str) -> Dict[str, Any]:
    required_certs = _as_list(requirement.get("required_certifications"))
    cert_text = _norm(trainer.get("certifications"))
    matched_certs = [
        cert for cert in required_certs
        if _contains_term(cert_text, cert) or _contains_term(profile_text, cert)
    ]

    if required_certs:
        cert_score = round((len(matched_certs) / max(len(required_certs), 1)) * 4)
    else:
        cert_score = 3 if _as_list(trainer.get("certifications")) else 1

    completeness_checks = [
        bool(_trainer_email(trainer)),
        bool(_clean_string(trainer.get("phone") or trainer.get("trainer_phone"))),
        bool(_clean_string(trainer.get("linkedin"))),
        bool(_clean_string(trainer.get("resume"))),
        bool(_clean_string(trainer.get("summary"))),
        bool(_as_list(trainer.get("past_clients"))),
    ]
    completeness_score = round((sum(completeness_checks) / len(completeness_checks)) * 6)

    return {
        "score": min(cert_score + completeness_score, CREDIBILITY_WEIGHT),
        "max": CREDIBILITY_WEIGHT,
        "matched_certifications": matched_certs,
        "profile_completeness": sum(completeness_checks),
    }


def _score_availability(trainer: Dict[str, Any]) -> Dict[str, Any]:
    email = _trainer_email(trainer)
    phone = _clean_string(trainer.get("phone") or trainer.get("trainer_phone"))
    teams = _clean_string(trainer.get("teams_email") or trainer.get("microsoft_teams_email") or trainer.get("teams_upn"))
    status = _clean_string(trainer.get("status")).lower()

    score = 0
    if email:
        score += 3
    if phone or teams:
        score += 1
    if status not in {"declined", "confirmed", "interested"}:
        score += 1

    return {
        "score": min(score, AVAILABILITY_WEIGHT),
        "max": AVAILABILITY_WEIGHT,
        "has_email": bool(email),
        "has_phone_or_teams": bool(phone or teams),
        "current_status": status,
    }


def _quality_band(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "strong"
    if score >= 55:
        return "good"
    if score >= 35:
        return "review"
    return "weak"


def _suggested_action(trainer: Dict[str, Any]) -> str:
    score = _safe_float(trainer.get("match_score"), 0)
    if score >= 70 and _trainer_email(trainer):
        return "Contact trainer for availability and commercial confirmation"
    if score >= 55:
        return "Review profile evidence before contacting"
    if not _trainer_email(trainer):
        return "Find or verify trainer email before outreach"
    return "Keep as backup only if stronger matches are unavailable"


def validation_agent(state: PipelineState) -> PipelineState:
    """Score every candidate against the normalized requirement with auditable evidence."""
    trainers = state.get("trainers", [])
    requirement = state.get("normalized_requirements", state.get("requirements", {}))

    must_linkedin = bool(requirement.get("must_have_linkedin", False))
    must_resume = bool(requirement.get("must_have_resume", False))

    validated: List[Dict[str, Any]] = []
    for trainer in trainers:
        profile_text = _trainer_profile_text(trainer)

        breakdown = {
            "technology": _score_technology(requirement, trainer, profile_text),
            "skills": _score_skills(requirement, profile_text),
            "experience": _score_experience(requirement, trainer),
            "delivery": _score_delivery(requirement, trainer, profile_text),
            "credibility": _score_credibility(requirement, trainer, profile_text),
            "availability": _score_availability(trainer),
        }

        score = round(sum(item["score"] for item in breakdown.values()), 2)
        has_linkedin = bool(_clean_string(trainer.get("linkedin")) and len(_clean_string(trainer.get("linkedin"))) > 5)
        has_resume = bool(_clean_string(trainer.get("resume")) and len(_clean_string(trainer.get("resume"))) > 5)

        filter_reasons: List[str] = []
        if must_linkedin and not has_linkedin:
            filter_reasons.append("LinkedIn required but missing")
        if must_resume and not has_resume:
            filter_reasons.append("Resume required but missing")

        validated.append({
            **trainer,
            "name": _trainer_name(trainer),
            "email": _trainer_email(trainer) or trainer.get("email", ""),
            "rule_match_score": score,
            "match_score": score,
            "score_breakdown": breakdown,
            "match_quality": _quality_band(score),
            "has_linkedin": has_linkedin,
            "has_resume": has_resume,
            "passed_filters": not filter_reasons,
            "filter_reasons": filter_reasons,
            "matching_pipeline_version": PIPELINE_VERSION,
        })

    state["validated_trainers"] = validated
    state["status"] = "validated"
    _append_stage(
        state,
        "validation",
        "completed",
        {
            "validated_count": len(validated),
            "passed_filters": sum(1 for trainer in validated if trainer.get("passed_filters")),
            "score_model": {
                "technology": TECHNOLOGY_WEIGHT,
                "skills": SKILLS_WEIGHT,
                "experience": EXPERIENCE_WEIGHT,
                "delivery": DELIVERY_WEIGHT,
                "credibility": CREDIBILITY_WEIGHT,
                "availability": AVAILABILITY_WEIGHT,
            },
        },
    )
    return state


def _strip_json_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith(CODE_FENCE):
        cleaned = re.sub(r"^" + re.escape(CODE_FENCE) + r"(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(re.escape(CODE_FENCE) + r"$", "", cleaned).strip()
    return cleaned


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    cleaned = _strip_json_fence(text)
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
    for trainer in trainers[:MAX_AI_CANDIDATES]:
        trainer_summaries.append({
            "trainer_id": trainer.get("trainer_id"),
            "name": trainer.get("name"),
            "rule_match_score": trainer.get("rule_match_score", trainer.get("match_score", 0)),
            "match_quality": trainer.get("match_quality"),
            "primary_category": trainer.get("primary_category") or trainer.get("technology_category"),
            "secondary_categories": trainer.get("secondary_categories", []),
            "domain": trainer.get("domain", ""),
            "skills": _as_list(trainer.get("skills"), limit=20),
            "specialisation_tags": _as_list(trainer.get("specialisation_tags") or trainer.get("specialty_tags"), limit=10),
            "industry_focus": _as_list(trainer.get("industry_focus"), limit=8),
            "skill_level_map": trainer.get("skill_level_map", {}),
            "experience_years": trainer.get("experience_years", 0),
            "certifications": _as_list(trainer.get("certifications"), limit=12),
            "summary": _clean_string(trainer.get("summary"))[:900],
            "past_clients": _as_list(trainer.get("past_clients"), limit=10),
            "score_breakdown": trainer.get("score_breakdown", {}),
        })

    return f"""You are a senior training delivery matcher.
Score each trainer for this client requirement using evidence only.
Prefer trainers whose primary specialty, skills, delivery history, experience, and certifications align with the requirement.
Do not reward generic profiles when a specialist is available.

Requirement:
{json.dumps(requirements, ensure_ascii=False, default=str)}

Candidate trainers:
{json.dumps(trainer_summaries, ensure_ascii=False, default=str)}

Return ONLY valid JSON array. No markdown. No explanation outside JSON.
Each object must use exactly these keys:
[
  {{
    "trainer_id": "TR-123",
    "ai_match_score": 0-100,
    "confidence": 0.0-1.0,
    "ai_reason": "one concise evidence-based reason",
    "risk_flags": ["missing or weak evidence, if any"]
  }}
]"""


async def claude_scoring_agent(state: PipelineState) -> PipelineState:
    """Refine high-potential candidates with Claude when Anthropic credentials exist."""
    candidates = [
        trainer for trainer in state.get("validated_trainers", [])
        if trainer.get("passed_filters") and _safe_float(trainer.get("match_score"), 0) > 0
    ]
    if not candidates:
        state["ai_scoring_applied"] = False
        state["ai_scoring_candidate_count"] = 0
        state["status"] = "ai_scoring_skipped"
        _append_stage(state, "ai_scoring", "skipped", {"reason": "No candidates passed validation"})
        return state

    api_key = _anthropic_api_key()
    if not api_key:
        state["ai_scoring_applied"] = False
        state["ai_scoring_candidate_count"] = 0
        state["status"] = "ai_scoring_skipped"
        _append_stage(state, "ai_scoring", "skipped", {"reason": "ANTHROPIC_API_KEY not configured"})
        return state

    score_targets = sorted(candidates, key=lambda item: item.get("match_score", 0), reverse=True)[:MAX_AI_CANDIDATES]
    state["ai_scoring_candidate_count"] = len(score_targets)

    try:
        client = _anthropic_client(api_key)
        message = await client.messages.create(
            model=MATCHING_MODEL,
            max_tokens=2200,
            temperature=0,
            messages=[{"role": "user", "content": _ai_scoring_prompt(state.get("normalized_requirements", {}), score_targets)}],
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

        for trainer in state.get("validated_trainers", []):
            ai_item = ai_scores.get(trainer.get("trainer_id"))
            if not ai_item:
                continue
            ai_score = _clamp(_safe_float(ai_item.get("ai_match_score"), 0.0), 0.0, 100.0)
            confidence = _clamp(_safe_float(ai_item.get("confidence"), 0.7), 0.0, 1.0)
            ai_weight = 0.30 + (confidence * 0.15)
            rule_score = _safe_float(trainer.get("rule_match_score", trainer.get("match_score")), 0.0)
            blended = (rule_score * (1 - ai_weight)) + (ai_score * ai_weight)

            trainer["ai_match_score"] = round(ai_score, 2)
            trainer["ai_match_confidence"] = round(confidence, 2)
            trainer["ai_match_reason"] = _clean_string(ai_item.get("ai_reason"))[:300]
            trainer["risk_flags"] = _as_list(ai_item.get("risk_flags"), limit=5)
            trainer["match_score"] = round(blended, 2)
            trainer["match_quality"] = _quality_band(blended)

        state["ai_scoring_applied"] = True
        state["status"] = "ai_scored"
        _append_stage(
            state,
            "ai_scoring",
            "completed",
            {"scored_count": len(ai_scores), "model": MATCHING_MODEL},
        )
    except Exception as exc:
        state.setdefault("errors", []).append(f"Claude scoring unavailable: {exc}")
        state["ai_scoring_applied"] = False
        state["status"] = "ai_scoring_fallback"
        _append_stage(state, "ai_scoring", "fallback", {"reason": str(exc)})

    return state


def ranking_agent(state: PipelineState) -> PipelineState:
    """Rank validated trainers and mark the top shortlist candidates."""
    requirement = state.get("normalized_requirements", state.get("requirements", {}))
    top_n = max(1, min(_safe_int(requirement.get("top_n"), DEFAULT_TOP_N), 20))

    passed = [
        trainer for trainer in state.get("validated_trainers", [])
        if trainer.get("passed_filters") and _safe_float(trainer.get("match_score"), 0) > 0
    ]

    ranked = sorted(
        passed,
        key=lambda trainer: (
            _safe_float(trainer.get("match_score"), 0),
            _safe_float(trainer.get("experience_years"), 0),
            1 if _trainer_email(trainer) else 0,
        ),
        reverse=True,
    )

    for index, trainer in enumerate(ranked, start=1):
        trainer["rank"] = index
        trainer["match_quality"] = _quality_band(_safe_float(trainer.get("match_score"), 0))
        trainer["recommended_next_action"] = _suggested_action(trainer)
        trainer["pipeline_status"] = "shortlisted" if index <= top_n else "qualified_backup"

    state["ranked_trainers"] = ranked
    state["top_trainers"] = ranked[:top_n]
    state["status"] = "ranked"
    _append_stage(
        state,
        "ranking",
        "completed",
        {
            "ranked_count": len(ranked),
            "top_count": len(state["top_trainers"]),
            "excellent_or_strong": sum(1 for trainer in ranked if trainer.get("match_quality") in {"excellent", "strong"}),
        },
    )
    return state


def _requirement_detail_lines(requirement: Dict[str, Any]) -> List[str]:
    line_map = [
        ("Technology", requirement.get("technology_needed")),
        ("Role", requirement.get("job_title")),
        ("Mode", requirement.get("mode") or requirement.get("training_mode")),
        ("Location", requirement.get("preferred_location")),
        ("Duration", requirement.get("training_duration") or requirement.get("duration") or requirement.get("duration_days")),
        ("Participants", requirement.get("participant_count") or requirement.get("participants")),
        ("Audience", requirement.get("audience_level")),
        ("Reference", requirement.get("requirement_id")),
    ]
    lines = [f"- {label}: {_clean_string(value)}" for label, value in line_map if _clean_string(value)]
    return lines or ["- Requirement details will be shared after your availability is confirmed."]


def _email_signature() -> str:
    settings = get_settings()
    sender_name = _clean_string(getattr(settings, "from_name", "")) or "TrainerSync Coordination Team"
    sender_email = (
        _clean_string(getattr(settings, "from_email", ""))
        or _clean_string(getattr(settings, "gmail_user", ""))
    )
    if sender_email:
        return f"{sender_name}\n{sender_email}"
    return sender_name


def email_composer_agent(state: PipelineState) -> PipelineState:
    """Prepare professional first-touch trainer outreach payloads for the selected shortlist."""
    requirement = state.get("normalized_requirements", state.get("requirements", {}))
    technology = requirement.get("technology_needed") or "training"
    req_id = requirement.get("requirement_id", "REQ")
    detail_lines = "\n".join(_requirement_detail_lines(requirement))
    signature = _email_signature()

    payloads: List[Dict[str, Any]] = []
    for trainer in state.get("top_trainers", []):
        to_email = _trainer_email(trainer)
        if not to_email:
            continue

        trainer_name = _trainer_name(trainer)
        reason = (
            trainer.get("ai_match_reason")
            or f"your profile aligns with {technology} and the current requirement criteria"
        )
        subject = f"Trainer availability request: {technology} | {req_id}"
        body = f"""Dear {trainer_name},

I hope you are doing well.

We are coordinating a client training requirement and your profile looks relevant for this engagement because {reason}.

Requirement snapshot:
{detail_lines}

Could you please reply with:
1. Your availability for the proposed schedule or nearest available slots.
2. Your commercial expectations.
3. Preferred delivery mode and any constraints.
4. An updated profile or course outline, if available.

We will share the final client schedule and discussion details after your confirmation.

Regards,
{signature}
"""

        payloads.append({
            "trainer_id": trainer.get("trainer_id", ""),
            "trainer_name": trainer_name,
            "to": to_email,
            "subject": subject,
            "body": body,
            "requirement_id": req_id,
            "rank": trainer.get("rank"),
            "match_score": trainer.get("match_score"),
            "match_quality": trainer.get("match_quality"),
            "recommended_next_action": trainer.get("recommended_next_action"),
            "email_stage": 1,
            "status": "pending",
            "retry_count": 0,
            "composed_at": utc_now().isoformat(),
        })

    state["email_payloads"] = payloads
    state["status"] = "emails_composed"
    _append_stage(
        state,
        "email_composition",
        "completed",
        {
            "payload_count": len(payloads),
            "skipped_without_email": len(state.get("top_trainers", [])) - len(payloads),
        },
    )
    return state


def finalizer_agent(state: PipelineState) -> PipelineState:
    ranked = state.get("ranked_trainers", [])
    top = state.get("top_trainers", [])
    state["pipeline_summary"] = {
        "pipeline_version": PIPELINE_VERSION,
        "status": "completed",
        "total_candidates": state.get("total_candidates", len(state.get("trainers", []))),
        "category_filter_applied": state.get("category_filter_applied", False),
        "category_match_count": state.get("category_match_count", 0),
        "validated_count": len(state.get("validated_trainers", [])),
        "ranked_count": len(ranked),
        "top_count": len(top),
        "email_payload_count": len(state.get("email_payloads", [])),
        "ai_scoring_applied": state.get("ai_scoring_applied", False),
        "warnings": state.get("warnings", []),
        "errors": state.get("errors", []),
        "completed_at": utc_now().isoformat(),
    }
    state["status"] = "completed"
    _append_stage(state, "finalize", "completed", state["pipeline_summary"])
    return state


@lru_cache(maxsize=1)
def build_pipeline():
    graph = StateGraph(PipelineState)

    graph.add_node("requirement_normalizer_agent", requirement_normalizer_agent)
    graph.add_node("category_filter_agent", _category_filter_agent)
    graph.add_node("validation_agent", validation_agent)
    graph.add_node("claude_scoring_agent", claude_scoring_agent)
    graph.add_node("ranking_agent", ranking_agent)
    graph.add_node("email_composer_agent", email_composer_agent)
    graph.add_node("finalizer_agent", finalizer_agent)

    graph.set_entry_point("requirement_normalizer_agent")
    graph.add_edge("requirement_normalizer_agent", "category_filter_agent")
    graph.add_edge("category_filter_agent", "validation_agent")
    graph.add_edge("validation_agent", "claude_scoring_agent")
    graph.add_edge("claude_scoring_agent", "ranking_agent")
    graph.add_edge("ranking_agent", "email_composer_agent")
    graph.add_edge("email_composer_agent", "finalizer_agent")
    graph.add_edge("finalizer_agent", END)

    return graph.compile()


async def run_pipeline(trainers: List[Dict[str, Any]], requirements: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full trainer matching pipeline and return a backwards-compatible state."""
    pipeline = build_pipeline()

    initial_state: PipelineState = {
        "trainers": list(trainers or []),
        "requirements": dict(requirements or {}),
        "normalized_requirements": {},
        "validated_trainers": [],
        "ranked_trainers": [],
        "top_trainers": [],
        "email_payloads": [],
        "errors": [],
        "warnings": [],
        "status": "started",
        "category_filter_applied": False,
        "no_category_match": False,
        "category_match_count": 0,
        "total_candidates": len(trainers or []),
        "ai_scoring_applied": False,
        "ai_scoring_candidate_count": 0,
        "stage_log": [],
        "pipeline_summary": {},
    }

    return await pipeline.ainvoke(initial_state)

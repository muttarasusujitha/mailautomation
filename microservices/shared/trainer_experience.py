"""Conservative extraction of explicit professional experience durations."""
import re
from typing import Optional


DOMAIN_ALIASES = {
    "DevOps": ("devops", "site reliability engineering", "sre"),
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure", "microsoft azure"),
    "GCP": ("gcp", "google cloud platform", "google cloud"),
    "Kubernetes": ("kubernetes", "k8s"),
    "Docker": ("docker",),
    "Python": ("python",),
    "Java": ("java",),
    "JavaScript": ("javascript",),
    "React": ("react", "react.js", "reactjs"),
    "Data Engineering": ("data engineering", "data engineer"),
    "Data Science": ("data science", "data scientist"),
    "Machine Learning": ("machine learning", "ml"),
    "Generative AI": ("generative ai", "gen ai", "llm"),
    "Salesforce": ("salesforce",),
    "SAP": ("sap",),
    "ServiceNow": ("servicenow", "service now"),
    "Cybersecurity": ("cybersecurity", "cyber security",),
    "SQL": ("sql",),
    "Power BI": ("power bi",),
    "Tableau": ("tableau",),
}


_NUMBER = r"(\d{1,2}(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)"
_EXPERIENCE_PATTERNS = (
    re.compile(rf"\b(?:total|professional)\s+experience\s*(?:is|of|:|-)?\s*{_NUMBER}\b", re.I),
    re.compile(rf"\b{_NUMBER}\s+(?:of\s+)?(?:total\s+|professional\s+)?experience\b", re.I),
    re.compile(rf"\bexperience\s*(?:is|of|:|-)?\s*{_NUMBER}\b", re.I),
)


def extract_experience_years(text: object) -> Optional[float]:
    """Return years only when resume text explicitly ties them to experience."""
    source = str(text or "")
    for pattern in _EXPERIENCE_PATTERNS:
        match = pattern.search(source)
        if match:
            try:
                value = float(match.group(1))
            except (TypeError, ValueError):
                continue
            if 0 <= value <= 60:
                return value
    return None


def profile_experience_years(profile: object) -> Optional[float]:
    """Prefer explicit years in stored source text over a conflicting parsed field."""
    if not isinstance(profile, dict):
        return None
    for key in ("resume", "combined_text", "summary", "experience_raw"):
        value = extract_experience_years(profile.get(key))
        if value is not None:
            return value
    try:
        value = float(profile.get("experience_years"))
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 60 else None


def extract_domain_experience(text: object) -> dict[str, float]:
    """Extract domain-specific years only when the resume ties duration to a domain."""
    source = str(text or "")
    results: dict[str, float] = {}
    number = r"(\d{1,2}(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)"
    patterns = (
        re.compile(rf"\b{number}\s+(?:of\s+)?(?:hands-on\s+|professional\s+|relevant\s+)?", re.I),
        re.compile(rf"\b(?:experience|expertise)\s+(?:in|with|of)\s+", re.I),
    )
    for domain, aliases in DOMAIN_ALIASES.items():
        escaped = "(?:" + "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True)) + ")"
        candidates = []
        # Explicit forms: "5 years of AWS experience" or "AWS: 5 years experience".
        candidates.extend(re.finditer(
            rf"\b{number}\s+(?:of\s+)?(?:hands-on\s+|professional\s+|relevant\s+)?{escaped}\s+(?:experience|expertise)\b",
            source, re.I,
        ))
        candidates.extend(re.finditer(
            rf"\b{escaped}\s*[:\-]\s*{number}\s*(?:of\s+)?(?:years?\s+)?(?:experience|expertise)?",
            source, re.I,
        ))
        candidates.extend(re.finditer(
            rf"\b(?:experience|expertise)\s+(?:in|with|of)\s+{escaped}\s*[:\-]?\s*{number}",
            source, re.I,
        ))
        for match in candidates:
            values = re.findall(r"\d{1,2}(?:\.\d+)?", match.group(0))
            if values:
                value = float(values[-1])
                if 0 <= value <= 60:
                    results[domain] = max(results.get(domain, 0.0), value)
    return results

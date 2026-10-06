"""Accuracy rules shared with the Tavily trainer search, without calling that API."""
import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit


TRAINER_QUERY_SUFFIXES = (
    "corporate trainer",
    "freelance trainer",
    "technical trainer",
    "online trainer",
    "training consultant",
    "trainer instructor",
)

_GENERIC_SKILL_WORDS = {"trainer", "instructor", "training"}
_TRAINER_LANGUAGE = re.compile(
    r"\b(trainer|instructor|corporate training|training consultant|facilitator|coach)\b",
    re.IGNORECASE,
)


def trainer_public_queries(domain, location=""):
    """Ask a public results page for trainer profiles.

    The wording is a normal trainer search. Domain lock, the skill check, and
    the older-year check are applied to each result link.
    """
    skill = (domain or "").strip()
    place = (location or "").strip()
    return [" ".join(part for part in (skill, suffix, place) if part) for suffix in TRAINER_QUERY_SUFFIXES]


def matches_requested_skill(profile, search_text) -> bool:
    """The requested technology must appear in the title, snippet, or profile URL."""
    wanted = re.sub(r"[^a-z0-9+#. ]+", " ", (search_text or "").lower()).strip()
    if not wanted:
        return True
    haystack = " ".join([
        str(profile.get("title") or ""),
        str(profile.get("snippet") or ""),
        str(profile.get("content") or ""),
        str(profile.get("slug") or ""),
        str(profile.get("source_url") or profile.get("url") or ""),
    ]).lower()
    tokens = [
        token for token in wanted.split()
        if len(token) > 1 and token not in _GENERIC_SKILL_WORDS
    ]
    if not tokens:
        return True
    return any(token in haystack for token in tokens)


def is_current_year_result(profile) -> bool:
    """Reject a result that explicitly advertises an older year."""
    current_year = datetime.utcnow().year
    haystack = " ".join([
        str(profile.get("title") or ""),
        str(profile.get("snippet") or ""),
        str(profile.get("content") or ""),
    ])
    years = [int(year) for year in re.findall(r"\b20\d{2}\b", haystack)]
    return not years or max(years) >= current_year


def has_trainer_language(profile) -> bool:
    haystack = " ".join([
        str(profile.get("title") or ""),
        str(profile.get("snippet") or ""),
        str(profile.get("content") or ""),
    ])
    return bool(_TRAINER_LANGUAGE.search(haystack))


def is_trainer_profile_url(url) -> bool:
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https"):
        return False
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return parts.path.startswith("/in/")
    if host == "naukri.com" or host.endswith(".naukri.com"):
        return bool(parts.path.strip("/"))
    return False


def select_accurate_profiles(rows, search_text):
    """Keep current-year trainer profiles whose text matches the requested skill."""
    kept = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = row.get("url") or row.get("source_url") or row.get("link") or ""
        if not is_trainer_profile_url(url):
            continue
        if not has_trainer_language(row):
            continue
        if not matches_requested_skill(row, search_text):
            continue
        if not is_current_year_result(row):
            continue
        kept.append(row)
    return kept


def canonical_public_url(value):
    """Normalize a LinkedIn profile URL, and keep a Naukri profile URL."""
    from app.clients.linkedin_browser import canonical_url

    linkedin = canonical_url(value)
    if linkedin:
        return linkedin
    parts = urlsplit(value or "")
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https"):
        return ""
    if not (host == "naukri.com" or host.endswith(".naukri.com")):
        return ""
    if not parts.path.strip("/"):
        return ""
    return urlunsplit(("https", "www.naukri.com", parts.path.rstrip("/"), "", ""))

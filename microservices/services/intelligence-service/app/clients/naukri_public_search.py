"""Find publicly indexed Naukri job-seeker profile pages only.

This reads result links from public search pages. It does not open candidate
pages, log in, access the private resume database, or bypass access checks.
"""
import re
from urllib.parse import urlsplit, urlunsplit

from app.clients.public_search import search_public_many
from app.clients.search_accuracy import matches_requested_skill

_NAUKRI_HOST = re.compile(r"(^|\.)naukri\.com$", re.IGNORECASE)
_PROFILE_PATH = re.compile(
    r"(?:^|/)(?:resume|profile|candidate)(?:/|$)|(?:^|/)(?:resume|candidate|profile)-",
    re.IGNORECASE,
)
_NON_PROFILE_PATH = re.compile(
    r"(?:^|/)(?:jobs?|job-listings?|career-advice|profile-summary|blog|campus|companies|company|"
    r"services|resume-maker|resume-templates|recruiter-zone)(?:/|$)|-jobs?(?:-|$)",
    re.IGNORECASE,
)


def public_profile_url(value):
    """Return a clean Naukri URL only when its path identifies a public profile."""
    try:
        parts = urlsplit(str(value or ""))
        port = parts.port
    except ValueError:
        return ""
    if (
        parts.scheme not in ("http", "https")
        or parts.username or parts.password
        or port not in (None, 443)
        or not _NAUKRI_HOST.search(parts.hostname or "")
    ):
        return ""
    path = parts.path.rstrip("/")
    if not path or _NON_PROFILE_PATH.search(path) or not _PROFILE_PATH.search(path):
        return ""
    return urlunsplit(("https", parts.netloc.lower(), path, "", ""))


def public_profile_queries(skill, location=""):
    """Build focused public-index searches for job-seeker profiles."""
    skill = " ".join(str(skill or "").split())
    location = " ".join(str(location or "").split())
    if not skill:
        return []
    suffix = f" {location}" if location else ""
    return [
        f"site:naukri.com/resume {skill}{suffix}",
        f"site:naukri.com/profile {skill}{suffix}",
        f"site:naukri.com/candidate {skill}{suffix}",
        f"site:naukri.com {skill} profile{suffix}",
    ]


async def search_public_naukri_profiles(skill, location="", limit=20):
    """Return public Naukri profile links surfaced by public search indexes."""
    target = min(max(int(limit or 1), 1), 30)
    queries = public_profile_queries(skill, location)
    if not queries:
        return []
    rows, _attempts = await search_public_many(queries, target * 2, ["naukri.com"])
    profiles = []
    seen = set()
    for row in rows:
        url = public_profile_url(row.get("url") or row.get("source_url") or row.get("link"))
        if not url or url in seen or not matches_requested_skill(row, skill):
            continue
        seen.add(url)
        path_slug = re.sub(r"[^a-zA-Z0-9]+", "-", urlsplit(url).path).strip("-")[:80]
        profiles.append({
            "source_url": url,
            "slug": path_slug,
            "source": "naukri",
            "title": str(row.get("title") or "Naukri job seeker")[:160],
            "snippet": str(row.get("content") or row.get("snippet") or "")[:300],
        })
        if len(profiles) >= target:
            break
    return profiles

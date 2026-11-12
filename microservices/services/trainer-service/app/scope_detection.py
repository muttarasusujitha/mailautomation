"""Find every catalog technology a client asks for, with any stated days and levels.

The catalog is built from every course file (datasets_compact and datasets_levels):
domain names, display names and aliases. Matching is case-insensitive, on word
boundaries, longest phrase first, so "Java Full Stack" is one technology rather
than Java plus Full Stack, and "Azure DevOps" is the Azure DevOps product.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

_APP = Path(__file__).parent
_LEVEL_WORDS = {
    "beginner": "beginner", "basic": "beginner", "basics": "beginner", "foundation": "beginner",
    "foundational": "beginner", "fundamentals": "beginner",
    "intermediate": "intermediate", "intermidate": "intermediate",
    "advanced": "advanced", "advance": "advanced", "expert": "advanced",
}
# Technologies recognised before the catalog existed; kept so their wording still matches.
_EXTRA_ALIASES = {
    "Kubernetes": ["kubernetes", "k8s"],
    "Agentic AI": ["agentic ai", "ai agents", "ai agent"],
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure", "microsoft azure"],
    "DevOps": ["devops", "cloud devops"],
}
# Aliases that are ordinary words or too short to be reliable on their own.
_IGNORED_ALIASES = {"r", "rn", "cv", "dl", "mean", "snow", "mas", "ado", "edw", "bi", "ml", "dsa", "ai", "api", "apis", "llm", "llms"}
# The technologies recognised before the catalog: they are never folded into another
# requested technology, and they are the only ones read from free-text notes.
LEGACY_TECHNOLOGIES = ("DevOps", "AWS", "Azure", "Kubernetes", "Python", "Agentic AI")
# Broad words: only counted in the client's stated scope (title, technology, topics),
# not in free-text notes, and dropped when a more specific technology of the same
# family is also requested (for example "cloud" when AWS is named).
_WEAK_ALIASES = {"cloud", "testing", "qa", "agile", "observability", "monitoring", "automation", "security"}
_UMBRELLAS = {"Cloud": {"AWS", "Azure", "AWS AI", "Azure AI"}}
_PRIOR_KNOWLEDGE = re.compile(
    r"\b(?:know|knows|knowledge of|familiar with|experience (?:in|with)|experienced in|"
    r"prerequisites?|prior|already (?:use|using|work with))\s+(?:[a-z0-9+#.]+\s+){0,3}$")


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9+#./& ]+", " ", str(value or "").lower()).split())


def _course_files():
    files = sorted((_APP / "datasets_compact").glob("*.json"))
    files += [p for p in sorted((_APP / "datasets_levels").glob("*.json"))
              if p.name not in {"categories.json", "combined.json"}]
    return files


@lru_cache(maxsize=1)
def _raw_aliases():
    """domain -> every alias any course file lists for it (before resolving shared aliases)."""
    raw = {}
    for path in _course_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError):
            continue
        domain = str(data.get("domain") or "").strip()
        if not domain:
            continue
        for alias in (domain, data.get("name"), *(data.get("aliases") or [])):
            key = _norm(alias)
            if key and key not in _IGNORED_ALIASES:
                raw.setdefault(domain, set()).add(key)
    return raw


@lru_cache(maxsize=1)
def _catalog():
    """alias -> canonical domain, resolving aliases shared by several courses."""
    candidates = {}
    for domain, aliases in _raw_aliases().items():
        for key in aliases:
            candidates.setdefault(key, set()).add(domain)
    for domain, aliases in _EXTRA_ALIASES.items():
        for alias in aliases:
            candidates[_norm(alias)] = {domain}
    catalog = {}
    for alias, domains in candidates.items():
        # Prefer the course whose own name is this alias; otherwise the most specific one.
        own = [d for d in domains if _norm(d) == alias]
        specific = [d for d in domains if d not in _UMBRELLAS and d not in {"DevOps", "Agentic AI", "Machine Learning", "Data Engineering", "Full Stack"}]
        catalog[alias] = sorted(own or specific or domains)[0]
    return catalog


def _mentions(text, include_weak):
    """[(start, end, domain, alias)] for non-overlapping catalog phrases, longest first."""
    norm = _norm(text)
    taken = [False] * len(norm)
    found = []
    for alias in sorted(_catalog(), key=len, reverse=True):
        if not include_weak and alias in _WEAK_ALIASES:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        for match in re.finditer(pattern, norm):
            if any(taken[match.start():match.end()]):
                continue
            for index in range(match.start(), match.end()):
                taken[index] = True
            found.append((match.start(), match.end(), _catalog()[alias], alias))
    return norm, sorted(found)


def detect_technologies(primary_text, secondary_text=""):
    """Requested technologies in order of first mention.

    primary_text is the client's stated scope (title, technology, topics), read
    against the whole catalog. secondary_text is free text such as notes; only the
    legacy technologies are read from it, so a passing mention of a tool in the notes
    does not add a technology block.
    """
    order, matched, linked = {}, {}, {}
    for rank, (text, weak, allowed) in enumerate(((primary_text, True, None),
                                                  (secondary_text, False, set(LEGACY_TECHNOLOGIES)))):
        norm, mentions = _mentions(text, weak)
        for index, (start, _end, domain, alias) in enumerate(mentions):
            if allowed is not None and domain not in allowed:
                continue
            if _PRIOR_KNOWLEDGE.search(norm[max(0, start - 40):start]):
                # "participants already know Python" is a prerequisite, not a requested topic.
                continue
            if domain not in order:
                order[domain] = (rank, start)
                matched[domain] = alias
                # "X with Y and Z" / "X using Y": Y and Z are introduced as parts of X.
                first_end = mentions[0][1] if index else 0
                linked[domain] = bool(index and re.search(
                    r"\b(?:with|using|including|via|in|on|for)\b", norm[first_end:start]))
    detected = sorted(order, key=order.get)
    for umbrella, specifics in _UMBRELLAS.items():
        if umbrella in detected and any(item in specifics for item in detected):
            detected.remove(umbrella)
    # "Agentic AI with LangGraph": LangGraph is also listed as part of Agentic AI and is
    # introduced with "with", so it stays a topic inside Agentic AI. A tool word such as
    # "Docker" (not its own course name) is always folded into the course that lists it.
    # A course named in a plain list ("ML, Deep Learning and CV") stays separate, and
    # legacy technologies (for example DevOps and Kubernetes) always stay separate.
    raw = _raw_aliases()

    def folded(domain):
        if domain in LEGACY_TECHNOLOGIES:
            return False
        own_name = matched[domain] == _norm(domain)
        return any(other != domain and matched[domain] in raw.get(other, set()) for other in detected) \
            and (not own_name or linked[domain])

    return [domain for domain in detected if not folded(domain)]


def stated_plan(text, technologies):
    """Days and levels the client wrote next to each technology.

    Days: "Python 5 days", "Python (5 days)", "5 days of Python".
    Levels: "advanced AWS", "AWS (beginner)". Levels are only used when the
    text mixes at least two different levels; a single word such as
    "Advanced DevOps with AWS" describes the whole programme instead.
    """
    norm, mentions = _mentions(text, True)
    wanted = set(technologies)
    days, levels = {}, {}
    mentions = [m for m in mentions if m[2] in wanted]
    for index, (start, end, domain, _alias) in enumerate(mentions):
        next_start = mentions[index + 1][0] if index + 1 < len(mentions) else len(norm)
        previous_end = mentions[index - 1][1] if index else 0
        after = norm[end:min(next_start, end + 25)]
        before = norm[max(previous_end, start - 25):start]
        day_match = re.match(r"^\W{0,3}(?:for|-|:)?\s*(\d{1,2})\s*(?:days?|d)\b", after) \
            or re.search(r"(\d{1,2})\s*days?\s*(?:of|on|for)?\s*$", before)
        if day_match and domain not in days:
            days[domain] = int(day_match.group(1))
        level_match = re.search(r"\b(" + "|".join(_LEVEL_WORDS) + r")\s*(?:level\s*)?$", before) \
            or re.match(r"^\W{0,3}(" + "|".join(_LEVEL_WORDS) + r")\b", after)
        if level_match and domain not in levels:
            levels[domain] = _LEVEL_WORDS[level_match.group(1)]
    if len(set(levels.values())) < 2:
        levels = {}
    return days, levels

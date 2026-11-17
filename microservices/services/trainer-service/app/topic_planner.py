"""Design a TOC around the topics a client asked for, using every dataset for the technology.

When a requirement names topics ("Helm, RBAC, Network Policies"), the plan:
1. covers every named topic that any dataset teaches, preferring days at the requested level;
2. gives the named topics more depth while days remain;
3. fills the rest from the technology's normal plan for that level;
4. orders the days from foundations to advanced and ends with the level's capstone.
Topics no dataset teaches are reported, not invented.
"""
import re
from copy import deepcopy

from shared.toc_quality import normalize_topic, topic_is_covered

LEVEL_ORDER = {"beginner": 0, "intermediate": 1, "advanced": 2}


def requested_topic_list(text):
    topics = []
    for part in re.split(r"[;,\n]+", str(text or "")):
        part = part.strip(" .")
        if part and normalize_topic(part) not in {normalize_topic(t) for t in topics}:
            topics.append(part)
    return topics


def _is_capstone(day):
    return "capstone" in str(day.get("topic") or "").lower()


def _candidates(domain_name):
    """Every authored day for the technology, with its level and its place in the course."""
    from app.level_curriculum import LEVELS, get_level_course
    from app.toc_domain_dataset import same_technology_datasets
    pool = []
    course = get_level_course(domain_name)
    if course:
        for level in LEVELS:
            days = course["levels"][level]["days"]
            for index, day in enumerate(days):
                pool.append({"day": day, "level": level, "source": course.get("name") or course["domain"],
                             "order": LEVEL_ORDER[level] * 1000 + index * 1000 / max(1, len(days))})
    for data in same_technology_datasets(domain_name):
        days = data.get("days") or []
        for index, day in enumerate(days):
            # Catalog courses run from setup to production practice; spread them over the three levels.
            position = index / max(1, len(days))
            pool.append({"day": day, "level": None, "source": data.get("name") or data.get("domain"),
                         "order": position * 3000, "approx_level": min(2, int(position * 3))})
    return course, pool


def _topic_course(topic):
    """The level course for a topic that is itself a technology (Ansible inside a DevOps request)."""
    from app.level_curriculum import LEVELS, get_level_course
    course = get_level_course(topic)
    if not course:
        return []
    return [{"day": day, "level": level, "source": course.get("name") or course["domain"],
             "order": LEVEL_ORDER[level] * 1000 + index * 1000 / max(1, len(course["levels"][level]["days"]))}
            for level in LEVELS for index, day in enumerate(course["levels"][level]["days"])]


def _strength(topic, day):
    """2 when the day is about the topic, 1 when the topic is one of its subtopics, else 0."""
    title = str(day.get("topic") or "")
    if topic_is_covered(topic, title):
        return 2
    if topic_is_covered(topic, " ".join([title, *map(str, day.get("subtopics") or [])])):
        return 1
    return 0


def _level_distance(level, candidate):
    """Levels between the request and the day; catalog days use their place in the course."""
    if level == "mixed":
        return 0
    day_level = LEVEL_ORDER[candidate["level"]] if candidate["level"] else candidate.get("approx_level", 1)
    return abs(LEVEL_ORDER.get(level, 1) - day_level)


def _fit(topic, candidate, level):
    """How well a day serves a named topic for this group: a day about the topic at the
    right level is best; a day that only mentions it at the right level beats a day
    about it two levels away."""
    return 2 * _strength(topic, candidate["day"]) - _level_distance(level, candidate)


def plan_requested_topics(domain_name, topics_text, duration, level):
    """Return {"days", "covered", "missing", "level_notes", "levels_used"} or None when no topics are named."""
    from app.level_curriculum import _similar_topics, level_programme
    topics = requested_topic_list(topics_text)
    if not topics:
        return None
    duration = max(1, int(duration or 1))
    level = level if level in (*LEVEL_ORDER, "mixed") else "intermediate"
    course, pool = _candidates(domain_name)
    teaching = [c for c in pool if not _is_capstone(c["day"])]
    extra = {topic: [c for c in _topic_course(topic) if not _is_capstone(c["day"])] for topic in topics}
    slots = duration - (1 if duration >= 5 else 0)
    chosen = []

    def already_chosen(candidate):
        return any(str(candidate["day"].get("topic")).lower() == str(c["day"].get("topic")).lower() for c in chosen)

    def similar_to_chosen(candidate):
        title = candidate["day"].get("topic")
        return any(str(title).lower() == str(c["day"].get("topic")).lower() or _similar_topics(title, c["day"].get("topic"))
                   for c in chosen)

    def ranked(topic, minimum=1):
        options = [c for c in teaching + extra[topic] if _strength(topic, c["day"]) >= minimum]
        return sorted(options, key=lambda c: (-_fit(topic, c, level), -_strength(topic, c["day"]),
                                              c["level"] is None, c["order"]))

    # 1. Cover every named topic; a day that covers several named topics counts for each.
    uncovered = [t for t in topics if ranked(t)]
    while uncovered and len(chosen) < slots:
        best = None
        for topic in uncovered:
            for candidate in ranked(topic):
                # A named topic may need a "Part 2" day next to its "Part 1"; only exact repeats are skipped here.
                if already_chosen(candidate):
                    continue
                gain = sum(_strength(t, candidate["day"]) > 0 for t in uncovered)
                key = (gain, _fit(topic, candidate, level), _strength(topic, candidate["day"]))
                if best is None or key > best[0]:
                    best = (key, candidate)
                break
        if best is None:
            break
        chosen.append(best[1])
        uncovered = [t for t in uncovered if _strength(t, best[1]["day"]) == 0]

    # 2. More depth on the named topics, taking them in turn.
    added = True
    while added and len(chosen) < slots:
        added = False
        for topic in topics:
            if len(chosen) >= slots:
                break
            for candidate in ranked(topic, minimum=2):
                if not similar_to_chosen(candidate) and _level_distance(level, candidate) <= 1:
                    chosen.append(candidate)
                    added = True
                    break

    # 3. Fill the remaining days from the technology's normal plan at this level.
    plan = level_programme(domain_name, duration, level) if course else None
    support = [c for c in teaching if plan and c["day"] in plan["days"]] or \
        [c for c in teaching if _level_distance(level, c) == 0] or teaching
    for candidate in sorted(support, key=lambda c: c["order"]):
        if len(chosen) >= slots:
            break
        if not similar_to_chosen(candidate):
            chosen.append(candidate)

    chosen.sort(key=lambda c: c["order"])
    days = [deepcopy(c["day"]) for c in chosen[:slots]]
    if duration >= 5:
        capstone = None
        if course:
            capstone_level = level if level in LEVEL_ORDER else "advanced"
            capstone = next((d for d in reversed(course["levels"][capstone_level]["days"]) if _is_capstone(d)), None)
        capstone = capstone or next((c["day"] for c in reversed(pool) if _is_capstone(c["day"])), None)
        if capstone:
            days.append(deepcopy(capstone))

    covered, missing, level_notes = {}, [], []
    for topic in topics:
        titles = [d.get("topic") for d in days if _strength(topic, d) > 0]
        if titles:
            covered[topic] = titles
        else:
            missing.append(topic)
        levels = {c["level"] for c in chosen if c["level"] and _strength(topic, c["day"]) > 0}
        if level in LEVEL_ORDER and levels and level not in levels:
            shown = ", ".join(sorted(levels, key=LEVEL_ORDER.get))
            if all(LEVEL_ORDER[found] < LEVEL_ORDER[level] for found in levels):
                level_notes.append(f"'{topic}' comes from the {shown} course; the trainer should teach it in more "
                                   f"depth for an {level} group.")
            else:
                level_notes.append(f"'{topic}' comes from the {shown} course; confirm the {level} group is "
                                   "ready for it.")
    levels_used = sorted({c["level"] for c in chosen if c["level"]}, key=LEVEL_ORDER.get)
    return {"days": days, "covered": covered, "missing": missing, "level_notes": level_notes,
            "levels_used": levels_used, "requested": topics,
            "certifications": list((course or {}).get("certifications") or []),
            "name": (course or {}).get("name") or (course or {}).get("domain") or domain_name}

"""Draft a detailed design for every module of a course with a model. Default is a local inventory.

    python -m app.draft_module_designs --course aws                    # count modules without a design; no API calls
    python -m app.draft_module_designs --course aws --run --limit 4    # draft 4 modules (paid API) and save them
    python -m app.draft_module_designs --run --per-course 2            # 2 modules from each default course

A design has 3-5 outcomes with how each is assessed, timed topics with mode,
failure scenario and best practice, a seeded lab failure, knowledge-check
questions, a lab rubric and the lab environment (see the Docker Fundamentals
design in authored_outlines.json, which is also the example the model follows).

Every draft is normalised and must pass ``design_problems`` plus the checks
below (no prices, real questions, a lab topic) before it is saved. A failing
draft gets one retry with its problems listed; if it still fails it is skipped
and reported, and a later run retries it. Designs are saved straight into the
course files as model drafts pending technical review, so an interrupted run
keeps its progress. Modules that already have a design are never redrafted.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path

from app.apply_authored_outlines import design_problems

ROOT = Path(__file__).parent
LEVEL_DIR = ROOT / "datasets_levels"
COMPACT_DIR = ROOT / "datasets_compact"
REVISION = "module-design-v1"
ORIGIN = "model_draft_pending_technical_review"
LEVELS = ("beginner", "intermediate", "advanced")
MODULE_MINUTES = 420
# The 15 most-requested courses in the mailbox archive (by dataset file).
DEFAULT_COURSES = ("generative_ai", "azure", "testing_qa", "sap", "devops_30", "devops_60", "csharp", "java",
                   "cybersecurity", "aws", "react", "oracle_database", "data_engineering", "sre", "python",
                   "salesforce")
_PRICE_RE = re.compile(r"[$\u20b9\u20ac\u00a3]\s?\d|\b\d[\d,.]*\s?(usd|inr|eur|gbp|dollars?|rupees?)\b|\bper (hour|month)\b", re.I)
_STANDARD = "90 minutes of concept topics (mode discussion), two demos totalling 60 minutes (mode demo, names start with 'Demo: '), one main lab of 150 minutes (mode lab, named 'Lab: <lab name>', subtopics are the participant tasks), 'Troubleshooting the seeded failure' for 60 minutes (mode lab), and 'Knowledge check and recap' for 60 minutes (mode discussion)"
_CAPSTONE = "'Capstone build' for 270 minutes (mode lab), 'Presentation and defence' for 90 minutes (mode discussion) and 'Review and feedback' for 60 minutes (mode discussion)"

INSTRUCTIONS = f"""You are a senior technical trainer designing modules of a corporate IT training course.
For each input module, write a detailed design that stays inside that module's topic, subtopics and lab.
Do not add topics from other modules. Write plain, short English sentences.

Return JSON only: {{"modules": [{{"key": "<input key>", "design": <design>}}]}} with one entry per input key.

A design has these fields:
- "outcomes": 3 to 5 measurable "can do" statements, each {{"outcome", "assessed_by"}}. assessed_by is one of
  "Lab check: <what is checked>", "Lab checks: <what is checked>", "Seeded-failure troubleshooting" or "Knowledge check".
- "topics": a list of {{"topic", "subtopics", "minutes", "mode", "failure_scenario", "best_practice"}}.
  mode is "discussion", "demo" or "lab". Each topic has 3 to 6 subtopics. Minutes must add up to the module minutes.
  A normal module has {_STANDARD}. A capstone module has {_CAPSTONE}.
  failure_scenario is one sentence with a realistic symptom and its cause that practitioners meet with that topic;
  use "" for recap, quiz and review topics. best_practice is one concrete practice, or "".
- "seeded_failure": {{"symptom", "cause", "fix"}} for a fault the trainer plants in the lab. The symptom says only what
  participants observe; the cause and fix are for the trainer.
- "quiz": 5 to 8 knowledge-check questions answerable from this module. Questions only, each ending with "?".
- "lab_rubric": exactly 4 criteria, each {{"criterion", "exceeds", "meets", "partly", "not_met"}}.
- "lab_environment": 2 to 6 rows for the tools the lab needs, each {{"tool", "version", "access", "setup_owner", "cost"}}.
  version is a minimum version you are certain of, or "Current stable release". setup_owner is Trainer, Client IT,
  Participant or a combination. cost never contains a price: use "No licence cost", "Free tier",
  "Licence required; confirm with the vendor" or "Priced in the Lab Cost Estimate".

Never invent client facts, prices, statistics, or version numbers you are not sure of.
Follow the style and depth of the example design, but do not copy its content."""


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _strings(value):
    return [_text(item) for item in (value or []) if _text(item)] if isinstance(value, list) else []


def _course_path(name):
    for directory in (LEVEL_DIR, COMPACT_DIR):
        path = directory / f"{name}.json"
        if path.exists():
            return path
    raise ValueError(f"No course file named {name}.json")


def _source(course, level, day):
    """The fields the model sees for one module; also the basis of its cache key."""
    checks = day.get("checks") or day.get("acceptance_checks") or []
    def check_line(check):
        if isinstance(check, list):
            return " -> ".join(_text(part) for part in check[:2])
        if isinstance(check, dict):
            return _text(check.get("input_or_condition")) + " -> " + _text(check.get("expected_result"))
        return _text(check)
    check_text = [check_line(check) for check in checks]
    lab = day.get("lab_task") or day.get("lab") or ""
    topic = _text(day.get("topic"))
    source = {
        "course": _text(course.get("name") or course.get("domain")), "level": level or _text(course.get("level")),
        "topic": topic, "subtopics": _strings(day.get("subtopics")), "lab": _text(lab),
        "deliverable": _text(day.get("deliverable")), "checks": [c for c in check_text if c.strip(" ->")],
        "objectives": _strings(day.get("objectives") or day.get("learning_objectives")),
        "tools": _strings(day.get("tools") or course.get("tools")),
        "minutes": int(day.get("minutes") or MODULE_MINUTES), "capstone": "capstone" in topic.lower(),
    }
    source["key"] = hashlib.sha256(json.dumps([REVISION, source], sort_keys=True).encode()).hexdigest()[:20]
    return source


def _has_design(day):
    outline = day.get("outline") if isinstance(day.get("outline"), dict) else {}
    return isinstance(day.get("design"), dict) or isinstance(outline.get("design"), dict)


def inventory(courses=DEFAULT_COURSES):
    """Modules without a design, deduplicated by content, each with every place it is used."""
    pending = {}
    for name in courses:
        path = _course_path(name)
        course = json.loads(path.read_text(encoding="utf-8-sig"))
        tracks = ([(level, course["levels"][level]["days"]) for level in LEVELS if level in course.get("levels", {})]
                  if "levels" in course else [(None, course.get("days") or [])])
        for level, days in tracks:
            for day in days:
                if _has_design(day) or not _text(day.get("topic")):
                    continue
                source = _source(course, level, day)
                entry = pending.setdefault(source["key"], {"source": source, "course": name, "places": []})
                entry["places"].append({"path": str(path), "level": level, "topic": day["topic"]})
    return pending


def example_design():
    authored = json.loads((ROOT / "authored_outlines.json").read_text(encoding="utf-8"))
    for course in authored["courses"]:
        for day in course["days"]:
            if day.get("design"):
                design = deepcopy(day["design"])
                design["lab_rubric"] = [dict(zip(("criterion", "exceeds", "meets", "partly", "not_met"), row))
                                        for row in design.get("lab_rubric") or []]
                return {"input": {"topic": day["topic"], "lab": day["lab"]["title"], "minutes": MODULE_MINUTES,
                                  "capstone": False}, "design": design}
    return None


def _scaled(values, total):
    base = sum(values)
    if base <= 0:
        return values
    scaled = [max(5, int(5 * round(value * total / base / 5))) for value in values]
    scaled[-1] += total - sum(scaled)
    return scaled


def normalise(design, minutes):
    """Coerce a model draft into the stored design shape (types, list lengths, minutes adding up)."""
    if not isinstance(design, dict):
        return {}
    topics = []
    for item in design.get("topics") or []:
        if not isinstance(item, dict):
            continue
        try:
            item_minutes = int(round(float(item.get("minutes") or 0)))
        except (TypeError, ValueError):
            item_minutes = 0
        topics.append({"topic": _text(item.get("topic")), "minutes": item_minutes,
                       "mode": _text(item.get("mode")).lower(), "subtopics": _strings(item.get("subtopics"))[:8],
                       "failure_scenario": _text(item.get("failure_scenario")),
                       "best_practice": _text(item.get("best_practice"))})
    if topics and all(t["minutes"] > 0 for t in topics) and sum(t["minutes"] for t in topics) != minutes:
        for topic, value in zip(topics, _scaled([t["minutes"] for t in topics], minutes)):
            topic["minutes"] = value
    rubric = []
    for row in design.get("lab_rubric") or []:
        if isinstance(row, dict):
            row = [row.get(key) for key in ("criterion", "exceeds", "meets", "partly", "not_met")]
        if isinstance(row, list):
            rubric.append([_text(cell) for cell in row[:5]])
    seeded = design.get("seeded_failure") if isinstance(design.get("seeded_failure"), dict) else {}
    return {
        "outcomes": [{"outcome": _text(o.get("outcome")), "assessed_by": _text(o.get("assessed_by"))}
                     for o in design.get("outcomes") or [] if isinstance(o, dict)][:5],
        "topics": topics,
        "seeded_failure": {key: _text(seeded.get(key)) for key in ("symptom", "cause", "fix")},
        "quiz": _strings(design.get("quiz"))[:8],
        "lab_rubric": rubric[:4],
        "lab_environment": [{key: _text(row.get(key)) for key in ("tool", "version", "access", "setup_owner", "cost")}
                            for row in design.get("lab_environment") or [] if isinstance(row, dict)][:6],
    }


def problems(design, source):
    found = design_problems(design, source["minutes"]) if design else ["draft missing from the response"]
    if not design:
        return found
    if not any(t["mode"] == "lab" for t in design["topics"]):
        found.append("design needs a lab topic")
    if len({_norm(t["topic"]) for t in design["topics"]}) != len(design["topics"]):
        found.append("topic names must be unique")
    if any(len(t["subtopics"]) < 2 for t in design["topics"]):
        found.append("every topic needs at least 2 subtopics")
    if any(not q.endswith("?") for q in design["quiz"]):
        found.append("every quiz item must be a question ending with '?'")
    if len(design["lab_rubric"]) != 4:
        found.append("lab rubric needs exactly 4 criteria")
    if not 2 <= len(design["lab_environment"]) <= 6:
        found.append("lab environment needs 2 to 6 rows")
    if any(_PRICE_RE.search(row["cost"]) for row in design["lab_environment"]):
        found.append("lab environment cost must not contain a price")
    return found


def _settings():
    values = dict(os.environ)
    try:
        from dotenv import dotenv_values
        values = {**dotenv_values(ROOT.parents[2] / ".env"), **values}
    except ImportError:
        pass
    provider = (values.get("AI_PROVIDER") or "gemini").strip().lower()
    if provider == "openai":
        return {"provider": "openai", "key": values.get("OPENAI_API_KEY"), "model": values.get("OPENAI_MODEL") or "gpt-5.5"}
    return {"provider": "gemini", "key": values.get("GEMINI_API_KEY"), "model": values.get("GEMINI_MODEL") or "gemini-2.5-flash"}


class FatalProviderError(RuntimeError):
    """The key, model or request is wrong; retrying will not help."""


async def _post(client, settings, system, user):
    """One model call with backoff on rate limits and server errors; returns the JSON text."""
    if settings["provider"] == "openai":
        url, headers = "https://api.openai.com/v1/responses", {"Authorization": "Bearer " + settings["key"]}
        body = {"model": settings["model"], "instructions": system, "input": user, "max_output_tokens": 32000,
                "text": {"format": {"type": "json_object"}}}
    else:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings['model']}:generateContent"
        headers = {"x-goog-api-key": settings["key"]}  # never in the URL, so it cannot reach request logs
        config = {"responseMimeType": "application/json", "temperature": 0.4, "maxOutputTokens": 32000}
        if "flash" in settings["model"]:
            config["thinkingConfig"] = {"thinkingBudget": 0}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": config}
    for attempt in range(6):
        response = await client.post(url, headers=headers, json=body)
        if response.status_code in (429, 500, 502, 503, 504):
            delay = min(120.0, float(response.headers.get("retry-after") or 5 * 2 ** attempt))
            await asyncio.sleep(delay)
            continue
        if response.status_code in (400, 401, 403, 404):
            raise FatalProviderError(f"Provider rejected the request ({response.status_code})")
        if response.is_error:
            raise RuntimeError(f"Provider request failed ({response.status_code})")
        data = response.json()
        if settings["provider"] == "openai":
            return "".join(part.get("text", "") for item in data.get("output", [])
                           for part in item.get("content", []) if part.get("type") == "output_text")
        candidate = (data.get("candidates") or [{}])[0]
        return "".join(part.get("text", "") for part in (candidate.get("content") or {}).get("parts", []))
    raise RuntimeError("Provider still rate-limited after retries")


def _parse(text):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", text or "", re.S)
        data = json.loads(match.group(0)) if match else {}
    return {item.get("key"): item.get("design") for item in (data.get("modules") or []) if isinstance(item, dict)}


async def draft(batch, post, example):
    """Draft one batch; any module that fails the checks is retried once on its own with its problems."""
    sources = [entry["source"] for entry in batch]
    user = json.dumps({"example": example, "modules": sources}, ensure_ascii=False)
    try:
        drafts = _parse(await post(INSTRUCTIONS, user))
    except FatalProviderError:
        raise
    except Exception as exc:  # a malformed or failed batch: retry its modules one by one
        drafts = {}
        first_error = type(exc).__name__
    else:
        first_error = None
    results = {}
    for source in sources:
        design = normalise(drafts.get(source["key"]), source["minutes"])
        issues = problems(design, source) if design else [first_error or "draft missing from the response"]
        if issues:
            retry = json.dumps({"example": example, "modules": [source],
                                "fix_these_problems_in_your_previous_draft": issues}, ensure_ascii=False)
            try:
                design = normalise(_parse(await post(INSTRUCTIONS, retry)).get(source["key"]), source["minutes"])
                issues = problems(design, source) if design else ["draft missing from the response"]
            except FatalProviderError:
                raise
            except Exception as exc:
                issues = [type(exc).__name__]
        results[source["key"]] = (design, issues)
    return results


def _insert_design(text, level, topic, design):
    """Add a "design" block to one level-course day without reformatting the rest of the file."""
    lines = text.split("\n")
    level_start = next(i for i, line in enumerate(lines) if line.strip().startswith(f'"{level}": {{'))
    marker = '"topic": ' + json.dumps(topic, ensure_ascii=False)
    topic_line = next(i for i in range(level_start, len(lines)) if lines[i].strip().startswith(marker))
    opening = max(i for i in range(topic_line) if lines[i].strip() == "{")
    indent = lines[opening][: len(lines[opening]) - len(lines[opening].lstrip())]
    closing = next(i for i in range(topic_line, len(lines)) if lines[i] in (indent + "}", indent + "},"))
    lines[closing - 1] += ","
    lines.insert(closing, indent + "  " + '"design": ' + json.dumps(design, ensure_ascii=False))
    return "\n".join(lines)


def save(results, pending, model):
    """Write accepted designs into their course files; returns the number of days updated."""
    by_path = {}
    for key, (design, issues) in results.items():
        if issues:
            continue
        stored = {**design, "origin": ORIGIN, "revision": REVISION, "model": model, "source_key": key}
        for place in pending[key]["places"]:
            by_path.setdefault(place["path"], []).append((place, stored))
    updated = 0
    for path_text, items in by_path.items():
        path = Path(path_text)
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw)
        if "levels" in document:
            text = raw
            for place, design in items:
                text = _insert_design(text, place["level"], place["topic"], design)
                day = next(d for d in document["levels"][place["level"]]["days"] if d["topic"] == place["topic"])
                day["design"] = design
            if json.loads(text) != document:
                raise ValueError(f"{path.name}: inserted designs do not match the intended data; nothing written")
        else:
            if json.dumps(document, ensure_ascii=False, indent=2) + "\n" != raw:
                raise ValueError(f"{path.name}: unexpected formatting; nothing written")
            for place, design in items:
                day = next(d for d in document["days"] if d.get("topic") == place["topic"] and not _has_design(d))
                day["design"] = design
            text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        updated += len(items)
    return updated


async def run(pending, *, post, model, limit=0, per_course=0, batch_size=3, concurrency=2, log=print):
    """Draft pending modules and save each batch as it finishes; returns a summary."""
    chosen, per = [], {}
    for entry in pending.values():
        if per_course and per.get(entry["course"], 0) >= per_course:
            continue
        per[entry["course"]] = per.get(entry["course"], 0) + 1
        chosen.append(entry)
    if limit:
        chosen = chosen[:limit]
    example = example_design()
    batches = [chosen[i:i + batch_size] for i in range(0, len(chosen), batch_size)]
    gate, lock = asyncio.Semaphore(max(1, concurrency)), asyncio.Lock()
    summary = {"modules": len(chosen), "accepted": 0, "rejected": [], "days_updated": 0, "model": model}

    async def one(batch):
        async with gate:
            results = await draft(batch, post, example)
        async with lock:
            summary["days_updated"] += save(results, pending, model)
            for key, (_, issues) in results.items():
                if issues:
                    source = pending[key]["source"]
                    summary["rejected"].append({"course": pending[key]["course"], "topic": source["topic"],
                                                "issues": issues[:3]})
                else:
                    summary["accepted"] += 1
            log(json.dumps({"accepted": summary["accepted"], "rejected": len(summary["rejected"]),
                            "of": summary["modules"]}), flush=True)

    await asyncio.gather(*(one(batch) for batch in batches))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", action="append", default=[], help="course file name without .json; repeatable")
    parser.add_argument("--run", action="store_true", help="draft with the configured model (paid API)")
    parser.add_argument("--limit", type=int, default=0, help="draft at most this many modules in total")
    parser.add_argument("--per-course", type=int, default=0, help="draft at most this many modules per course")
    parser.add_argument("--batch-size", type=int, default=3, help="modules per model request")
    parser.add_argument("--concurrency", type=int, default=2, help="model requests in flight")
    parser.add_argument("--summary", help="write the run summary as JSON to this path")
    args = parser.parse_args()
    courses = [name for value in args.course for name in value.split(",") if name.strip()] or list(DEFAULT_COURSES)
    pending = inventory([name.strip() for name in courses])
    summary = {"pending_modules": len(pending),
               "by_course": {name: sum(e["course"] == name for e in pending.values()) for name in courses}}
    if args.run:
        settings = _settings()
        if not settings["key"]:
            raise SystemExit("No API key configured for " + settings["provider"])
        import httpx

        async def go():
            async with httpx.AsyncClient(timeout=300) as client:
                return await run(pending, post=lambda system, user: _post(client, settings, system, user),
                                 model=settings["model"], limit=args.limit, per_course=args.per_course,
                                 batch_size=max(1, args.batch_size), concurrency=args.concurrency)
        try:
            summary.update(asyncio.run(go()))
        except FatalProviderError as exc:
            # Do not print provider messages, headers or credentials.
            summary["error"] = str(exc)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if summary.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

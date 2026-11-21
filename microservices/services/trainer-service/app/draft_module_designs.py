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
and reported, and a later run retries it. Designs are saved batch by batch to
``module_designs/<course>.json`` (see app.module_design_store) as model drafts
pending technical review, so an interrupted run keeps its progress. Course
files are never changed. Modules that already have a design are never
redrafted, and placeholder modules (generic "<topic> concepts / configuration"
subtopics) are skipped because a design would hide that they need real content.

    python -m app.draft_module_designs --plan --select rest   # courses other than the default 15
    python -m app.draft_module_designs --plan --select all    # every course the generator can use
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path

from app import module_design_store
from app.apply_authored_outlines import design_problems

ROOT = Path(__file__).parent
LEVEL_DIR = ROOT / "datasets_levels"
COMPACT_DIR = ROOT / "datasets_compact"
REVISION = "module-design-v1"
ORIGIN = "model_draft_pending_technical_review"
LEVELS = ("beginner", "intermediate", "advanced")
MODULE_MINUTES = 420
TBC = "To be confirmed"
DESIGN_DIR = module_design_store.DIR
SPECIAL_FILES = {"categories.json", "combined.json"}
_GENERIC_END = re.compile(r"\b(concepts|configuration|hands-on workflow|troubleshooting|best practices|validation)$", re.I)
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


def all_courses():
    """Every level and compact course file the ToC generator loads, by file name."""
    names = [path.stem for path in sorted(LEVEL_DIR.glob("*.json")) if path.name not in SPECIAL_FILES
             and "levels" in json.loads(path.read_text(encoding="utf-8-sig"))]
    return names + [path.stem for path in sorted(COMPACT_DIR.glob("*.json"))]


def select_courses(selection, explicit=()):
    if explicit:
        return list(explicit)
    if selection == "all":
        return all_courses()
    if selection == "rest":
        return [name for name in all_courses() if name not in DEFAULT_COURSES]
    return list(DEFAULT_COURSES)


def is_placeholder(day):
    """True for generated filler days: most subtopics are '<topic> concepts', '<topic> configuration' and so on."""
    from app.course_outline import is_filler_subtopic, is_template_text
    subtopics = [str(item) for item in day.get("subtopics") or []]
    filler = sum(1 for item in subtopics if is_filler_subtopic(item) or is_template_text(item)
                 or (_GENERIC_END.search(item) and len(item.split()) <= 6))
    return is_template_text(str(day.get("topic") or "")) or (bool(subtopics) and filler >= len(subtopics) / 2)


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


def inventory(courses=DEFAULT_COURSES, skipped=None):
    """Modules without a design, deduplicated by content, each with every place it is used."""
    pending = {}
    for name in courses:
        path = _course_path(name)
        course = json.loads(path.read_text(encoding="utf-8-sig"))
        stored = module_design_store.load(name, DESIGN_DIR)
        tracks = ([(level, course["levels"][level]["days"]) for level in LEVELS if level in course.get("levels", {})]
                  if "levels" in course else [(None, course.get("days") or [])])
        for level, days in tracks:
            for day in days:
                if not _text(day.get("topic")):
                    continue
                store_key = module_design_store.place_key(level, day["topic"])
                outline = day.get("outline") if isinstance(day.get("outline"), dict) else {}
                if isinstance(day.get("design"), dict) or isinstance(outline.get("design"), dict) or store_key in stored:
                    continue
                if is_placeholder(day):
                    if skipped is not None:
                        skipped.append({"course": name, "topic": day["topic"]})
                    continue
                source = _source(course, level, day)
                entry = pending.setdefault(source["key"], {"source": source, "course": name, "places": []})
                entry["places"].append({"course": name, "level": level, "topic": day["topic"], "store_key": store_key})
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
        mode = _text(item.get("mode")).lower()
        mode = "demo" if "demo" in mode else ("lab" if "lab" in mode or "hands" in mode else "discussion")
        topics.append({"topic": _text(item.get("topic")), "minutes": item_minutes,
                       "mode": mode, "subtopics": _strings(item.get("subtopics"))[:8],
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
    environment = []
    for row in design.get("lab_environment") or []:
        if not isinstance(row, dict) or not _text(row.get("tool")):
            continue
        item = {key: _text(row.get(key)) or TBC for key in ("tool", "version", "access", "setup_owner", "cost")}
        if _PRICE_RE.search(item["cost"]):
            item["cost"] = "Priced in the Lab Cost Estimate"  # never pass a model-invented price to a client
        environment.append(item)
    return {
        "outcomes": [{"outcome": _text(o.get("outcome")), "assessed_by": _text(o.get("assessed_by")) or "Lab checks"}
                     for o in design.get("outcomes") or [] if isinstance(o, dict) and _text(o.get("outcome"))][:5],
        "topics": topics,
        "seeded_failure": {key: _text(seeded.get(key)) for key in ("symptom", "cause", "fix")},
        "quiz": [re.sub(r"^(q?\d+[.):]\s*)", "", q, flags=re.I) for q in _strings(design.get("quiz"))][:8],
        "lab_rubric": rubric[:4],
        "lab_environment": environment[:6],
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
    if any(len(q) < 15 for q in design["quiz"]):
        found.append("every quiz item must be a full question")
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


def _provider_message(response, secret):
    try:
        message = str((response.json().get("error") or {}).get("message") or "")
    except ValueError:
        message = ""
    return message.replace(secret or "\0", "[redacted]")[:200]


def _quota_details(response):
    """(daily quota exhausted?, seconds Gemini asks us to wait) from a 429 response."""
    try:
        details = (response.json().get("error") or {}).get("details") or []
    except ValueError:
        details = []
    daily, wait = False, 0.0
    for detail in details:
        for violation in detail.get("violations") or []:
            if "perday" in str(violation.get("quotaId") or "").lower():
                daily = True
        delay = str(detail.get("retryDelay") or "")
        if delay.endswith("s"):
            try:
                wait = max(wait, float(delay[:-1]))
            except ValueError:
                pass
    return daily, wait


def _model_rank(name):
    lower = name.lower()
    version = re.search(r"gemini-(\d+(?:\.\d+)?)", lower)
    family = 0 if "flash" in lower and "lite" not in lower else 1 if "flash" in lower else 2 if "pro" in lower else 3
    return (family, any(tag in lower for tag in ("preview", "exp")), -float(version.group(1)) if version else 0.0, lower)


def _gemini_body(model, system, user):
    config = {"responseMimeType": "application/json", "temperature": 0.4, "maxOutputTokens": 32000}
    if model.startswith("gemini-2.5-flash"):
        config["thinkingConfig"] = {"thinkingBudget": 0}  # supported by 2.5 Flash; keeps drafts fast and cheap
    return {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": config}


async def _probe(client, settings, model):
    """True if this key can generate with the model using the real request shape; the reply text when not."""
    response = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": settings["key"]},
        json=_gemini_body(model, "Reply with JSON only.", 'Return {"ok": true}'))
    if response.status_code in (401, 403):
        raise FatalProviderError(f"Gemini rejected the API key ({response.status_code}): "
                                 + _provider_message(response, settings["key"]))
    if response.status_code == 429 and _quota_details(response)[0]:
        raise FatalProviderError("Daily Gemini quota reached: " + _provider_message(response, settings["key"]))
    return True if not response.is_error else _provider_message(response, settings["key"])


async def resolve_model(client, settings):
    """The first model that actually answers: configured, then any suggested by Gemini, then the best Flash models."""
    if settings["provider"] != "gemini":
        return settings["model"]
    response = await client.get("https://generativelanguage.googleapis.com/v1beta/models",
                                headers={"x-goog-api-key": settings["key"]}, params={"pageSize": 200})
    if response.is_error:
        raise FatalProviderError(f"Could not list Gemini models ({response.status_code}): "
                                 + _provider_message(response, settings["key"]))
    names = [str(m.get("name", "")).removeprefix("models/") for m in response.json().get("models") or []
             if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    names = [n for n in names if n.startswith("gemini") and not any(
        tag in n.lower() for tag in ("image", "tts", "embedding", "live", "audio", "vision", "robotics", "computer-use"))]
    queue, tried, notes = [settings["model"]] + sorted(names, key=_model_rank), [], []
    while queue and len(tried) < 8:
        model = queue.pop(0)
        if model in tried:
            continue
        tried.append(model)
        result = await _probe(client, settings, model)
        if result is True:
            return model
        notes.append(f"{model}: {result[:80]}")
        suggested = re.findall(r"models/([A-Za-z0-9.\-]+)", result)
        queue[:0] = [name for name in suggested if name not in tried and name != model]
    raise FatalProviderError("No usable Gemini model for this key. " + " | ".join(notes)[:300])


async def _post(client, settings, system, user):
    """One model call with backoff on rate limits and server errors; returns the JSON text."""
    if settings["provider"] == "openai":
        url, headers = "https://api.openai.com/v1/responses", {"Authorization": "Bearer " + settings["key"]}
        body = {"model": settings["model"], "instructions": system, "input": user, "max_output_tokens": 32000,
                "text": {"format": {"type": "json_object"}}}
    else:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings['model']}:generateContent"
        headers = {"x-goog-api-key": settings["key"]}  # never in the URL, so it cannot reach request logs
        body = _gemini_body(settings["model"], system, user)
    for attempt in range(6):
        response = await client.post(url, headers=headers, json=body)
        if response.status_code == 429:
            daily, retry_seconds = _quota_details(response)
            if daily:
                # A daily quota does not recover by retrying; stop so the rest of the quota stays
                # available to the live application, and continue on another day or another key.
                raise FatalProviderError("Daily Gemini quota reached: " + _provider_message(response, settings["key"]))
            await asyncio.sleep(min(120.0, retry_seconds or 5 * 2 ** attempt))
            continue
        if response.status_code in (500, 502, 503, 504):
            await asyncio.sleep(min(120.0, float(response.headers.get("retry-after") or 5 * 2 ** attempt)))
            continue
        if response.status_code in (400, 401, 403, 404):
            raise FatalProviderError(f"Provider rejected the request ({response.status_code}): "
                                     + _provider_message(response, settings["key"]))
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


def save(results, pending, model):
    """Write accepted designs to module_designs/<course>.json; returns the number of days updated."""
    by_course = {}
    for key, (design, issues) in results.items():
        if issues:
            continue
        stored = {**design, "origin": ORIGIN, "revision": REVISION, "model": model, "source_key": key}
        for place in pending[key]["places"]:
            by_course.setdefault(place["course"], {})[place["store_key"]] = stored
    for course, designs in by_course.items():
        module_design_store.write(course, designs, DESIGN_DIR)
    return sum(len(designs) for designs in by_course.values())


def migrate_inline(courses):
    """Move designs that earlier runs wrote inside course files into the design store.

    Level files had one '"design": {...}' line added per day; that line and the comma
    added before it are removed, so the course file returns to its original text.
    Returns the number of designs moved.
    """
    moved = 0
    for name in courses:
        path = _course_path(name)
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw)
        tracks = ([(level, document["levels"][level]["days"]) for level in LEVELS if level in document.get("levels", {})]
                  if "levels" in document else [(None, document.get("days") or [])])
        found = {}
        for level, days in tracks:
            for day in days:
                design = day.get("design")
                if isinstance(design, dict) and design.get("origin") == ORIGIN:
                    found[module_design_store.place_key(level, day["topic"])] = design
                    del day["design"]
        if not found:
            continue
        if "levels" in document:
            lines = raw.split("\n")
            keep = []
            for line in lines:
                if line.lstrip().startswith('"design": {') and '"origin": "' + ORIGIN + '"' in line:
                    keep[-1] = keep[-1][:-1] if keep and keep[-1].endswith(",") else keep[-1]
                    continue
                keep.append(line)
            text = "\n".join(keep)
            if json.loads(text) != document:
                raise ValueError(f"{path.name}: removing inline designs changed other data; nothing written")
        else:
            text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        module_design_store.write(name, found, DESIGN_DIR)
        path.write_text(text, encoding="utf-8")
        moved += len(found)
    return moved


async def run(pending, *, post, model, limit=0, per_course=0, batch_size=3, concurrency=2, max_minutes=0, log=print):
    """Draft pending modules and save each batch as it finishes; returns a summary.

    With ``max_minutes`` no new batch starts after that time, so a CI job can end
    normally and keep its work before the job time limit; a later run continues.
    """
    import time
    started = time.monotonic()
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
            if summary.get("error"):
                return  # a fatal provider error stops the rest of the run; saved work is kept
            if max_minutes and time.monotonic() - started > max_minutes * 60:
                summary["stopped_at_time_limit"] = True
                return
            try:
                results = await draft(batch, post, example)
            except FatalProviderError as exc:
                summary["error"] = str(exc)
                return
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
                            "of": summary["modules"],
                            "rejected_now": [{"topic": pending[k]["source"]["topic"], "issues": i[:2]}
                                             for k, (_, i) in results.items() if i]}, ensure_ascii=False), flush=True)

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
    parser.add_argument("--max-minutes", type=int, default=0, help="start no new batch after this many minutes")
    parser.add_argument("--select", choices=("top", "rest", "all"), default="top",
                        help="course set when --course is not given: the 15 most-requested, the rest, or all")
    parser.add_argument("--plan", action="store_true", help="print, as JSON, the courses that still need designs")
    parser.add_argument("--groups", type=int, default=0, help="with --plan, split the courses into this many groups")
    parser.add_argument("--paths", action="store_true", help="print the design file path for each --course")
    parser.add_argument("--migrate-inline", action="store_true",
                        help="move designs written inside course files by earlier runs into module_designs/")
    args = parser.parse_args()
    explicit = [name.strip() for value in args.course for name in value.split(",") if name.strip()]
    courses = select_courses(args.select, explicit)
    if args.migrate_inline:
        print(json.dumps({"designs_moved": migrate_inline(courses)}))
        return
    if args.paths:
        print("\n".join(str(DESIGN_DIR / f"{name}.json") for name in courses))
        return
    if args.plan:
        needed = [name for name in courses if inventory([name])]
        if args.groups:
            groups = [needed[i::args.groups] for i in range(args.groups)]
            print(json.dumps([",".join(group) for group in groups if group]))
        else:
            print(json.dumps(needed))
        return
    skipped = []
    pending = inventory(courses, skipped)
    summary = {"pending_modules": len(pending), "placeholder_modules_skipped": len(skipped),
               "by_course": {name: sum(e["course"] == name for e in pending.values()) for name in courses}}
    if args.run:
        settings = _settings()
        if not settings["key"]:
            raise SystemExit("No API key configured for " + settings["provider"])
        import httpx

        async def go():
            async with httpx.AsyncClient(timeout=300) as client:
                settings["model"] = await resolve_model(client, settings)
                print(json.dumps({"model": settings["model"]}), flush=True)
                return await run(pending, post=lambda system, user: _post(client, settings, system, user),
                                 model=settings["model"], limit=args.limit, per_course=args.per_course,
                                 batch_size=max(1, args.batch_size), concurrency=args.concurrency,
                                 max_minutes=args.max_minutes)
        try:
            summary.update(asyncio.run(go()))
        except FatalProviderError as exc:
            # Provider messages are short and have the key redacted; headers are never printed.
            summary["error"] = str(exc)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if args.summary:
        summary_path = Path(args.summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if summary.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

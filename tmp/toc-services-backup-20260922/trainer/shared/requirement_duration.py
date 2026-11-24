"""Read explicit training duration without confusing dates or lab access with teaching."""
import math
import re


def positive_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def training_duration(requirement):
    extracted = requirement.get("extracted")
    sources = [requirement, extracted if isinstance(extracted, dict) else {}]
    result = {}
    for field in ("duration_days", "duration_hours", "hours_per_day"):
        aliases = (field, "training_hours_per_day") if field == "hours_per_day" else (field,)
        for source in sources:
            value = next((positive_number(source.get(key)) for key in aliases if positive_number(source.get(key))), None)
            if value:
                result[field] = value
                break
    texts = []
    for source in sources:
        texts.extend(str(source.get(key) or "") for key in ("duration_text", "training_duration", "duration"))
        for key in ("body", "raw_text", "description", "client_notes", "notes"):
            for line in str(source.get(key) or "").splitlines():
                match = re.match(r"^\s*(?:[-*?]\s*)?(?:training\s+duration|duration|total\s+training\s+hours|training\s+hours\s+per\s+day)\s*[:=-]\s*(.+)$", line, re.I)
                if match:
                    texts.append(line)
    for text in texts:
        days = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:(?:training|working|business)\s+)?days?\b", text, re.I)
        hours = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", text, re.I)
        daily = re.search(r"(?:per\s+day|/\s*day|daily)", text, re.I)
        if days and positive_number(days.group(1)):
            result.setdefault("duration_days", float(days.group(1)))
        if hours and positive_number(hours.group(1)):
            result.setdefault("hours_per_day" if daily else "duration_hours", float(hours.group(1)))
    if "duration_days" not in result and result.get("duration_hours") and result.get("hours_per_day"):
        result["duration_days"] = result["duration_hours"] / result["hours_per_day"]
    return result

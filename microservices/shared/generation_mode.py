"""Read the one application-wide AI wording switch."""


async def application_ai_enabled(db) -> bool:
    """True only when Dashboard has set generation_mode to ai."""
    collection = None
    getter = getattr(db, "get", None)
    if callable(getter):
        collection = getter("automation_settings")
    if collection is None:
        try:
            collection = db["automation_settings"]
        except Exception:
            return False
    find_one = getattr(collection, "find_one", None)
    if not callable(find_one):
        return False
    try:
        setting = await find_one({"key": "generation_mode"}, {"_id": 0}) or {}
    except Exception:
        return False
    value = setting.get("value") if isinstance(setting, dict) else ""
    return str(value or "").strip().lower() == "ai"

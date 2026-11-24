"""Presentation selection is independent of curriculum selection."""
from email.utils import parseaddr

REFERENCE_LAYOUTS = (
    "execution_plan",
    "technical_plan",
    "skills_matrix",
    "detailed_syllabus",
    "stone_plan",
    "moss_plan",
    "sand_plan",
    "bark_plan",
    "mist_plan",
    "olive_plan",
)


def normalize_client_email(value):
    address = parseaddr(str(value or ""))[1].strip().lower()
    return address if "@" in address else ""


async def select_toc_layout(db, requested="auto", client_email="", toc_id=None):
    if requested in REFERENCE_LAYOUTS or requested == "legacy":
        return requested
    collection = db["toc_generations"]
    if toc_id:
        existing = await collection.find_one({"toc_id": toc_id}, {"toc.excel_layout": 1})
        saved = ((existing or {}).get("toc") or {}).get("excel_layout")
        if saved in REFERENCE_LAYOUTS:
            return saved
    email = normalize_client_email(client_email)
    if email:
        latest = await collection.find_one(
            {"client_email": email, "toc.excel_layout": {"$in": list(REFERENCE_LAYOUTS)}},
            {"toc.excel_layout": 1}, sort=[("created_at", -1)],
        )
        previous = ((latest or {}).get("toc") or {}).get("excel_layout")
        if previous in REFERENCE_LAYOUTS:
            return REFERENCE_LAYOUTS[(REFERENCE_LAYOUTS.index(previous) + 1) % len(REFERENCE_LAYOUTS)]
    return REFERENCE_LAYOUTS[0]

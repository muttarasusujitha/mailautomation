"""Wider backfill: find inbound email_logs containing REQ- or TR- and try to extract both ids even if not adjacent.
Updates documents and prints summary.
"""
from pymongo import MongoClient
from datetime import datetime
import re

MONGO = "mongodb://127.0.0.1:27017/"
DB = "trainer_platform"

client = MongoClient(MONGO)
db = client[DB]

REQ_RE = re.compile(r"REQ-[A-Z0-9-]+", flags=re.IGNORECASE)
TR_RE = re.compile(r"TR-[A-Z0-9-]+", flags=re.IGNORECASE)

query = {
    "$and": [
        {"direction": {"$in": ["inbound", "received"]}},
        {"$or": [{"trainer_id": {"$exists": False}}, {"requirement_id": {"$exists": False}}]},
        {"$or": [
            {"body": {"$regex": "REQ-|TR-", "$options": "i"}},
            {"body_snippet": {"$regex": "REQ-|TR-", "$options": "i"}},
            {"raw_body": {"$regex": "REQ-|TR-", "$options": "i"}},
            {"subject": {"$regex": "REQ-|TR-", "$options": "i"}},
        ]}
    ]
}

candidates = list(db.email_logs.find(query).limit(5000))
print(f"Found {len(candidates)} candidate inbound logs to examine")

updated = 0
skipped = 0
for doc in candidates:
    text_parts = [doc.get(k) or "" for k in ("body", "body_snippet", "raw_body", "subject")]
    text = "\n".join(p for p in text_parts if p)
    if not text:
        skipped += 1
        continue
    reqs = REQ_RE.findall(text)
    trs = TR_RE.findall(text)
    if not reqs and not trs:
        skipped += 1
        continue
    req_id = reqs[0].upper() if reqs else None
    tr_id = trs[0].upper() if trs else None
    update = {}
    if req_id and not doc.get("requirement_id"):
        update["requirement_id"] = req_id
    if tr_id and not doc.get("trainer_id"):
        update["trainer_id"] = tr_id
    if update:
        update["updated_at"] = datetime.utcnow()
        db.email_logs.update_one({"_id": doc["_id"]}, {"$set": update})
        updated += 1
        print(f"Updated {doc.get('email_id')} -> {update}")
    else:
        skipped += 1

print(f"Backfill complete. Documents updated: {updated}, skipped: {skipped}")
client.close()

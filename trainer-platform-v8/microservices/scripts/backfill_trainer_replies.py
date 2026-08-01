"""Backfill script: extract REQ/TR pairs from inbound email_logs and update documents.

Run with:
    python backfill_trainer_replies.py

It connects to mongodb://127.0.0.1:27017 and database `trainer_platform` by default.
"""
from pymongo import MongoClient
from datetime import datetime
import re

MONGO = "mongodb://127.0.0.1:27017/"
DB = "trainer_platform"

client = MongoClient(MONGO)
db = client[DB]

# Regexes (same logic as inbox._extract_trainer_reply_ref)
EXACT_REF = re.compile(r"\bRef\s*:\s*(REQ-[A-Z0-9-]+)\s*/\s*(TR-[A-Z0-9-]+)", flags=re.IGNORECASE)
FALLBACK_PAIR = re.compile(r"(REQ-[A-Z0-9-]+)\s*/\s*(TR-[A-Z0-9-]+)", flags=re.IGNORECASE)

query = {
    "$and": [
        {"direction": {"$in": ["inbound", "received"]}},
        {"$or": [{"trainer_id": {"$exists": False}}, {"requirement_id": {"$exists": False}}]},
        {"$or": [
            {"body": {"$regex": "REQ-[A-Z0-9-]+\\/\\s*TR-[A-Z0-9-]+", "$options": "i"}},
            {"body_snippet": {"$regex": "REQ-|TR-", "$options": "i"}},
            {"raw_body": {"$regex": "REQ-|TR-", "$options": "i"}},
            {"subject": {"$regex": "REQ-|TR-", "$options": "i"}},
        ]}
    ]
}

candidates = list(db.email_logs.find(query).limit(1000))
print(f"Found {len(candidates)} candidate inbound logs to examine")

updated = 0
for doc in candidates:
    text_parts = [doc.get(k) or "" for k in ("body", "body_snippet", "raw_body", "subject")]
    text = "\n".join(p for p in text_parts if p)
    if not text:
        continue
    match = EXACT_REF.search(text)
    if not match:
        match = FALLBACK_PAIR.search(text)
    if not match:
        continue
    req_id = match.group(1).upper()
    tr_id = match.group(2).upper()
    update = {}
    if not doc.get("requirement_id"):
        update["requirement_id"] = req_id
    if not doc.get("trainer_id"):
        update["trainer_id"] = tr_id
    if update:
        update["updated_at"] = datetime.utcnow()
        db.email_logs.update_one({"_id": doc["_id"]}, {"$set": update})
        updated += 1
        print(f"Updated {doc.get('email_id')} -> {req_id} / {tr_id}")

print(f"Backfill complete. Documents updated: {updated}")
client.close()

#!/usr/bin/env python3
"""Repair shortlist `top_trainers` flags from `email_logs`.

Usage:
  python repair_shortlists.py --mongo-url mongodb://host.docker.internal:27017 --db trainersync [--apply]

By default this script runs in dry-run mode and prints intended updates.
Pass `--apply` to perform the updates.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pprint import pprint
from typing import Dict, Any

from pymongo import MongoClient


def find_latest_email(db, requirement_id: str, trainer_id: str, mail_type: str):
    return db.email_logs.find_one(
        {"requirement_id": requirement_id, "trainer_id": trainer_id, "mail_type": mail_type},
        sort=[("created_at", -1)],
    )


def repair_shortlist(db, shortlist: Dict[str, Any], apply: bool = False) -> int:
    req = shortlist.get("requirement_id")
    modified = 0
    top = shortlist.get("top_trainers") or []
    now = datetime.utcnow()
    changed = False
    for t in top:
        tid = t.get("trainer_id")
        if not tid:
            continue
        need_fix = (
            t.get("client_email_sent") is None
            or t.get("trainer_email_sent") is None
            or t.get("interview_scheduled") is None
        )
        if not need_fix:
            continue

        client = find_latest_email(db, req, tid, "client_interview_schedule")
        trainer = find_latest_email(db, req, tid, "mail4")

        if client:
            t["client_email_sent"] = bool(client.get("client_email_sent") or True)
            t["client_mail4_email_id"] = client.get("email_id") or t.get("client_mail4_email_id")
            t["client_mail4_sent_at"] = client.get("created_at") or t.get("client_mail4_sent_at")
            t["interview_scheduled"] = bool(client.get("interview_scheduled") or True)
            t["interview_scheduled_at"] = client.get("created_at") or t.get("interview_scheduled_at")
            t["interview_link"] = client.get("interview_link") or client.get("meet_link") or t.get("interview_link")
            t["meet_link"] = client.get("interview_link") or client.get("meet_link") or t.get("meet_link")

        if trainer:
            t["trainer_email_sent"] = bool(trainer.get("trainer_email_sent") or True)
            t["mail4_email_id"] = trainer.get("email_id") or t.get("mail4_email_id")
            t["mail4_sent_at"] = trainer.get("created_at") or t.get("mail4_sent_at")

        changed = True
        modified += 1

    if changed:
        top_update = {"top_trainers": top, "updated_at": now}
        print(f"Requirement {req}: would update {modified} trainer(s)")
        if apply:
            res = db.shortlists.update_one({"requirement_id": req}, {"$set": top_update})
            print("DB update result:", res.raw_result)
        else:
            pprint(top_update)

    return modified


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mongo-url", default="mongodb://host.docker.internal:27017", help="MongoDB URI")
    p.add_argument("--db", default="trainersync", help="MongoDB database name")
    p.add_argument("--requirement", help="Only repair a single requirement id")
    p.add_argument("--limit", type=int, default=0, help="Limit number of shortlists to scan (0 = all)")
    p.add_argument("--apply", action="store_true", help="Apply updates (default: dry-run)")
    args = p.parse_args()

    client = MongoClient(args.mongo_url)
    db = client[args.db]

    query = {}
    # find shortlists with at least one top_trainer missing flags
    query["top_trainers"] = {
        "$elemMatch": {
            "$or": [
                {"client_email_sent": {"$in": [None]}},
                {"trainer_email_sent": {"$in": [None]}},
                {"interview_scheduled": {"$in": [None]}},
            ]
        }
    }
    if args.requirement:
        query = {"requirement_id": args.requirement}

    cursor = db.shortlists.find(query, {"top_trainers": 1, "requirement_id": 1}).sort("updated_at", -1)
    if args.limit and args.limit > 0:
        cursor = cursor.limit(args.limit)

    total = 0
    total_modified = 0
    for s in cursor:
        total += 1
        modified = repair_shortlist(db, s, apply=args.apply)
        total_modified += modified

    print(f"Scanned {total} shortlist(s), modified {total_modified} trainer entries")


if __name__ == "__main__":
    main()

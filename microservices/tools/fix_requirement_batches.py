#!/usr/bin/env python3
"""Fix requirement batch classification for known records.

Usage:
  python fix_requirement_batches.py --mongo-url mongodb://127.0.0.1:27017 --db trainersync
  python fix_requirement_batches.py --apply

By default this runs as a dry run.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any, Dict

from pymongo import MongoClient


TARGETS: Dict[str, Dict[str, str]] = {
    "REQ-0647D530": {
        "batch_flow": "proposal",
        "batch_type": "proposal",
        "requirement_type": "proposal_batch",
        "pipeline_target": "shortlist",
        "pipeline_page": "shortlist",
    },
    "REQ-810D6E3B": {
        "batch_flow": "confirmed",
        "batch_type": "confirmed",
        "requirement_type": "confirmed_batch",
        "pipeline_target": "shortlist1",
        "pipeline_page": "shortlist1",
    },
}


def _build_update(target: Dict[str, str], existing: Dict[str, Any]) -> Dict[str, Any]:
    update = dict(target)
    update["updated_at"] = datetime.utcnow()
    if existing.get("client_email"):
        update["client_email"] = existing["client_email"]
    if existing.get("client_name"):
        update["client_name"] = existing["client_name"]
    return update


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo-url", default="mongodb://127.0.0.1:27017", help="MongoDB URI")
    parser.add_argument("--db", default="trainersync", help="MongoDB database name")
    parser.add_argument("--requirement", help="Only fix one requirement id")
    parser.add_argument("--apply", action="store_true", help="Apply updates instead of printing them")
    args = parser.parse_args()

    client = MongoClient(args.mongo_url)
    db = client[args.db]

    targets = {args.requirement: TARGETS[args.requirement]} if args.requirement else TARGETS
    for requirement_id, target in targets.items():
        requirement = db.requirements.find_one({"requirement_id": requirement_id}, {"_id": 0})
        shortlist = db.shortlists.find_one({"requirement_id": requirement_id}, {"_id": 0})
        if not requirement and not shortlist:
            print(f"{requirement_id}: not found")
            continue

        update = _build_update(target, requirement or shortlist or {})
        print(f"{requirement_id}: {update}")
        if args.apply:
            if requirement:
                db.requirements.update_one({"requirement_id": requirement_id}, {"$set": update})
            if shortlist:
                db.shortlists.update_one({"requirement_id": requirement_id}, {"$set": update})

    client.close()


if __name__ == "__main__":
    main()

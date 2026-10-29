"""python -m app.index_curriculum [--embed] [--output prepared-curriculum.json]

Preparation is offline by default. --embed explicitly builds the persistent
semantic index using the configured provider; it incurs embedding API usage.
"""
import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.curriculum_reasoning import builtin_records, embed_records, load_records


async def run(args):
    records = builtin_records()
    if args.embed:
        from motor.motor_asyncio import AsyncIOMotorClient
        from openai import AsyncOpenAI
        settings = get_settings()
        if not settings.OPENAI_API_KEY.strip():
            raise SystemExit("OPENAI_API_KEY is required for --embed")
        mongo = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=10000)
        try:
            db = mongo[settings.MONGODB_DB_NAME]
            records = await load_records(db)
            async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=1) as client:
                await embed_records(client, settings.TOC_EMBEDDING_MODEL, records, db)
        finally:
            mongo.close()
    if args.output:
        Path(args.output).write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"records": len(records), "domains": len({r['domain'] for r in records}),
                      "indexed": args.embed, "unreviewed": sum(r['review_status'] != 'approved' for r in records)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--output")
    asyncio.run(run(parser.parse_args()))

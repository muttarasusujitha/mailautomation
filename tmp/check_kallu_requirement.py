import asyncio

from app.config import get_settings
from shared.database.service import get_db, init_db, shutdown_db


async def main():
    await init_db(get_settings())
    db = await get_db()
    record = await db["requirements"].find_one(
        {"requirement_id": "REQ-F4F906C1"},
        {"_id": 0, "requirement_id": 1, "title": 1, "technology_needed": 1,
         "pipeline_page": 1, "pipeline_target": 1, "batch_flow": 1,
         "requirement_type": 1, "status": 1, "created_at": 1},
    )
    print(record or {"error": "REQ-F4F906C1 is not in the active requirements database"})
    await shutdown_db()


asyncio.run(main())

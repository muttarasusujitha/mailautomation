import asyncio,json
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
async def main():
    s=get_settings(); c=AsyncIOMotorClient(s.MONGODB_URL)
    try:
        d=await c[s.MONGODB_DB_NAME]['email_logs'].find_one({'email_id':'EML-0771827567'}, {'_id':0,'email_id':1,'status':1,'to_email':1,'recipient':1,'subject':1,'sent_at':1,'error_message':1})
        print(json.dumps(d,default=str))
    finally:
        c.close()
asyncio.run(main())

import asyncio,json
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
async def main():
 s=get_settings(); c=AsyncIOMotorClient(s.MONGODB_URL); db=c[s.MONGODB_DB_NAME]
 query={'$or':[{'interview_link':{'$regex':'vmw-ofjm-fxx|qok-gszg-pia'}},{'meet_link':{'$regex':'vmw-ofjm-fxx|qok-gszg-pia'}}]}
 fields={k:1 for k in ['email_id','interview_at','interview_end_at','interview_link','meet_link','meet_bot_status','meet_bot_error','meet_bot_attempts','meet_bot_joined_at','interview_scheduled','status','meet_bot_claimed_at','meet_bot_updated_at']}; fields['_id']=0
 async for row in db.email_logs.find(query,fields): print(json.dumps(row,default=str))
 c.close()
asyncio.run(main())


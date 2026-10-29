import asyncio,json
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
async def main():
 s=get_settings(); c=AsyncIOMotorClient(s.MONGODB_URL); db=c[s.MONGODB_DB_NAME]
 for name,query in [('requirements',{'requirement_id':'REQ-4C953BAF'}),('shortlists',{'requirement_id':'REQ-4C953BAF'})]:
  d=await db[name].find_one(query,{'_id':0}) or {}
  if name=='requirements':
   print(json.dumps({k:d.get(k) for k in ['requirement_id','fx_rate','cloud_provider','cloud_region','cloud_regions','participant_count','lab_hours_per_day','duration_days','batch_flow','pipeline_target']},default=str))
  else:
   print(json.dumps({'summary':d.get('pipeline_summary'),'trainers':[{k:t.get(k) for k in ['trainer_id','slot_status','pipeline_status','client_slot_error','client_handoff_error_detail','client_handoff_input_version','client_slots_sent','slot_reply_text']} for t in d.get('top_trainers',[])]},default=str))
 c.close()
asyncio.run(main())

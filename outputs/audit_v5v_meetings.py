"""Read-only meeting automation audit; run inside scheduler container."""
import asyncio
import json
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
from app.celery_app import celery_app


async def main():
    settings = get_settings()
    print('CONFIG', json.dumps({'now_utc': str(datetime.utcnow()), 'no_show_minutes': getattr(settings, 'INTERVIEW_NO_SHOW_MINUTES_AFTER', None), 'tasks': {k: {'task': v['task'], 'schedule': str(v['schedule'])} for k, v in celery_app.conf.beat_schedule.items()}}))
    client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
    db = client[settings.MONGODB_DB_NAME]
    try:
        pattern = {'$regex': 'v5|minds', '$options': 'i'}
        reqs = await db.requirements.find({'$or': [{k: pattern} for k in ['client_name', 'company_name', 'client_company', 'company', 'client_email', 'subject']]}, {'_id': 0, 'requirement_id': 1, 'client_name': 1, 'company_name': 1, 'interview_status': 1}).to_list(100)
        print('REQUIREMENTS', json.dumps(reqs, default=str))
        ids = [x['requirement_id'] for x in reqs if x.get('requirement_id')]
        query = {'$or': [{'requirement_id': {'$in': ids}}] + [{k: pattern} for k in ['client_name', 'client_email', 'to_email', 'subject']]}
        fields = ['email_id', 'requirement_id', 'mail_type', 'status', 'to_email', 'trainer_name', 'client_name', 'interview_at', 'interview_date', 'interview_scheduled', 'meet_start_notice_sent', 'meet_start_notice_sent_at', 'meet_start_notice_error', 'meet_start_notice_retry_count', 'meet_bot_status', 'meet_bot_error', 'meet_bot_attempts', 'meet_attendance_observed_at', 'meet_participant_view_available', 'trainer_joined', 'client_joined', 'no_show_check_completed', 'no_show_check_result', 'no_show_check_completed_at', 'sent_at', 'error_message', 'subject', 'client_email', 'calendar_event_id']
        projection = dict.fromkeys(fields, 1)
        projection['_id'] = 0
        logs = await db.email_logs.find(query, projection).sort('created_at', -1).limit(60).to_list(60)
        print('V5V_LOGS', json.dumps(logs, default=str))
        print('NOTICE_COUNTS', json.dumps({kind: await db.email_logs.count_documents({'mail_type': kind}) for kind in ['meet_start_notice', 'meet_no_show_notice']}))
        print('RECENT_MEETINGS', json.dumps(await db.email_logs.find({'interview_scheduled': True}, projection).sort('interview_at', -1).limit(8).to_list(8), default=str))
    finally:
        client.close()


asyncio.run(main())

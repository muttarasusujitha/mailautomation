import json
import httpx
from app.config import get_settings
from app.tasks.meet_start_notices import _notice_body
settings = get_settings()
body = 'TEST REMINDER ONLY - this is a delivery check, not a new interview booking.\n\n' + _notice_body(name='Clahan Team', technology='Clahan delivery test', interview_link='https://meet.google.com/jzy-brvd-bbj', interview_date='Test only - no attendance required').replace('starts in 5 minutes', 'reminder is being tested')
payload = {'to':'sujithaofficial784@gmail.com', 'subject':'[TEST] Clahan meeting reminder delivery check', 'body':body, 'mail_type':'meet_start_notice', 'ai_generate':False, 'idempotency_key':'clahan-reminder-delivery-test-20260914-01'}
headers = {'X-Internal-Token':settings.INTERNAL_SERVICE_TOKEN} if settings.INTERNAL_SERVICE_TOKEN else {}
r = httpx.post(settings.EMAIL_SERVICE_URL.rstrip('/') + '/api/v1/email/send', json=payload, headers=headers, timeout=60)
try:
    result = r.json()
except Exception:
    result = {'error':'Non-JSON response'}
print(json.dumps({'http_status':r.status_code, **{k:result.get(k) for k in ('success','email_id','status','error','error_message','detail') if k in result}}, default=str))

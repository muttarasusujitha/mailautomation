import json
import urllib.request
import urllib.error

base = 'http://127.0.0.1:8000/api/v1/toc'

payload = {
    'domain': 'DevOps',
    'duration_days': 3.0,
    'level': 'intermediate',
    'mode': 'Online',
    'notes': 'Sample DevOps TOC generated for email delivery.',
    'trainer_name': 'Sujitha',
    'trainer_email': 'sujithaofficial585@gmail.com',
    'training_dates': '15-17 July 2026',
    'timing': '10:00 AM - 5:00 PM',
}
print('Generating TOC...')
req = urllib.request.Request(base + '/generate', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=120) as resp:
    body = resp.read().decode('utf-8')
print('Generate response:', body)
result = json.loads(body)
toc_id = result.get('toc_id')
if not toc_id:
    raise SystemExit('No toc_id returned')
print('Generated toc_id:', toc_id)

send_payload = {
    'toc_id': toc_id,
    'to_email': 'sujithaofficial585@gmail.com',
    'subject': 'TOC Delivery from BEULIX SOLUTIONS',
    'body': 'Dear Sujitha,\n\nPlease find attached the TOC.\n\nRegards,\nBEULIX SOLUTIONS',
}
print('Sending TOC email...')
req2 = urllib.request.Request(base + '/send-email', data=json.dumps(send_payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req2, timeout=120) as resp2:
    body2 = resp2.read().decode('utf-8')
print('Send response:', body2)

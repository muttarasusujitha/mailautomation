import json
import requests

with open('master_topic_banks.json') as f:
    master = json.load(f)

from build_program import build_days

payload = {
    'toc': {
        'program_title': 'DevOps Mastery Program',
        'domain': 'DevOps',
        'duration_days': 10,
        'mode': 'Online',
        'trainer_name': 'DevOps Trainer',
        'overview': 'Generated DevOps program with morning/afternoon sessions, labs, and Jira practice.',
        'days': build_days(master['domains']['DevOps'], 10, 'DevOps'),
    },
    'to_email': 'sujithamuttarasu@gmail.com',
    'trainer_name': 'DevOps Trainer',
    'subject': 'DevOps Mastery Program - 10-Day TOC',
    'body': 'Dear Trainer,\n\nPlease find attached the 10-day DevOps TOC in the new format.\n\nRegards,\nTrainerSync Team',
}

print('sending request...')
response = requests.post('http://127.0.0.1:8004/api/v1/toc/send-email', json=payload, timeout=120)
print('status:', response.status_code)
print('text:', response.text)

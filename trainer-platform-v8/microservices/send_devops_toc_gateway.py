import json
import subprocess
import sys
from pathlib import Path

import requests

root = Path(__file__).resolve().parent
build_program = root / 'services' / 'trainer-service' / 'build_program.py'
master_file = root / 'services' / 'trainer-service' / 'master_topic_banks.json'

if not build_program.exists() or not master_file.exists():
    raise SystemExit('Required build_program.py or master_topic_banks.json not found')

result = subprocess.check_output([
    sys.executable,
    str(build_program),
    str(master_file),
    'DevOps',
    '10',
], cwd=str(root))

toc = json.loads(result)

payload = {
    'toc': toc,
    'to_email': 'sujithamuttarasu@gmail.com',
    'trainer_name': 'DevOps Trainer',
    'subject': 'DevOps Mastery Program - 10-Day TOC',
    'body': (
        'Dear Trainer,\n\n'
        'Please find attached the 10-day DevOps TOC in the new format.\n\n'
        'Regards,\n'
        'TrainerSync Team'
    ),
}

url = 'http://127.0.0.1:8000/api/v1/toc/send-email'
print('Sending to', url)
response = requests.post(url, json=payload, timeout=120)
print('Status:', response.status_code)
print('Response:', response.text)
if response.status_code >= 400:
    raise SystemExit('Failed sending TOC email')

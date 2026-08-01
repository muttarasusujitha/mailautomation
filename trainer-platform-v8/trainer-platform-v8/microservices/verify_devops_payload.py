import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
script = root / 'services' / 'trainer-service' / 'build_program.py'
master = root / 'services' / 'trainer-service' / 'master_topic_banks.json'
result = subprocess.check_output([sys.executable, str(script), str(master), 'DevOps', '10'])
toc = json.loads(result)
print('title:', toc.get('title'))
print('subtitle:', toc.get('subtitle'))
print('domain:', toc.get('domain'))
print('duration_days:', toc.get('duration_days'))
print('overview:', toc.get('overview'))
print('day topics:')
for day in toc.get('days', []):
    print(' ', day.get('day'), ':', day.get('topic'))
print('first day morning session:', toc['days'][0].get('morning_session'))
print('first day afternoon session:', toc['days'][0].get('afternoon_session'))

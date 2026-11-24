import json
from pathlib import Path

path = Path('tmp/sonar-issues.json')
raw = path.read_bytes()
# detect UTF-16 LE BOM
if raw.startswith(b'\xff\xfe'):
    text = raw.decode('utf-16')
else:
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('utf-16')

data = json.loads(text)
print('TOTAL', data.get('total'))
issues = data.get('issues', [])
for i, issue in enumerate(issues[:50], start=1):
    print(f"{i}. {issue.get('rule')} {issue.get('severity')} {issue.get('component')} line={issue.get('line')} status={issue.get('status')}")
    print('   message:', issue.get('message'))
    print('   key:', issue.get('key'))
    print()
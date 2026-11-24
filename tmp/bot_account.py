import json
from pathlib import Path
p=Path('/data/chrome-profile/Default/Preferences')
if p.exists():
 data=json.loads(p.read_text())
 print(json.dumps([{'email':a.get('email')} for a in data.get('account_info',[]) ]))
else: print('No saved Chrome preferences')

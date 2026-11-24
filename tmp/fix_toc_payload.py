import json
from pathlib import Path
p = Path('tmp/jira_toc_import.json')
out = Path('tmp/jira_toc_import_fixed.json')
if not p.exists():
    print('source not found:', p)
    raise SystemExit(1)
data = json.loads(p.read_text(encoding='utf-8'))
items = data.get('items', [])
for item in items:
    toc = item.setdefault('toc', {})
    # Ensure top-level subtopics
    if not toc.get('subtopics') and not toc.get('days'):
        toc['subtopics'] = ['General']
    # Normalize days
    days = toc.get('days')
    if isinstance(days, list):
        for day in days:
            # if subtopics is string, split
            st = day.get('subtopics')
            if isinstance(st, str):
                parts = [s.strip() for s in st.replace(';',',').split(',') if s.strip()]
                day['subtopics'] = parts or ['General']
            elif not st:
                day['subtopics'] = ['General']
    # If toc has no days but has subtopics as string, convert
    if 'subtopics' in toc and isinstance(toc['subtopics'], str):
        toc['subtopics'] = [s.strip() for s in toc['subtopics'].replace(';',',').split(',') if s.strip()] or ['General']

out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
print('fixed written to', out)

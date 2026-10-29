"""Render test fixtures through the production workbook renderer, without delivery."""
import json
import subprocess
from pathlib import Path

from app.toc_reference_excel import render_reference_toc
from shared.toc_layouts import REFERENCE_LAYOUTS

source = json.loads(Path('/tmp/toc-reference-fixture.json').read_text())
days = []
for number in (1, 2):
    modules = []
    for item in source['modules']:
        if item['reference_day'] == number:
            modules.append({**item, 'title': item['topic'],
                            'scenario': '\n'.join(s['situation'] for s in item['scenarios'])})
    days.append({'day': number, 'modules': modules})
toc = {'title': source['name'], 'days': days,
       'requirement_brief': {'audience': source['audience']}, 'mode': 'Online'}
output = Path('/tmp/toc-reference-qa')
output.mkdir(exist_ok=True)
for layout in REFERENCE_LAYOUTS:
    data = render_reference_toc({**toc, 'excel_layout': layout})
    path = output / (layout + '.xlsx')
    path.write_bytes(data)
    result = subprocess.run(['libreoffice', '-env:UserInstallation=file:///tmp/toc-qa-lo', '--headless',
        '--convert-to', 'pdf', '--outdir', str(output), str(path)], capture_output=True, text=True, timeout=60)
    print(json.dumps({'layout': layout, 'bytes': len(data), 'render_exit': result.returncode,
                      'pdf_exists': path.with_suffix('.pdf').exists(), 'output': result.stdout.strip()}), flush=True)

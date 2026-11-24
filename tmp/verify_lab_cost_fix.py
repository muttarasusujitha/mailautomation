"""Smoke-test the local trainer API without emailing or using a paid AI call."""
import io
import json
import urllib.request
import urllib.error
import zipfile

base = 'http://127.0.0.1:8004/api/v1/toc'
payload = {
    'toc': {'domain': 'Linux smoke test', 'days': [
        {'day': 1, 'focus_area': 'Linux', 'lab': 'Linux shell practice on AWS',
         'tools': ['Linux'], 'subtopics': ['Shell commands']}
    ]},
    'lab_generation_mode': 'template',
    'cloud_provider': 'aws', 'cloud_region': 'ap-south-1',
    'participant_count': 2, 'hours_per_day': 3,
    'storage_gb': 0, 'egress_gb': 0, 'build_minutes': 0, 'monitoring_gb': 0,
    'k8s_worker_nodes': 0,
}
request = urllib.request.Request(base + '/generate-lab-cost',
    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(request, timeout=330) as response:
        data = response.read()
        workbook = zipfile.ZipFile(io.BytesIO(data))
        assert 'xl/workbook.xml' in workbook.namelist()
        print(json.dumps({'status': response.status, 'workbook_bytes': len(data),
            'pricing_status': response.headers.get('X-Lab-Cost-Pricing-Status')}))
except urllib.error.HTTPError as error:
    print('HTTP', error.code, error.read().decode()[:1500])
    raise SystemExit(1)

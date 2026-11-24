from shared.live_lab_pricing import _aws_catalog
import json
for service in ('AmazonEKS', 'AmazonS3'):
    for row, url in _aws_catalog(service, 'ap-south-1'):
        if row.get('TermType') == 'OnDemand' and (service == 'AmazonEKS' or (row.get('Unit') == 'GB-Mo' and row.get('Storage Class') == 'General Purpose')):
            print(json.dumps(row), flush=True)

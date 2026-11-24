import json
from urllib.request import urlopen
from urllib.parse import urlencode
queries = ["armSkuName eq 'Standard_B2s'", "armSkuName eq 'Standard_D4s_v5'", "serviceName eq 'Azure Kubernetes Service'", "serviceName eq 'Storage' and unitOfMeasure eq '1 GB/Month'"]
queries = ["productName eq 'Premium SSD Managed Disks' and meterName eq 'P4 LRS Disk'", "productName eq 'Premium Block Blob' and meterName eq 'Premium LRS Data Stored'"]
for query in queries:
    url = 'https://prices.azure.com/api/retail/prices?' + urlencode({'$filter': "armRegionName eq 'centralindia' and priceType eq 'Consumption' and (" + query + ')'})
    with urlopen(url, timeout=45) as response:
        data = json.load(response)
    print(json.dumps({'query': query, 'next': data.get('NextPageLink'), 'items': [{k: r.get(k) for k in ('productName','meterName','meterId','unitOfMeasure','retailPrice','tierMinimumUnits')} for r in data.get('Items', [])]}), flush=True)

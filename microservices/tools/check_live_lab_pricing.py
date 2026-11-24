"""Read-only smoke check against the public Azure pricing endpoint."""
import json
from urllib.parse import urlencode
from urllib.request import urlopen
from shared.live_lab_pricing import _azure

query = {'$filter': "armRegionName eq 'centralindia' and armSkuName eq 'Standard_B2s' and priceType eq 'Consumption'"}
with urlopen('https://prices.azure.com/api/retail/prices?' + urlencode(query), timeout=30) as response:
    data = json.load(response)
item = next(x for x in data['Items'] if x['type'] == 'Consumption'
            and 'Windows' not in x['productName'] and 'Spot' not in x['skuName']
            and 'Low Priority' not in x['skuName'])
rates = _azure({'meter_id': item['meterId']}, 'centralindia')
assert len(rates) == 1
assert rates[0]['unit'] == '1 Hour'
print('Azure live lookup passed:', rates[0])

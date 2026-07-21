import json
import base64
import urllib.request

TOKEN = 'squ_841a76c7d75d3dfe627fbacc8046c9ab10f45b09'
URL = 'http://127.0.0.1:9000/api/issues/search?projectKeys=trainersync&resolved=false&ps=100'

req = urllib.request.Request(
    URL,
    headers={
        'Authorization': 'Basic ' + base64.b64encode((TOKEN + ':').encode()).decode(),
        'Accept': 'application/json',
    },
)
with urllib.request.urlopen(req, timeout=10) as resp:
    text = resp.read().decode()
    data = json.loads(text)
    print(json.dumps(data, indent=2))

"""Configure verified local Azure selections and export a batch workbook; sends no email."""
import asyncio, io, json
import httpx
import zipfile
from xml.etree import ElementTree
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
from app.routes.shortlists import _build_toc
from shared.lab_planning import default_cloud_mapping
from shared.live_lab_pricing import automatic_pricing_selections

async def main():
    s = get_settings()
    mongo = AsyncIOMotorClient(s.MONGODB_URL)
    db = mongo[s.MONGODB_DB_NAME]
    req = await db.requirements.find_one({'requirement_id': 'REQ-4C953BAF'}, {'_id': 0})
    shortlist = await db.shortlists.find_one({'requirement_id': req['requirement_id']}, {'_id': 0})
    trainer = next(t for t in shortlist['top_trainers'] if t['trainer_id'] == 'TR-63F6F0DB')
    toc = await _build_toc({**req, 'cloud_provider': 'azure', 'cloud_region': 'centralindia'}, trainer, db)
    values = dict(cloud_provider='azure', cloud_region='centralindia', participant_count=req['participant_count'],
                  hours_per_day=req['lab_hours_per_day'], fx_rate=req['fx_rate'], egress_gb=0, build_minutes=0, monitoring_gb=0)
    selections = automatic_pricing_selections(toc, values)
    selections['VM Heavy'] = {'meter_id': '2382d92d-4ce9-5330-9bb4-8ec9120e6a64'}
    selections['Kubernetes worker'] = selections['VM Heavy'].copy()
    selections['Kubernetes control plane'] = {'meter_id': '251a08e1-40d6-48e6-8368-4c3e5ee3bbff'}
    selections['Disk'] = {'meter_id': 'ed9e91d2-0f0c-4d55-b3dd-7f69d4708b22'}
    selections['Storage'] = {'meter_id': 'e7835f46-4557-4a90-b05a-9033deda4811'}
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.put('http://localhost:8004/api/v1/toc/lab-cost/pricing-catalog', json={
            'cloud_provider': 'azure', 'cloud_region': 'centralindia', 'selections': selections})
        print('Catalog:', response.status_code, flush=True)
        if response.status_code != 200:
            print(response.text); return
        values['lab_day_mapping'] = default_cloud_mapping(toc, values)
        values['architecture_note'] = 'Proposed learner VMs with shared AKS and 10 GB Premium LRS Blob storage where required by the TOC. No resources provisioned. Egress, managed build, monitoring and Blob request charges excluded; delete lab resources after each mapped period.'
        response = await client.post('http://localhost:8004/api/v1/toc/generate-lab-cost', json={'toc': toc, **values, 'lab_generation_mode': 'manual'})
        print('Workbook:', response.status_code, response.headers.get('X-Lab-Cost-Pricing-Status'), flush=True)
        if response.status_code != 200:
            print(response.text); return
        quote_id = response.headers['X-Lab-Cost-Quote-ID']
        quote = await db.lab_cost_quotes.find_one({'quote_id': quote_id})
        assert quote['pricing_status'] == 'provider_api_verified_public_retail'
        snapshot = await db.lab_cost_rate_snapshots.find_one({'quote_id': quote_id})
        assert snapshot['assumptions']['disk_gb_per_node'] == 32
        assert snapshot['rates']['VM Heavy']['rate'] > snapshot['rates']['VM Light']['rate']
        assert snapshot['rates']['Disk']['provider_unit'] == '1/Month'
        print('Saved quote and disk conversion verified', flush=True)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            workbook = ElementTree.fromstring(archive.read('xl/workbook.xml'))
            sheets = [node.attrib['name'] for node in workbook.findall('.//{*}sheet')]
        assert 'Live Price Check' in sheets
        assert len(values['lab_day_mapping']) == 20
        assert sum(day['vm_qty'] for day in values['lab_day_mapping']) > 0
        with open('/tmp/DevOps-Azure-Central-India-Lab-Cost.xlsx', 'wb') as out:
            out.write(response.content)
        print(json.dumps({'sheets': sheets, 'bytes': len(response.content), 'quote_id': response.headers.get('X-Lab-Cost-Quote-ID')}), flush=True)
    mongo.close()

asyncio.run(main())

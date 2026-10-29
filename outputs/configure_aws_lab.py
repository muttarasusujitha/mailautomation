"""Configure verified local AWS selections and export a batch workbook; sends no email."""
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
    toc = await _build_toc(req, trainer, db)
    values = dict(cloud_provider='aws', cloud_region='ap-south-1', participant_count=req['participant_count'],
                  hours_per_day=req['lab_hours_per_day'], fx_rate=req['fx_rate'], egress_gb=0, build_minutes=0, monitoring_gb=0)
    selections = automatic_pricing_selections(toc, values)
    selections['Kubernetes control plane'] = dict(service='AmazonEKS', sku='RQJ9MJY8F5PSNNWU', rate_code='RQJ9MJY8F5PSNNWU.JRTCKXETXF.6YS6EN2CT7')
    selections['Storage'] = dict(service='AmazonS3', sku='USGUTP2JY23N9GH2', rate_code='USGUTP2JY23N9GH2.JRTCKXETXF.PGHJ3S3EYE', first_tier_only=True)
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.put('http://localhost:8004/api/v1/toc/lab-cost/pricing-catalog', json={
            'cloud_provider': 'aws', 'cloud_region': 'ap-south-1', 'selections': selections})
        print('Catalog:', response.status_code, flush=True)
        if response.status_code != 200:
            print(response.text); return
        values['lab_day_mapping'] = default_cloud_mapping(toc, values)
        values['architecture_note'] = 'Proposed learner VMs with shared EKS and 10 GB S3 where required by the TOC. No resources provisioned. Egress, managed build, monitoring and S3 request charges excluded; delete lab resources after each mapped period.'
        response = await client.post('http://ts-document-service:8006/api/v1/documents/excel/toc/lab-cost', json={'toc': toc, 'assumptions': values})
        print('Workbook:', response.status_code, response.headers.get('X-Lab-Cost-Pricing-Status'), flush=True)
        if response.status_code != 200:
            print(response.text); return
        assert response.headers.get('X-Lab-Cost-Pricing-Status') == 'provider_api_verified_public_retail'
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            workbook = ElementTree.fromstring(archive.read('xl/workbook.xml'))
            sheets = [node.attrib['name'] for node in workbook.findall('.//{*}sheet')]
        assert 'Live Price Check' in sheets
        assert len(values['lab_day_mapping']) == 20
        assert sum(day['vm_qty'] for day in values['lab_day_mapping']) > 0
        with open('/tmp/DevOps-AWS-Mumbai-Lab-Cost.xlsx', 'wb') as out:
            out.write(response.content)
        print(json.dumps({'sheets': sheets, 'bytes': len(response.content), 'quote_id': response.headers.get('X-Lab-Cost-Quote-ID')}), flush=True)
    mongo.close()

asyncio.run(main())

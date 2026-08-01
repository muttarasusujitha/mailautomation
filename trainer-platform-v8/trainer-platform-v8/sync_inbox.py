import httpx
import asyncio
import json

async def sync_inbox():
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post('https://localhost:8000/api/gmail/sync-now')
            print('Status:', response.status_code)
            result = response.json()
            print('\n✅ INBOX SYNC RESULTS:')
            print(f'  Provider: {result.get("provider")}')
            print(f'  Processed: {result.get("processed_count")}')
            print(f'  Auto-sent: {result.get("auto_sent_existing_count")}')
            print(f'  Message: {result.get("message")}')
            if result.get('errors'):
                print(f'  Errors: {result.get("errors")}')
            
            print('\n📧 Full Response:')
            print(json.dumps(result, indent=2, default=str))
        except Exception as e:
            print(f'❌ Error: {e}')

asyncio.run(sync_inbox())

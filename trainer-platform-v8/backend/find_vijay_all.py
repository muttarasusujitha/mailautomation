import asyncio
from database import connect_db, get_db

async def find_all_vijay():
    await connect_db()
    db = get_db()
    
    # Search for all Vijay records
    trainers = await db['trainers'].find({
        '$or': [
            {'display_name': {'$regex': 'Vijay', '$options': 'i'}},
            {'name': {'$regex': 'Vijay', '$options': 'i'}}
        ]
    }).to_list(None)
    
    if trainers:
        print(f'Found {len(trainers)} Vijay record(s):\n')
        for i, trainer in enumerate(trainers, 1):
            print(f'--- Record {i} ---')
            print(f'Name: {trainer.get("display_name") or trainer.get("name")}')
            print(f'Email: {trainer.get("email") or "(empty)"}')
            print(f'Phone: {trainer.get("phone") or "(empty)"}')
            print(f'Location: {trainer.get("location") or "(empty)"}')
            print(f'Experience: {trainer.get("experience_years")} years')
            print(f'Resume start: {trainer.get("resume", "")[:80]}...\n')
    else:
        print('No Vijay trainers found')

asyncio.run(find_all_vijay())

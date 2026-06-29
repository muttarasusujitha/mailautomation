import asyncio
from database import connect_db, get_db

async def check_trainer():
    await connect_db()
    db = get_db()
    
    # Search for Vijay A trainer
    trainer = await db['trainers'].find_one({
        '$or': [
            {'display_name': {'$regex': 'Vijay', '$options': 'i'}},
            {'name': {'$regex': 'Vijay', '$options': 'i'}}
        ]
    })
    
    if trainer:
        print('=== TRAINER DETAILS ===')
        print(f'Name: {trainer.get("display_name") or trainer.get("name")}')
        print(f'Email: {trainer.get("email")}')
        print(f'Phone: {trainer.get("phone")}')
        print(f'Location: {trainer.get("location")}')
        print(f'Experience: {trainer.get("experience_years")} years')
        print(f'\nResume:')
        resume = trainer.get("resume", "")
        print(resume[:200] if resume else "No resume")
    else:
        print('Trainer not found')

asyncio.run(check_trainer())

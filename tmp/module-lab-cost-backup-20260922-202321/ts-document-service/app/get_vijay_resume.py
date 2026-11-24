import asyncio
from database import connect_db, get_db

async def get_vijay_resume():
    await connect_db()
    db = get_db()
    
    # Get the correct Vijay A trainer
    trainer = await db['trainers'].find_one({'name': 'Vijay A Corporate Trainer Consultant'})
    
    if trainer:
        print('=== VIJAY A - CORPORATE TRAINER & CONSULTANT ===\n')
        print(f'Name: {trainer.get("display_name") or trainer.get("name")}')
        print(f'Email: {trainer.get("email")}')
        print(f'Phone: {trainer.get("phone")}')
        print(f'Location: {trainer.get("location")}')
        print(f'Experience: {trainer.get("experience_years")} years')
        print(f'Skills: {trainer.get("skills")}')
        print(f'\n=== FULL RESUME ===\n')
        resume = trainer.get("resume", "")
        print(resume if resume else "No resume stored")
    else:
        print('Trainer not found')

asyncio.run(get_vijay_resume())

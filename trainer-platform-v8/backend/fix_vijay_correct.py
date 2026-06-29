import asyncio
from database import connect_db, get_db

async def fix_vijay():
    await connect_db()
    db = get_db()
    
    # Revert the wrong update - clear the email we added to Record 1
    result1 = await db['trainers'].update_one(
        {'name': 'Vijay', 'experience_years': 25.0},
        {
            '$set': {
                'email': '',
                'location': ''
            }
        }
    )
    
    # Make sure Record 6 (the CORRECT one) has all proper details
    result6 = await db['trainers'].update_one(
        {'name': 'Vijay A Corporate Trainer Consultant'},
        {
            '$set': {
                'display_name': 'Vijay A',
                'email': 'muralisocial123@gmail.com',
                'location': 'Bengaluru',
                'title': 'Corporate Trainer & Consultant',
                'profile_title': 'Corporate Trainer & Consultant - SailPoint & Oracle Identity Management'
            }
        }
    )
    
    print('✅ Database fixed!')
    print(f'Reverted wrong record: {result1.modified_count}')
    print(f'Updated correct record: {result6.modified_count}')
    
    # Show the correct trainer now
    trainer = await db['trainers'].find_one({'name': 'Vijay A Corporate Trainer Consultant'})
    print('\n=== CORRECT VIJAY A TRAINER ===')
    print(f'Name: {trainer.get("display_name")}')
    print(f'Email: {trainer.get("email")}')
    print(f'Location: {trainer.get("location")}')
    print(f'Experience: {trainer.get("experience_years")} years')
    print(f'Title: {trainer.get("title")}')

asyncio.run(fix_vijay())

import asyncio
from database import connect_db, get_db
from datetime import datetime

async def update_trainer():
    await connect_db()
    db = get_db()
    
    # Update Vijay trainer with correct details
    result = await db['trainers'].update_one(
        {'name': 'Vijay'},
        {
            '$set': {
                'display_name': 'Vijay A',
                'email': 'muralisocial123@gmail.com',
                'location': 'Bengaluru',
                'phone': '+91',  # Add if you have the phone
                'title': 'Corporate Trainer & Consultant',
                'profile_title': 'Corporate Trainer & Consultant - SailPoint & Oracle Identity Management',
                'updated_at': datetime.utcnow()
            }
        }
    )
    
    if result.modified_count > 0:
        print('✅ Trainer updated successfully!')
        print(f'Modified: {result.modified_count} document')
        
        # Verify
        trainer = await db['trainers'].find_one({'name': 'Vijay'})
        print('\n=== UPDATED DETAILS ===')
        print(f'Name: {trainer.get("display_name")}')
        print(f'Email: {trainer.get("email")}')
        print(f'Location: {trainer.get("location")}')
        print(f'Title: {trainer.get("title")}')
    else:
        print('❌ No updates made')

asyncio.run(update_trainer())

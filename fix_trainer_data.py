#!/usr/bin/env python3
"""
Fix incorrect trainer data in MongoDB
Finds trainers with specific email and corrects the name
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime

async def fix_trainer_data():
    # Connect to MongoDB
    mongo_uri = os.getenv("MONGO_URI") or "mongodb://localhost:27017/trainersync"
    client = AsyncIOMotorClient(mongo_uri)
    db = client.trainersync
    
    # Find all trainers with the email muralisocial123@gmail.com
    print("🔍 Searching for trainers with email: muralisocial123@gmail.com")
    trainers = await db["trainers"].find(
        {"email": {"$regex": "^muralisocial123@gmail.com$", "$options": "i"}},
        {"_id": 0}
    ).to_list(100)
    
    print(f"Found {len(trainers)} trainer(s) with this email:\n")
    for i, trainer in enumerate(trainers, 1):
        print(f"{i}. Name: {trainer.get('name')}")
        print(f"   ID: {trainer.get('trainer_id')}")
        print(f"   Email: {trainer.get('email')}")
        print(f"   Title: {trainer.get('role_designation', 'N/A')}")
        print()
    
    # Fix the trainer data
    if trainers:
        print("=" * 50)
        print("FIXING TRAINER DATA")
        print("=" * 50)
        
        # Update to correct name
        result = await db["trainers"].update_one(
            {"email": {"$regex": "^muralisocial123@gmail.com$", "$options": "i"}},
            {
                "$set": {
                    "name": "Murali Mohan",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        print(f"✅ Updated {result.modified_count} trainer record(s)")
        
        # Show updated data
        updated = await db["trainers"].find_one(
            {"email": {"$regex": "^muralisocial123@gmail.com$", "$options": "i"}},
            {"_id": 0}
        )
        
        print(f"\n📊 Updated Trainer Data:")
        print(f"   Name: {updated.get('name')}")
        print(f"   ID: {updated.get('trainer_id')}")
        print(f"   Email: {updated.get('email')}")
        print(f"   Title: {updated.get('role_designation', 'N/A')}")
    
    else:
        print("❌ No trainers found with this email")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(fix_trainer_data())

#!/usr/bin/env python3
import os
from pymongo import MongoClient
from datetime import datetime

MONGODB_URL = os.getenv('MONGODB_URL', 'mongodb://127.0.0.1:27017')
DB_NAME = os.getenv('MONGODB_DB_NAME', 'trainersync')

client = MongoClient(MONGODB_URL)
db = client[DB_NAME]

query = {"processing_status": {"$ne": "completed"}}

print(f"Connecting to {MONGODB_URL}, DB: {DB_NAME}")
count = db['resume_uploads'].count_documents(query)
print(f"Found {count} uploads with processing_status != 'completed'\n")

cursor = db['resume_uploads'].find(query).sort('created_at', -1).limit(200)
for doc in cursor:
    upload_id = doc.get('upload_id')
    filename = doc.get('filename')
    status = doc.get('processing_status')
    trainer_id = doc.get('trainer_id')
    created = doc.get('created_at')
    created_str = created.isoformat() if hasattr(created, 'isoformat') else str(created)
    keys = list(doc.keys())
    has_file = any(k in doc for k in ('file_bytes','original_file','raw_file','file_path'))
    print('---')
    print(f"upload_id: {upload_id}\nfilename: {filename}\nstatus: {status}\ntrainer_id: {trainer_id}\ncreated: {created_str}\nfields: {keys}\nhas_file_payload: {has_file}\n")

print('Done')

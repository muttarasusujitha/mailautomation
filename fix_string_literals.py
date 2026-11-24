#!/usr/bin/env python3
"""Replace duplicate string literals with module constants in api.py"""

import re

file_path = "backend/routes/api.py"

# Read the file
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replacement map - order matters (do longer strings first)
replacements = {
    '"$setOnInsert"': 'MONGO_SET_ON_INSERT',
    '"top_trainers.$.pipeline_status"': 'TRAINER_PIPELINE_STATUS_PATH',
    '"top_trainers.$.status"': 'TRAINER_STATUS_PATH',
    '"top_trainers.trainer_id"': 'TRAINER_ID_PATH',
    '"$regex"': 'MONGO_REGEX',
    '"$options"': 'MONGO_OPTIONS',
    '"$exists"': 'MONGO_EXISTS',
    '"+00:00"': 'ISO_TZ_SUFFIX',
    '"gemini-2.0-flash"': 'GEMINI_MODEL',
    '" .,:;"': 'STRIP_CHARS',
    'r"[^a-z0-9]+"': 'ALPHANUMERIC_PATTERN',
}

# Count replacements
for old, new in replacements.items():
    old_count = content.count(old)
    content = content.replace(old, new)
    print(f"Replaced {old_count} occurrences of {old}")

# Write back
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("\nString literal constants replaced successfully!")

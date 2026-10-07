"""Trusted operator CLI: python -m app.manage_users create-admin EMAIL

Also: activate EMAIL --role recruiter, or disable EMAIL.
Passwords are read from a hidden prompt, never command-line arguments or logs.
"""
import argparse
import asyncio
import getpass
import secrets
import warnings
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import TypeAdapter, EmailStr
from app.config import get_settings
from app.security import ensure_indexes, hash_password


def read_password():
    # getpass otherwise falls back to echoing input on unsupported terminals.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('New password (at least 12 characters): ')
            confirmation = getpass.getpass('Confirm password: ')
    except (getpass.GetPassWarning, EOFError):
        raise SystemExit('A terminal supporting hidden password input is required.') from None
    if not 12 <= len(password) <= 128 or password != confirmation:
        raise SystemExit('Passwords must match and contain 12-128 characters.')
    return password


async def run(args):
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    settings = get_settings()
    mongo = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=10000)
    try:
        db = mongo[settings.MONGODB_DB_NAME]
        await ensure_indexes(db)
        if args.action == 'create-admin':
            if await db.auth_users.find_one({'email_normalized': email}):
                raise SystemExit('Account already exists. Use activate to change its role.')
            password = read_password()
            await db.auth_users.insert_one({'user_id': 'USR-' + secrets.token_hex(12), 'email': email,
                'email_normalized': email, 'name': args.name or email.split('@')[0], 'role': 'admin',
                'status': 'active', 'password_hash': await asyncio.to_thread(hash_password, password),
                'auth_version': 0, 'created_at': datetime.utcnow()})
        else:
            changes = {'status': 'disabled' if args.action == 'disable' else 'active', 'updated_at': datetime.utcnow()}
            if args.action == 'activate':
                changes['role'] = args.role
            result = await db.auth_users.update_one({'email_normalized': email}, {'$set': changes, '$inc': {'auth_version': 1}})
            if not result.matched_count:
                raise SystemExit('Account not found. Register it first.')
        print('Account updated successfully. Existing sessions are invalid after role/status changes.')
    finally:
        mongo.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create-admin', 'activate', 'disable'])
    parser.add_argument('email')
    parser.add_argument('--name')
    parser.add_argument('--role', choices=['admin', 'recruiter'], default='recruiter')
    asyncio.run(run(parser.parse_args()))

"""Opaque server-side sessions and password credentials; no browser-trusted roles."""
import asyncio
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from pymongo import ReturnDocument
from app.config import get_settings

COOKIE = "ts_session"
ITERATIONS = 600_000


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password):
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
    return '$'.join(['pbkdf2_sha256', str(ITERATIONS), base64.b64encode(salt).decode(), base64.b64encode(value).decode()])


def verify_password(password, stored):
    try:
        algorithm, iterations, salt, expected = stored.split('$')
        if algorithm != 'pbkdf2_sha256' or int(iterations) != ITERATIONS:
            return False
        value = hashlib.pbkdf2_hmac('sha256', password.encode(), base64.b64decode(salt, validate=True), int(iterations))
        return hmac.compare_digest(value, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError, AttributeError):
        return False


DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def public_user(user):
    return {key: user.get(key) for key in ('user_id', 'name', 'email', 'role', 'status')}


def require_origin(request):
    origin = request.headers.get('origin')
    settings = get_settings()
    allowed = {s.rstrip('/') for s in settings.allowed_origins_list + [settings.FRONTEND_URL] if '*' not in s}
    if origin and origin.rstrip('/') not in allowed:
        raise HTTPException(403, 'Request origin is not allowed')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Cross-site request is not allowed')


async def rate_limit(db, request, action, email='', maximum=10):
    # Gateway overwrites this header. Direct auth-service is internal-only.
    address = request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')
    now = datetime.utcnow()
    window = int(now.timestamp()) // 900
    for scope, limit in [(address, maximum * 3), (email.lower(), maximum)] if email else [(address, maximum)]:
        key = digest(f'{action}:{scope}:{window}')
        row = await db['auth_rate_limits'].find_one_and_update(
            {'_id': key}, {'$inc': {'count': 1}, '$setOnInsert': {'expires_at': now + timedelta(minutes=30)}},
            upsert=True, return_document=ReturnDocument.AFTER)
        if row['count'] > limit:
            raise HTTPException(429, 'Too many attempts. Try again later.', headers={'Retry-After': '900'})


async def issue_session(db, request, response, user):
    old = request.cookies.get(COOKIE)
    if old:
        await db['auth_sessions'].delete_one({'_id': digest(old)})
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    settings = get_settings()
    seconds = max(1, min(settings.AUTH_SESSION_HOURS, 168)) * 3600
    await db['auth_sessions'].insert_one({
        '_id': digest(token), 'user_id': user['user_id'], 'csrf': csrf,
        'auth_version': user.get('auth_version', 0), 'created_at': datetime.utcnow(),
        'expires_at': datetime.utcnow() + timedelta(seconds=seconds),
    })
    response.set_cookie(COOKIE, token, max_age=seconds, httponly=True, secure=settings.AUTH_COOKIE_SECURE, samesite='lax', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return {'success': True, 'user': public_user(user), 'csrf_token': csrf}


async def authenticate(db, request, *, method=None):
    token = request.cookies.get(COOKIE, '')
    if not token or len(token) > 128:
        raise HTTPException(401, 'Sign in required')
    session = await db['auth_sessions'].find_one({'_id': digest(token), 'expires_at': {'$gt': datetime.utcnow()}})
    if not session:
        raise HTTPException(401, 'Session expired. Sign in again.')
    user = await db['auth_users'].find_one({'user_id': session['user_id'], 'status': 'active'})
    if not user or user.get('auth_version', 0) != session.get('auth_version', 0):
        raise HTTPException(401, 'Session revoked. Sign in again.')
    if (method or request.method).upper() not in {'GET', 'HEAD', 'OPTIONS'}:
        require_origin(request)
        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(403, 'Invalid CSRF token. Refresh and try again.')
    return user, session


async def require_admin(request: Request):
    from shared.database.service import get_db
    user, _ = await authenticate(await get_db(), request)
    if user.get('role') != 'admin':
        raise HTTPException(403, 'Administrator access required')
    return user


async def ensure_indexes(db):
    await db['auth_users'].create_index('email_normalized', unique=True, sparse=True)
    await db['auth_users'].create_index('user_id', unique=True, sparse=True)
    for collection in ('auth_sessions', 'auth_rate_limits', 'auth_oauth_states'):
        await db[collection].create_index('expires_at', expireAfterSeconds=0)

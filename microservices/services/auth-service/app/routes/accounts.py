import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError
from shared.database.service import get_db
from app.config import get_settings
from app.security import (COOKIE, DUMMY_HASH, authenticate, digest, hash_password, issue_session,
                          public_user, rate_limit, require_origin, verify_password)

router = APIRouter()
logger = logging.getLogger(__name__)


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    role: Literal['recruiter', 'trainer', 'employee'] = 'recruiter'


class Forgot(BaseModel):
    email: EmailStr


class Reset(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=12, max_length=128)


@router.post('/register', status_code=201)
async def register(payload: Registration, request: Request, db=Depends(get_db)):
    require_origin(request)
    email = str(payload.email).strip().lower()
    await rate_limit(db, request, 'register', email, maximum=5)
    password_hash = await asyncio.to_thread(hash_password, payload.password)
    try:
        await db['auth_users'].insert_one({
            'user_id': 'USR-' + secrets.token_hex(12), 'email': email, 'email_normalized': email,
            'name': payload.name.strip(), 'password_hash': password_hash, 'requested_role': payload.role,
            # Self-service signup grants the standard recruiter role only.
            # Elevated admin access remains operator-managed.
            'role': 'recruiter', 'status': 'active', 'auth_version': 0, 'created_at': datetime.utcnow(),
        })
    except DuplicateKeyError:
        pass
    return {'success': True, 'message': 'If this is a new account, it is ready to use. If you already have an account, sign in as usual.'}


@router.post('/login')
async def login(payload: Credentials, request: Request, response: Response, db=Depends(get_db)):
    require_origin(request)
    email = str(payload.email).lower()
    await rate_limit(db, request, 'login', email)
    user = await db['auth_users'].find_one({'email_normalized': email})
    valid = await asyncio.to_thread(verify_password, payload.password, (user or {}).get('password_hash') or DUMMY_HASH)
    if not valid or not user:
        raise HTTPException(401, "We couldn't sign you in. Check your email and password, or contact support for help.")
    if user.get('status') == 'pending':
        activation = await db['auth_users'].update_one(
            {'user_id': user['user_id'], 'status': 'pending'},
            {'$set': {'status': 'active', 'updated_at': datetime.utcnow()}},
        )
        if activation.matched_count:
            user['status'] = 'active'
        else:
            user = await db['auth_users'].find_one({'email_normalized': email})
    if not user or user.get('status') != 'active':
        raise HTTPException(401, "We couldn't sign you in. Check your email and password, or contact support for help.")
    return await issue_session(db, request, response, user)


async def _resolve_social_user(db, identity):
    """Find or create a standard account for a verified email identity.

    Existing pending signups are activated on verified social sign-in. Explicitly
    disabled accounts stay disabled, and social sign-in never grants the admin role.
    """
    email = str(identity.get('email') or '').strip().lower()
    if not email:
        return None

    user = await db['auth_users'].find_one({'email_normalized': email})
    if user is None:
        user = {
            'user_id': 'USR-' + secrets.token_hex(12),
            'email': email,
            'email_normalized': email,
            'name': str(identity.get('name') or email.split('@')[0]).strip(),
            'role': 'recruiter',
            'status': 'active',
            'auth_version': 0,
            'created_at': datetime.utcnow(),
        }
        try:
            await db['auth_users'].insert_one(user)
        except DuplicateKeyError:
            # Another sign-in may have created the same verified email concurrently.
            pass
        user = await db['auth_users'].find_one({'email_normalized': email})

    if not user or user.get('status') == 'disabled':
        return None
    if user.get('status') == 'pending':
        activation = await db['auth_users'].update_one(
            {'user_id': user['user_id'], 'status': 'pending'},
            {'$set': {'status': 'active', 'updated_at': datetime.utcnow()}},
        )
        if activation.matched_count:
            user['status'] = 'active'
        else:
            user = await db['auth_users'].find_one({'email_normalized': email})
    return user if user and user.get('status') == 'active' else None


@router.get('/me')
async def me(request: Request, response: Response, db=Depends(get_db)):
    user, session = await authenticate(db, request)
    response.headers['Cache-Control'] = 'no-store'
    return {'success': True, 'user': public_user(user), 'csrf_token': session['csrf']}


@router.post('/logout')
async def logout(request: Request, response: Response, db=Depends(get_db)):
    await authenticate(db, request)
    await db['auth_sessions'].delete_one({'_id': digest(request.cookies[COOKIE])})
    response.delete_cookie(COOKIE, path='/', secure=get_settings().AUTH_COOKIE_SECURE, httponly=True, samesite='lax')
    return {'success': True}


@router.get('/verify')
async def verify_access(request: Request, db=Depends(get_db)):
    # This endpoint receives trusted metadata only from nginx's internal subrequest.
    user, _ = await authenticate(db, request, method=request.headers.get('x-original-method', 'GET'))
    path = urlsplit(request.headers.get('x-original-uri', '')).path
    if path.startswith('/api/') and not path.startswith('/api/v1/'):
        path = '/api/v1/' + path[len('/api/'):]
    path = path.rstrip('/')
    admin_paths = ('/api/v1/admin', '/api/v1/database', '/api/v1/gmail', '/api/v1/teams-direct', '/api/v1/scheduler')
    if user.get('role') not in {'admin', 'recruiter'}:
        raise HTTPException(403, 'This workspace requires staff access')
    if any(path == p or path.startswith(p + '/') for p in admin_paths) and user.get('role') != 'admin':
        raise HTTPException(403, 'Administrator access required')
    if path.startswith('/api/v1/auth/'):
        raise HTTPException(403, 'Invalid authorization subrequest')
    return Response(status_code=204, headers={'Cache-Control': 'no-store'})


@router.post('/forgot-password')
async def forgot_password(payload: Forgot, request: Request, db=Depends(get_db)):
    require_origin(request)
    email = str(payload.email).lower()
    await rate_limit(db, request, 'reset', email, maximum=3)
    user = await db['auth_users'].find_one({'email_normalized': email, 'status': 'active'})
    if user and user.get('password_hash'):
        token = secrets.token_urlsafe(48)
        token_hash = digest(token)
        await db['auth_users'].update_one({'user_id': user['user_id']}, {'$set': {
            'reset_hash': token_hash, 'reset_expires_at': datetime.utcnow() + timedelta(minutes=30),
        }})
        settings = get_settings()
        # Fragment avoids placing credentials in HTTP access logs/referrer URLs.
        link = settings.FRONTEND_URL.rstrip('/') + '/reset-password#token=' + token
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                result = await client.post(settings.EMAIL_SERVICE_URL.rstrip('/') + '/api/v1/email/send', json={
                    'to': email, 'subject': 'Reset your TrainerSync password',
                    'body': 'A password reset was requested for your account. This link expires in 30 minutes:\n\n' + link + '\n\nIf you did not request this, ignore this email.',
                    'mail_type': 'password_reset', 'idempotency_key': 'password-reset:' + token_hash,
                    'ai_generate': False,
                })
                if result.status_code >= 400 or not result.json().get('success'):
                    raise RuntimeError('Reset delivery failed')
        except Exception:
            # Do not disclose account existence, provider details or credentials.
            logger.error('Password reset delivery failed')
            await db['auth_users'].update_one({'user_id': user['user_id'], 'reset_hash': token_hash}, {'$unset': {'reset_hash': '', 'reset_expires_at': ''}})
    return {'success': True, 'message': 'If this active account supports password recovery, you will receive reset instructions.'}


@router.post('/reset-password')
async def reset_password(payload: Reset, request: Request, response: Response, db=Depends(get_db)):
    require_origin(request)
    await rate_limit(db, request, 'reset-redeem', maximum=10)
    password_hash = await asyncio.to_thread(hash_password, payload.password)
    # Password change, one-time-token consumption and session revocation version
    # increment are one atomic update, including simultaneous redemption races.
    user = await db['auth_users'].find_one_and_update({
        'reset_hash': digest(payload.token), 'reset_expires_at': {'$gt': datetime.utcnow()}, 'status': 'active',
    }, {'$set': {'password_hash': password_hash, 'password_changed_at': datetime.utcnow()},
        '$inc': {'auth_version': 1}, '$unset': {'reset_hash': '', 'reset_expires_at': ''}})
    if not user:
        raise HTTPException(400, 'Reset link is invalid or expired')
    await db['auth_sessions'].delete_many({'user_id': user['user_id']})
    response.delete_cookie(COOKIE, path='/')
    return {'success': True, 'message': 'Password changed. Sign in with your new password.'}


class GoogleCredential(BaseModel):
    credential: str = Field(min_length=1, max_length=8192)


@router.post('/google')
async def google_login(payload: GoogleCredential, request: Request, response: Response, db=Depends(get_db)):
    require_origin(request)
    await rate_limit(db, request, 'google', maximum=20)
    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(503, 'Google sign-in is not configured')
    try:
        from google.oauth2.id_token import verify_oauth2_token
        from google.auth.transport.requests import Request as GoogleRequest
        info = await asyncio.to_thread(verify_oauth2_token, payload.credential, GoogleRequest(), settings.GOOGLE_CLIENT_ID)
        if info.get('email_verified') is not True:
            raise ValueError('Unverified email')
    except Exception:
        raise HTTPException(401, 'Google credential could not be verified')
    user = await _resolve_social_user(db, info)
    if not user:
        raise HTTPException(403, 'Sign-in is unavailable for this account. Contact support if you need help.')
    return await issue_session(db, request, response, user)


@router.post('/linkedin/start')
async def linkedin_start(request: Request, response: Response, db=Depends(get_db)):
    require_origin(request)
    settings = get_settings()
    if not settings.LINKEDIN_CLIENT_ID or not settings.LINKEDIN_REDIRECT_URI:
        raise HTTPException(503, 'LinkedIn sign-in is not configured')
    await rate_limit(db, request, 'linkedin', maximum=20)
    state = secrets.token_urlsafe(32)
    await db['auth_oauth_states'].insert_one({'_id': digest(state), 'expires_at': datetime.utcnow() + timedelta(minutes=10)})
    response.set_cookie('ts_oauth_state', state, httponly=True, secure=settings.AUTH_COOKIE_SECURE, samesite='lax', max_age=600, path='/')
    return {'url': 'https://www.linkedin.com/oauth/v2/authorization?' + urlencode({
        'response_type': 'code', 'client_id': settings.LINKEDIN_CLIENT_ID, 'redirect_uri': settings.LINKEDIN_REDIRECT_URI,
        'state': state, 'scope': 'openid profile email',
    })}


class LinkedInCode(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=32, max_length=128)


@router.post('/linkedin/oauth-callback')
async def linkedin_callback(payload: LinkedInCode, request: Request, response: Response, db=Depends(get_db)):
    require_origin(request)
    import hmac
    if not hmac.compare_digest(payload.state, request.cookies.get('ts_oauth_state', '')):
        raise HTTPException(403, 'Invalid OAuth state')
    state = await db['auth_oauth_states'].find_one_and_delete({'_id': digest(payload.state), 'expires_at': {'$gt': datetime.utcnow()}})
    if not state:
        raise HTTPException(403, 'OAuth request expired or was already used')
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await client.post('https://www.linkedin.com/oauth/v2/accessToken', data={
                'grant_type': 'authorization_code', 'code': payload.code, 'redirect_uri': settings.LINKEDIN_REDIRECT_URI,
                'client_id': settings.LINKEDIN_CLIENT_ID, 'client_secret': settings.LINKEDIN_CLIENT_SECRET,
            })
            token.raise_for_status()
            identity = await client.get('https://api.linkedin.com/v2/userinfo', headers={'Authorization': 'Bearer ' + token.json()['access_token']})
            identity.raise_for_status()
            info = identity.json()
            if info.get('email_verified') is not True:
                raise ValueError('Unverified email')
    except Exception:
        raise HTTPException(401, 'LinkedIn identity could not be verified')
    user = await _resolve_social_user(db, info)
    if not user:
        raise HTTPException(403, 'Sign-in is unavailable for this account. Contact support if you need help.')
    response.delete_cookie('ts_oauth_state', path='/')
    return await issue_session(db, request, response, user)

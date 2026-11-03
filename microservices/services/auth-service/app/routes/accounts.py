import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, model_validator
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


class LoginCredentials(Credentials):
    desired_role: Literal['admin', 'trainer', 'client'] = 'admin'


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    role: Literal['trainer', 'client'] = 'trainer'
    domain: str = Field(default='', max_length=120)
    company: str = Field(default='', max_length=160)
    phone: str = Field(default='', max_length=40)

    @model_validator(mode='after')
    def require_client_contact(self):
        if self.role == 'client' and (not self.company.strip() or not self.phone.strip()):
            raise ValueError('Client registration requires a company name and contact phone number')
        return self


class Forgot(BaseModel):
    email: EmailStr


class Reset(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=12, max_length=128)


@router.post('/register', status_code=201)
async def register(payload: Registration, request: Request, db=Depends(get_db), response: Response = None):
    require_origin(request)
    email = str(payload.email).strip().lower()
    await rate_limit(db, request, 'register', email, maximum=5)
    password_hash = await asyncio.to_thread(hash_password, payload.password)
    try:
        user = {
            'user_id': 'USR-' + secrets.token_hex(12), 'email': email, 'email_normalized': email,
            'name': payload.name.strip(), 'password_hash': password_hash, 'requested_role': payload.role,
            # Public registration is limited to trainer and client portals.
            # Administrators are provisioned by an operator, never self-selected.
            'role': payload.role,
            'registration_domain': payload.domain.strip(), 'status': 'active',
            'company': payload.company.strip(),
            'phone': payload.phone.strip(),
            'auth_version': 0, 'created_at': datetime.utcnow(),
        }
        await db['auth_users'].insert_one(user)
    except DuplicateKeyError:
        return {'success': True, 'message': 'If this is a new account, it is ready to use. If you already have an account, sign in as usual.'}
    if user['role'] == 'trainer':
        await _send_trainer_email(user, 'trainer_welcome', 'Welcome to TrainerSync',
                                  f"Hi {user['name']},\n\nThank you for registering as a trainer with TrainerSync. Sign in to complete your trainer profile and upload your resume.\n\nTrainerSync")
        session = await issue_session(db, request, response, user)
        return {**session, 'message': 'Welcome to TrainerSync. Complete your trainer profile to get started.'}
    if user['role'] == 'client':
        session = await issue_session(db, request, response, user)
        return {**session, 'message': 'Your client account is ready. Create a training request to find trainers.'}
    return {'success': True, 'message': 'If this is a new account, it is ready to use. If you already have an account, sign in as usual.'}


async def _send_trainer_email(user, mail_type, subject, body):
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            result = await client.post(settings.EMAIL_SERVICE_URL.rstrip('/') + '/api/v1/email/send', json={
                'to': user['email'], 'subject': subject, 'body': body,
                'mail_type': mail_type,
                'idempotency_key': f"{mail_type}:{user['user_id']}:{datetime.utcnow().strftime('%Y%m%d%H%M') if mail_type == 'trainer_login' else 'welcome'}",
                'ai_generate': False,
            })
            if result.status_code >= 400 or not result.json().get('success'):
                logger.warning('Trainer account email was not accepted (%s)', mail_type)
    except Exception:
        # Sending confirmation mail should not lock a trainer out of their account.
        logger.warning('Trainer account email delivery failed (%s)', mail_type)


@router.post('/login')
async def login(payload: LoginCredentials, request: Request, response: Response, db=Depends(get_db)):
    require_origin(request)
    email = str(payload.email).lower()
    await rate_limit(db, request, 'login', email)
    user = await db['auth_users'].find_one({'email_normalized': email})
    valid = await asyncio.to_thread(verify_password, payload.password, (user or {}).get('password_hash') or DUMMY_HASH)
    if not valid or not user:
        raise HTTPException(401, "We couldn't sign you in. Check your email and password, or contact support for help.")
    if user.get('role') != payload.desired_role or user.get('role') not in {'admin', 'trainer', 'client'}:
        raise HTTPException(403, 'This account does not have access to the selected portal. Choose the correct sign-in page or contact the administrator.')
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
    session = await issue_session(db, request, response, user)
    if user.get('role') == 'trainer':
        await _send_trainer_email(user, 'trainer_login', 'Thank you for signing in to TrainerSync',
                                  f"Hi {user.get('name') or 'Trainer'},\n\nThank you for signing in to TrainerSync. Your trainer profile is ready whenever you are.\n\nTrainerSync")
    return session


async def _resolve_social_user(db, identity, desired_role):
    """Find or create the selected trainer/client account for a verified identity.

    Existing pending signups are activated on verified social sign-in. Explicitly
    disabled accounts stay disabled, and social sign-in never grants admin access.
    """
    email = str(identity.get('email') or '').strip().lower()
    if not email:
        return None

    user = await db['auth_users'].find_one({'email_normalized': email})
    if user is None:
        if desired_role not in {'trainer', 'client'}:
            return None
        user = {
            'user_id': 'USR-' + secrets.token_hex(12),
            'email': email,
            'email_normalized': email,
            'name': str(identity.get('name') or email.split('@')[0]).strip(),
            'role': desired_role,
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
    if user.get('role') != desired_role or user.get('role') not in {'admin', 'trainer', 'client'}:
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


async def _social_login_denial(db, identity, desired_role, provider):
    """Return a useful denial reason after the provider has verified the identity."""
    email = str(identity.get('email') or '').strip().lower()
    user = await db['auth_users'].find_one({'email_normalized': email}) if email else None
    if not user:
        return f'{provider} sign-in could not be linked to an active account. Contact support if you need help.'
    if user.get('status') == 'disabled':
        return 'This account is disabled. Contact support to restore access.'
    role = user.get('role')
    if role != desired_role:
        labels = {'admin': 'Administrator', 'trainer': 'Trainer', 'client': 'Client'}
        current = labels.get(role, 'a legacy or unsupported role')
        requested = labels.get(desired_role, 'selected')
        return f'This email is registered for the {current} portal, so it cannot sign in to the {requested} portal. Contact support to update this account’s access.'
    return 'This account is not active. Contact support if you need help.'


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
    method = request.headers.get('x-original-method', 'GET').upper()
    user, _ = await authenticate(db, request, method=method)
    path = urlsplit(request.headers.get('x-original-uri', '')).path
    if path.startswith('/api/') and not path.startswith('/api/v1/'):
        path = '/api/v1/' + path[len('/api/'):]
    path = path.rstrip('/')
    trainer_portal_paths = {
        ('GET', '/api/v1/trainer-membership/status'),
        ('POST', '/api/v1/trainer-membership/order'),
        ('POST', '/api/v1/trainer-membership/verify'),
        ('GET', '/api/v1/trainers/portal/profile'),
        ('POST', '/api/v1/trainers/portal/profile'),
        ('GET', '/api/v1/trainers/portal/opportunities'),
        ('POST', '/api/v1/trainers/portal/opportunities/{opportunity_id}/interest'),
    }
    if user.get('role') == 'trainer':
        allowed = (method, path) in trainer_portal_paths or (
            method == 'POST' and path.startswith('/api/v1/trainers/portal/opportunities/') and path.endswith('/interest')
        )
        if not allowed:
            raise HTTPException(403, 'Trainer accounts can only access the trainer profile portal')
        return Response(status_code=204, headers={
            'Cache-Control': 'no-store',
            'X-Authenticated-User-ID': str(user.get('user_id') or ''),
        })
    if user.get('role') == 'client':
        client_portal_paths = {
            ('GET', '/api/v1/client-portal/profile'),
            ('PATCH', '/api/v1/client-portal/profile'),
            ('POST', '/api/v1/client-portal/email-verification/send'),
            ('POST', '/api/v1/client-portal/email-verification/verify'),
            ('GET', '/api/v1/client-portal/subscription'),
            ('POST', '/api/v1/client-portal/requests'),
            ('GET', '/api/v1/client-portal/requests'),
            ('POST', '/api/v1/client-portal/parse-request'),
            ('POST', '/api/v1/client-portal/subscription/order'),
            ('POST', '/api/v1/client-portal/subscription/verify'),
        }
        if (method, path) not in client_portal_paths:
            raise HTTPException(403, 'Client accounts can only access the client request portal')
        return Response(status_code=204, headers={
            'Cache-Control': 'no-store',
            'X-Authenticated-User-ID': str(user.get('user_id') or ''),
        })
    if user.get('role') != 'admin':
        raise HTTPException(403, 'This workspace requires staff access')
    if path.startswith('/api/v1/trainers/portal/applications') and user.get('role') != 'admin':
        raise HTTPException(403, 'Staff access required')
    admin_paths = ('/api/v1/admin', '/api/v1/database', '/api/v1/gmail', '/api/v1/teams-direct', '/api/v1/scheduler')
    personal_gmail_actions = {
        ('GET', '/api/v1/gmail/me/auth-status'),
        ('GET', '/api/v1/gmail/me/oauth-url'),
        ('POST', '/api/v1/gmail/me/oauth-callback'),
        ('POST', '/api/v1/gmail/me/disconnect'),
        ('POST', '/api/v1/gmail/me/test-send'),
    }
    is_admin_path = any(path == p or path.startswith(p + '/') for p in admin_paths)
    if is_admin_path and user.get('role') != 'admin' and (method, path) not in personal_gmail_actions:
        raise HTTPException(403, 'Administrator access required')
    if path.startswith('/api/v1/auth/'):
        raise HTTPException(403, 'Invalid authorization subrequest')
    return Response(status_code=204, headers={
        'Cache-Control': 'no-store',
        'X-Authenticated-User-ID': str(user.get('user_id') or ''),
    })


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
    desired_role: Literal['admin', 'trainer', 'client'] = 'admin'


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
    user = await _resolve_social_user(db, info, payload.desired_role)
    if not user:
        raise HTTPException(403, await _social_login_denial(db, info, payload.desired_role, 'Google'))
    session = await issue_session(db, request, response, user)
    if user.get('role') == 'trainer':
        await _send_trainer_email(user, 'trainer_login', 'Thank you for signing in to TrainerSync',
                                  f"Hi {user.get('name') or 'Trainer'},\n\nThank you for signing in to TrainerSync. Your trainer profile is ready whenever you are.\n\nTrainerSync")
    return session


class OAuthStart(BaseModel):
    desired_role: Literal['admin', 'trainer', 'client'] = 'admin'


@router.post('/linkedin/start')
async def linkedin_start(payload: OAuthStart, request: Request, response: Response, db=Depends(get_db)):
    require_origin(request)
    settings = get_settings()
    if not settings.LINKEDIN_CLIENT_ID or not settings.LINKEDIN_REDIRECT_URI:
        raise HTTPException(503, 'LinkedIn sign-in is not configured')
    await rate_limit(db, request, 'linkedin', maximum=20)
    state = secrets.token_urlsafe(32)
    await db['auth_oauth_states'].insert_one({'_id': digest(state), 'desired_role': payload.desired_role,
                                             'expires_at': datetime.utcnow() + timedelta(minutes=10)})
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
    user = await _resolve_social_user(db, info, state.get('desired_role') or 'admin')
    if not user:
        raise HTTPException(403, await _social_login_denial(db, info, state.get('desired_role') or 'admin', 'LinkedIn'))
    response.delete_cookie('ts_oauth_state', path='/')
    session = await issue_session(db, request, response, user)
    if user.get('role') == 'trainer':
        await _send_trainer_email(user, 'trainer_login', 'Thank you for signing in to TrainerSync',
                                  f"Hi {user.get('name') or 'Trainer'},\n\nThank you for signing in to TrainerSync. Your trainer profile is ready whenever you are.\n\nTrainerSync")
    return session

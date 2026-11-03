"""Client membership, free-text request intake and private trainer matching."""
import hashlib
import hmac
import json
import logging
import secrets
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from shared.database.service import get_db
from app.config import get_settings
from app.routes.requirements import _build_shortlist_for_requirement, _normalise_requirement_payload

router = APIRouter()
webhook_router = APIRouter()
logger = logging.getLogger(__name__)
SUBSCRIPTION_AMOUNT_PAISE = 99900
SUBSCRIPTION_CURRENCY = 'INR'
SUBSCRIPTION_DAYS = 365


async def _client(user_id: str, db):
    if not user_id:
        raise HTTPException(401, 'Sign in required')
    user = await db['auth_users'].find_one({'user_id': user_id, 'status': 'active'})
    if not user or user.get('role') != 'client':
        raise HTTPException(403, 'Client account required')
    return user


def _subscription_is_active(user):
    expiry = user.get('client_subscription_expires_at')
    return bool(user.get('client_subscription_status') == 'active' and expiry and expiry > datetime.utcnow())


def _requirement_query(user, req_id):
    return {'requirement_id': req_id, 'client_portal_user_id': user['user_id']}


class ClientRequestText(BaseModel):
    text: str = Field(min_length=20, max_length=12000)


class ClientProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    company: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=5, max_length=40)


class ClientEmailCode(BaseModel):
    code: str = Field(pattern=r'^\d{6}$')


class ClientRequestStage(BaseModel):
    stage: str = Field(max_length=40)
    note: str = Field(default='', max_length=1000)


class ClientRequest(BaseModel):
    request_text: str = Field(min_length=20, max_length=12000)
    domain: str = Field(default='', max_length=120)
    required_skills: list[str] = Field(default_factory=list, max_length=30)
    min_experience_years: int = Field(default=0, ge=0, le=70)
    duration_days: Optional[int] = Field(default=None, ge=1, le=365)
    participant_count: Optional[int] = Field(default=None, ge=1, le=100000)
    timeline_start: str = Field(default='', max_length=40)
    timeline_end: str = Field(default='', max_length=40)
    timing: str = Field(default='', max_length=120)
    delivery_mode: str = Field(default='', max_length=40)
    location: str = Field(default='', max_length=120)
    commercial_amount: Optional[float] = Field(default=None, ge=0, le=1000000000)
    lab_hours_per_day: Optional[float] = Field(default=None, ge=0, le=24)
    training_approach: str = Field(default='', max_length=2000)
    business_context: str = Field(default='', max_length=1200)
    requested_deliverables: list[str] = Field(default_factory=list, max_length=20)


class PaymentVerification(BaseModel):
    razorpay_order_id: str = Field(min_length=5, max_length=64)
    razorpay_payment_id: str = Field(min_length=5, max_length=64)
    razorpay_signature: str = Field(min_length=64, max_length=128)


def _amount_from_text(text):
    match = re.search(r'(?:₹|INR\s*|Rs\.?\s*)([\d,]+(?:\.\d{1,2})?)', text, re.I)
    if not match:
        return None
    try:
        return float(match.group(1).replace(',', ''))
    except ValueError:
        return None


def _date_from_text(text):
    for pattern in (
        r'\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b',
        r'\b([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b',
        r'\b(\d{4}-\d{2}-\d{2})\b',
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1).replace(',', '')
        for fmt in ('%d %B %Y', '%d %b %Y', '%B %d %Y', '%b %d %Y', '%Y-%m-%d'):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
    return ''


def parse_client_request_text(text):
    normalized = re.sub(r'\r', '', text).strip()
    domain_match = re.search(r'^\s*domain\s*:\s*(.+?)\s*$', normalized, re.I | re.M)
    domain = domain_match.group(1).strip(' .') if domain_match else ''
    if not domain:
        for candidate in ('DevOps', 'AWS', 'Azure', 'Python', 'Java', 'Data Science', 'Data Engineering', 'Cybersecurity', 'Kubernetes', 'Cloud'):
            if re.search(rf'\b{re.escape(candidate)}\b', normalized, re.I):
                domain = candidate
                break
    duration_match = re.search(r'\b(\d{1,3})\s*[- ]?days?\b', normalized, re.I)
    duration = int(duration_match.group(1)) if duration_match else None
    start = _date_from_text(normalized)
    mode_match = re.search(r'\b(offline|on[- ]?site|online|hybrid|virtual|remote)\b', normalized, re.I)
    mode_value = mode_match.group(1).lower() if mode_match else ''
    mode = 'On-site' if mode_value in {'offline', 'on-site', 'onsite'} else 'Online' if mode_value in {'online', 'virtual', 'remote'} else 'Hybrid' if mode_value else ''
    lab_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:of\s+hands[- ]on\s+lab\s*)?(?:per\s+day|a\s+day|daily)', normalized, re.I)
    if not lab_match:
        lab_match = re.search(r'(?:lab|hands[- ]on)[^\n.]{0,80}?(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)', normalized, re.I)
    lab_hours = float(lab_match.group(1)) if lab_match else None
    skills_match = re.search(r'^\s*(?:skills?|technologies)\s*:\s*(.+?)\s*$', normalized, re.I | re.M)
    skills = [item.strip() for item in re.split(r'[,;]', skills_match.group(1)) if item.strip()] if skills_match else ([domain] if domain else [])
    deliverables = []
    for term, label in ((r'\b(?:trainer\s+profile|updated\s+cv|resume)\b', 'Trainer profile / updated CV'),
                        (r'\b(?:toc|table\s+of\s+contents?)\b', 'Detailed day-wise ToC'),
                        (r'\blab\s+cost\b', 'Lab cost')):
        if re.search(term, normalized, re.I):
            deliverables.append(label)
    training_match = re.search(r'^\s*training\s*:\s*(.+?)\s*$', normalized, re.I | re.M)
    training_approach = training_match.group(1).strip() if training_match else ''
    participants_match = re.search(r'\b(\d{1,5})\s*(?:participants?|learners?|attendees?)\b', normalized, re.I)
    return {
        'domain': domain,
        'required_skills': skills,
        'duration_days': duration,
        'timeline_start': start,
        'delivery_mode': mode,
        'commercial_amount': _amount_from_text(normalized),
        'lab_hours_per_day': lab_hours,
        'participant_count': int(participants_match.group(1)) if participants_match else None,
        'training_approach': training_approach,
        'requested_deliverables': deliverables,
        'request_text': normalized,
    }


@router.get('/profile')
async def client_profile(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    return {'profile': {
        'name': user.get('name', ''), 'email': user.get('email', ''),
        'company': user.get('company', ''), 'phone': user.get('phone', ''),
        'email_verified': user.get('client_email_verified') is True,
    }}


@router.patch('/profile')
async def update_client_profile(payload: ClientProfileUpdate,
                                x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    values = {'name': payload.name.strip(), 'company': payload.company.strip(), 'phone': payload.phone.strip()}
    if any(not value for value in values.values()):
        raise HTTPException(400, 'Name, company, and contact phone are required')
    await db['auth_users'].update_one({'user_id': user['user_id']}, {'$set': {**values, 'updated_at': datetime.utcnow()}})
    await db['requirements'].update_many({'client_portal_user_id': user['user_id']}, {'$set': {
        'client_name': values['name'], 'client_company': values['company'], 'client_phone': values['phone'],
    }})
    return {'success': True, 'profile': {**values, 'email': user.get('email', ''),
                                        'email_verified': user.get('client_email_verified') is True}}


@router.post('/email-verification/send')
async def send_client_email_code(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    if user.get('client_email_verified') is True:
        return {'success': True, 'verified': True}
    now = datetime.utcnow()
    last_sent = user.get('client_email_code_sent_at')
    if last_sent and last_sent > now - timedelta(minutes=1):
        raise HTTPException(429, 'Wait one minute before requesting another verification code')
    code = f'{secrets.randbelow(1_000_000):06d}'
    code_hash = hashlib.sha256((user['user_id'] + ':' + code).encode()).hexdigest()
    await db['auth_users'].update_one({'user_id': user['user_id']}, {'$set': {
        'client_email_code_hash': code_hash, 'client_email_code_expires_at': now + timedelta(minutes=10),
        'client_email_code_sent_at': now, 'client_email_code_attempts': 0,
    }})
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.post(settings.EMAIL_SERVICE_URL.rstrip('/') + '/api/v1/email/send', json={
                'to': user['email'], 'subject': 'Verify your TrainerSync client email',
                'body': f"Your TrainerSync verification code is {code}. It expires in 10 minutes. If you did not request this, ignore this email.",
                'mail_type': 'client_email_verification',
                'idempotency_key': f"client-verify:{user['user_id']}:{int(now.timestamp()) // 60}",
                'ai_generate': False,
            })
        if result.status_code >= 400 or not result.json().get('success'):
            raise RuntimeError('Verification mail was not accepted')
    except Exception:
        await db['auth_users'].update_one({'user_id': user['user_id'], 'client_email_code_hash': code_hash},
                                          {'$unset': {'client_email_code_hash': '', 'client_email_code_expires_at': ''}})
        logger.warning('Client email verification delivery failed')
        raise HTTPException(502, 'Could not send the verification email. Try again shortly.')
    return {'success': True, 'message': 'Verification code sent to your account email'}


@router.post('/email-verification/verify')
async def verify_client_email_code(payload: ClientEmailCode,
                                   x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    now = datetime.utcnow()
    expected = hashlib.sha256((user['user_id'] + ':' + payload.code).encode()).hexdigest()
    record = await db['auth_users'].find_one({'user_id': user['user_id'], 'client_email_code_expires_at': {'$gt': now}})
    if not record or record.get('client_email_code_attempts', 0) >= 5:
        raise HTTPException(400, 'Verification code is invalid or expired. Request a new one.')
    if not hmac.compare_digest(record.get('client_email_code_hash', ''), expected):
        await db['auth_users'].update_one({'user_id': user['user_id']}, {'$inc': {'client_email_code_attempts': 1}})
        raise HTTPException(400, 'Verification code is incorrect')
    await db['auth_users'].update_one({'user_id': user['user_id']}, {'$set': {
        'client_email_verified': True, 'client_email_verified_at': now,
    }, '$unset': {'client_email_code_hash': '', 'client_email_code_expires_at': '',
                  'client_email_code_attempts': '', 'client_email_code_sent_at': ''}})
    return {'success': True, 'verified': True}


@router.get('/subscription')
async def subscription_status(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    expiry = user.get('client_subscription_expires_at')
    return {
        'active': _subscription_is_active(user),
        'status': user.get('client_subscription_status', 'inactive'),
        'expires_at': expiry.isoformat() if expiry else None,
        'amount': 999, 'currency': SUBSCRIPTION_CURRENCY,
        # Browser checkout is verified with the signed Razorpay callback and a
        # server-side captured-payment lookup; webhooks are optional fallback.
        'checkout_enabled': bool(get_settings().RAZORPAY_KEY_ID and get_settings().RAZORPAY_KEY_SECRET),
        'requests_unlimited': _subscription_is_active(user),
    }


@router.post('/parse-request')
async def parse_request(payload: ClientRequestText, x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    await _client(x_authenticated_user_id, db)
    parsed = parse_client_request_text(payload.text)
    missing = [field for field in ('domain', 'duration_days', 'timeline_start') if not parsed.get(field)]
    return {'success': True, 'parsed': parsed, 'missing_fields': missing}


@router.post('/requests', status_code=201)
async def create_client_request(payload: ClientRequest, x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    if user.get('client_email_verified') is not True:
        raise HTTPException(403, 'Verify your account email before submitting a client request.')
    if not _subscription_is_active(user):
        raise HTTPException(402, 'An active one-year client subscription is required to submit requests.')
    domain = payload.domain.strip()
    if not domain:
        raise HTTPException(422, 'Add the training domain before submitting this request.')
    skills = payload.required_skills or [domain]
    now = datetime.utcnow()
    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    timeline_end = payload.timeline_end
    data = _normalise_requirement_payload({
        'requirement_id': req_id,
        'title': f'{domain} Trainer', 'technology_needed': domain, 'domain': domain,
        'required_skills': skills, 'preferred_skills': [],
        'min_experience_years': payload.min_experience_years,
        'duration_days': payload.duration_days,
        'participant_count': payload.participant_count,
        'timeline_start': payload.timeline_start, 'timeline_end': timeline_end,
        'training_dates': ' to '.join(part for part in (payload.timeline_start, timeline_end) if part),
        'timing': payload.timing, 'delivery_mode': payload.delivery_mode,
        'preferred_location': payload.location,
        'client_name': user.get('name', ''), 'client_company': user.get('company', ''),
        'client_email': user.get('email', ''), 'client_phone': user.get('phone', ''),
        'customer_id': user['user_id'], 'client_portal_user_id': user['user_id'],
        'client_portal_source': True, 'client_requirement_text': payload.request_text,
        'requirement_source_text': payload.request_text,
        'training_commercial_amount': payload.commercial_amount,
        'lab_hours_per_day': payload.lab_hours_per_day,
        'training_approach': payload.training_approach,
        'client_business_context': payload.business_context,
        'requested_deliverables': payload.requested_deliverables,
        'priority': 'medium', 'status': 'active', 'send_emails': False,
        'client_subscription_paid': True, 'client_subscription_expires_at': user['client_subscription_expires_at'],
        'metadata': {'source': 'client_portal', 'client_user_id': user['user_id']},
    })
    data.update({'requirement_id': req_id, 'client_portal_user_id': user['user_id'],
                 'client_portal_source': True, 'client_subscription_paid': True,
                 'created_at': now, 'updated_at': now})
    await db['requirements'].insert_one(data)
    shortlist = await _build_shortlist_for_requirement(db, data)
    return {'success': True, 'requirement_id': req_id,
            'matched_count': shortlist.get('total_matched', len(shortlist.get('top_trainers') or [])),
            'status': 'received'}


@router.get('/requests')
async def list_client_requests(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    cursor = db['requirements'].find({'client_portal_user_id': user['user_id']}, {
        '_id': 0, 'requirement_id': 1, 'title': 1, 'domain': 1, 'technology_needed': 1,
        'duration_days': 1, 'timeline_start': 1, 'delivery_mode': 1, 'created_at': 1,
        'client_selection_status': 1, 'client_portal_stage': 1, 'client_portal_stage_note': 1,
        'client_portal_stage_updated_at': 1,
    }).sort('created_at', -1).limit(500)
    items = [item async for item in cursor]
    if not items:
        return {'items': []}

    requirement_ids = [item['requirement_id'] for item in items if item.get('requirement_id')]
    shortlist_cursor = db['shortlists'].find({'requirement_id': {'$in': requirement_ids}}, {
        '_id': 0, 'requirement_id': 1, 'total_matched': 1,
        'pipeline_summary.status': 1, 'selection_status': 1,
    })
    shortlist_by_requirement = {
        row['requirement_id']: row async for row in shortlist_cursor if row.get('requirement_id')
    }
    for item in items:
        shortlist = shortlist_by_requirement.get(item.get('requirement_id'), {})
        matching_complete = shortlist.get('pipeline_summary', {}).get('status') == 'completed'
        selection = str(item.get('client_selection_status') or shortlist.get('selection_status') or '').lower()
        stored_stage = str(item.get('client_portal_stage') or '').lower()
        if stored_stage in {'received', 'matching', 'team_review', 'client_review', 'confirmed', 'closed'}:
            stage = stored_stage
            label = {'received': 'Request received', 'matching': 'Finding trainers', 'team_review': 'TrainerSync team review',
                     'client_review': 'Client review', 'confirmed': 'Confirmed', 'closed': 'Closed'}[stage]
        elif selection in {'selected', 'confirmed', 'client_review'}:
            stage, label = 'client_review', 'Client review'
        elif matching_complete:
            stage, label = 'team_review', 'TrainerSync team review'
        elif shortlist:
            stage, label = 'matching', 'Finding trainers'
        else:
            stage, label = 'received', 'Request received'
        item.update({
            'tracking_stage': stage,
            'tracking_label': label,
            'matching_complete': matching_complete,
            'matched_count': int(shortlist.get('total_matched') or 0),
            'tracking_note': item.get('client_portal_stage_note') or '',
            'tracking_updated_at': item.get('client_portal_stage_updated_at'),
        })
    return {'items': items}


@router.patch('/requests/{requirement_id}/stage')
async def update_client_request_stage(requirement_id: str, payload: ClientRequestStage,
                                     x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await db['auth_users'].find_one({'user_id': x_authenticated_user_id, 'status': 'active'})
    if not user or user.get('role') != 'admin':
        raise HTTPException(403, 'Staff access required')
    stage = payload.stage.strip().lower()
    allowed = {'received', 'matching', 'team_review', 'client_review', 'confirmed', 'closed'}
    if stage not in allowed:
        raise HTTPException(400, 'Choose a valid client tracking stage')
    now = datetime.utcnow()
    result = await db['requirements'].update_one({'requirement_id': requirement_id, 'client_portal_source': True}, {'$set': {
        'client_portal_stage': stage, 'client_portal_stage_note': payload.note.strip(),
        'client_portal_stage_updated_at': now, 'client_portal_stage_updated_by': user['user_id'], 'updated_at': now,
    }})
    if not result.matched_count:
        raise HTTPException(404, 'Client portal request not found')
    request = await db['requirements'].find_one({'requirement_id': requirement_id}, {'client_portal_user_id': 1}) or {}
    client = await db['auth_users'].find_one({'user_id': request.get('client_portal_user_id')}, {'email': 1, 'name': 1})
    if client and client.get('email'):
        label = {'received': 'Request received', 'matching': 'Finding trainers', 'team_review': 'TrainerSync team review',
                 'client_review': 'Client review', 'confirmed': 'Confirmed', 'closed': 'Closed'}[stage]
        body = f"Hello {client.get('name') or 'Client'},\n\nYour TrainerSync request {requirement_id} is now at: {label}.\n"
        if payload.note.strip():
            body += f"\nTeam update: {payload.note.strip()}\n"
        body += '\nSign in to your client portal to follow the request.\n\nTrainerSync'
        try:
            async with httpx.AsyncClient(timeout=12) as email_client:
                response = await email_client.post(get_settings().EMAIL_SERVICE_URL.rstrip('/') + '/api/v1/email/send', json={
                    'to': client['email'], 'subject': f'TrainerSync request update: {requirement_id}',
                    'body': body, 'mail_type': 'client_request_stage_update',
                    'idempotency_key': f'client-request-stage:{requirement_id}:{stage}:{int(now.timestamp())}',
                    'ai_generate': False,
                })
            if response.status_code >= 400 or not response.json().get('success'):
                logger.warning('Client request stage notification was not accepted')
        except Exception:
            logger.warning('Client request stage notification could not be delivered')
    return {'success': True, 'stage': stage, 'updated_at': now.isoformat()}


@router.post('/subscription/order')
async def create_subscription_order(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    settings = get_settings()
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(503, 'Annual plan checkout is not configured yet.')
    if _subscription_is_active(user):
        raise HTTPException(409, 'Your client subscription is already active.')
    receipt = 'sub-' + uuid.uuid4().hex[:24]
    try:
        async with httpx.AsyncClient(timeout=15, auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)) as client:
            response = await client.post('https://api.razorpay.com/v1/orders', json={
                'amount': SUBSCRIPTION_AMOUNT_PAISE, 'currency': SUBSCRIPTION_CURRENCY, 'receipt': receipt,
                'notes': {'client_user_id': user['user_id'], 'purpose': 'TrainerSync client one-year unlimited requests'},
            })
        response.raise_for_status()
        order = response.json()
    except Exception as exc:
        logger.warning('Razorpay client subscription order creation failed: %s', exc)
        raise HTTPException(502, 'Could not start annual subscription checkout.')
    await db['client_subscriptions'].insert_one({
        'razorpay_order_id': order['id'], 'client_user_id': user['user_id'],
        'amount': SUBSCRIPTION_AMOUNT_PAISE, 'currency': SUBSCRIPTION_CURRENCY,
        'status': 'created', 'created_at': datetime.utcnow(),
    })
    return {'order_id': order['id'], 'key_id': settings.RAZORPAY_KEY_ID,
            'amount': SUBSCRIPTION_AMOUNT_PAISE, 'currency': SUBSCRIPTION_CURRENCY,
            'name': user.get('name') or '', 'email': user.get('email') or ''}


async def _activate_subscription(db, payment_order, payment_id):
    now = datetime.utcnow()
    await db['client_subscriptions'].update_one(
        {'razorpay_order_id': payment_order['razorpay_order_id'], 'status': {'$ne': 'captured'}},
        {'$set': {'status': 'captured', 'razorpay_payment_id': payment_id,
                  'paid_at': now, 'expires_at': now + timedelta(days=SUBSCRIPTION_DAYS)}},
    )
    activated = await db['client_subscriptions'].find_one({'razorpay_order_id': payment_order['razorpay_order_id']}) or payment_order
    expiry = activated.get('expires_at') or (now + timedelta(days=SUBSCRIPTION_DAYS))
    started = activated.get('paid_at') or now
    await db['auth_users'].update_one({'user_id': payment_order['client_user_id']}, {'$set': {
        'client_subscription_status': 'active', 'client_subscription_started_at': started,
        'client_subscription_expires_at': expiry, 'client_subscription_payment_id': activated.get('razorpay_payment_id') or payment_id,
        'client_subscription_amount': SUBSCRIPTION_AMOUNT_PAISE, 'updated_at': now,
    }})
    return {'success': True, 'active': True, 'expires_at': expiry.isoformat(), 'requests_unlimited': True}


async def _verify_captured_payment(db, order_id, payment_id, *, user_id=None):
    payment_order = await db['client_subscriptions'].find_one({'razorpay_order_id': order_id})
    if not payment_order or (user_id and payment_order.get('client_user_id') != user_id):
        raise HTTPException(404, 'Subscription payment order not found')
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=12, auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)) as client:
            response = await client.get(f'https://api.razorpay.com/v1/payments/{payment_id}')
        response.raise_for_status()
        payment = response.json()
    except Exception:
        raise HTTPException(502, 'Payment status could not be verified yet. Please refresh and try again.')
    if (payment.get('order_id') != order_id or payment.get('amount') != SUBSCRIPTION_AMOUNT_PAISE
            or payment.get('currency') != SUBSCRIPTION_CURRENCY or payment.get('status') != 'captured'):
        raise HTTPException(409, 'Payment is not captured for the annual client plan')
    return await _activate_subscription(db, payment_order, payment_id)


@router.post('/subscription/verify')
async def verify_subscription_payment(payload: PaymentVerification,
                                      x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _client(x_authenticated_user_id, db)
    payment_order = await db['client_subscriptions'].find_one({
        'razorpay_order_id': payload.razorpay_order_id, 'client_user_id': user['user_id'],
        'amount': SUBSCRIPTION_AMOUNT_PAISE, 'currency': SUBSCRIPTION_CURRENCY,
    })
    if not payment_order:
        raise HTTPException(404, 'Subscription payment order not found')
    message = f'{payload.razorpay_order_id}|{payload.razorpay_payment_id}'.encode()
    expected = hmac.new(get_settings().RAZORPAY_KEY_SECRET.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        raise HTTPException(400, 'Payment signature could not be verified')
    return await _verify_captured_payment(db, payload.razorpay_order_id,
                                          payload.razorpay_payment_id, user_id=user['user_id'])


@webhook_router.post('/razorpay')
async def razorpay_webhook(request: Request, db=Depends(get_db)):
    secret = get_settings().RAZORPAY_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(503, 'Razorpay webhook is not configured')
    raw = await request.body()
    signature = request.headers.get('x-razorpay-signature', '')
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(400, 'Invalid webhook signature')
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(400, 'Invalid webhook payload')
    event_id = request.headers.get('x-razorpay-event-id', '')
    if event_id:
        try:
            await db['client_portal_webhook_events'].insert_one({'event_id': event_id, 'received_at': datetime.utcnow()})
        except DuplicateKeyError:
            pass
    if payload.get('event') == 'payment.captured':
        entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
        if (entity.get('order_id') and entity.get('id') and entity.get('status') == 'captured'
                and entity.get('currency') == SUBSCRIPTION_CURRENCY):
            if entity.get('amount') == SUBSCRIPTION_AMOUNT_PAISE:
                payment_order = await db['client_subscriptions'].find_one({'razorpay_order_id': entity['order_id']})
                if payment_order:
                    await _activate_subscription(db, payment_order, entity['id'])
            elif entity.get('amount') == 9900:
                trainer_order = await db['trainer_memberships'].find_one({'razorpay_order_id': entity['order_id']})
                if trainer_order:
                    from app.routes.trainer_membership import _activate
                    await _activate(db, trainer_order, entity['id'])
    return {'success': True}

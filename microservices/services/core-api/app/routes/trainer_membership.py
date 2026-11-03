"""One-time trainer membership checkout and paid matching priority."""
import hashlib
import hmac
import logging
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from shared.database.service import get_db
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
AMOUNT_PAISE = 9900
CURRENCY = 'INR'


async def _trainer(user_id: str, db):
    if not user_id:
        raise HTTPException(401, 'Sign in required')
    user = await db['auth_users'].find_one({'user_id': user_id, 'status': 'active'})
    if not user or user.get('role') != 'trainer':
        raise HTTPException(403, 'Trainer account required')
    return user


class PaymentVerification(BaseModel):
    razorpay_order_id: str = Field(min_length=5, max_length=64)
    razorpay_payment_id: str = Field(min_length=5, max_length=64)
    razorpay_signature: str = Field(min_length=64, max_length=128)


def _membership_active(user):
    return user.get('trainer_membership_status') == 'active'


def _status(user, settings):
    return {
        'active': _membership_active(user),
        'status': user.get('trainer_membership_status', 'free'),
        'paid_at': user.get('trainer_membership_paid_at').isoformat()
        if user.get('trainer_membership_paid_at') else None,
        'amount': 99,
        'currency': CURRENCY,
        'checkout_enabled': bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET),
        'priority': bool(_membership_active(user)),
    }


@router.get('/status')
async def membership_status(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _trainer(x_authenticated_user_id, db)
    return _status(user, get_settings())


@router.post('/order')
async def create_membership_order(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _trainer(x_authenticated_user_id, db)
    if _membership_active(user):
        raise HTTPException(409, 'Your trainer priority membership is already active.')
    settings = get_settings()
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(503, 'Trainer membership checkout is not configured yet.')
    pending = await db['trainer_memberships'].find_one({
        'trainer_user_id': user['user_id'], 'status': 'created',
    }, {'_id': 0, 'razorpay_order_id': 1})
    if pending:
        return {
            'order_id': pending['razorpay_order_id'], 'key_id': settings.RAZORPAY_KEY_ID,
            'amount': AMOUNT_PAISE, 'currency': CURRENCY,
            'name': user.get('name') or '', 'email': user.get('email') or '',
        }
    receipt = 'trn-' + uuid.uuid4().hex[:24]
    try:
        async with httpx.AsyncClient(timeout=15, auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)) as client:
            response = await client.post('https://api.razorpay.com/v1/orders', json={
                'amount': AMOUNT_PAISE, 'currency': CURRENCY, 'receipt': receipt,
                'notes': {'trainer_user_id': user['user_id'], 'purpose': 'TrainerSync one-time trainer priority membership'},
            })
        response.raise_for_status()
        order = response.json()
    except Exception as exc:
        logger.warning('Razorpay trainer membership order creation failed: %s', exc)
        raise HTTPException(502, 'Could not start trainer membership checkout.')
    await db['trainer_memberships'].insert_one({
        'razorpay_order_id': order['id'], 'trainer_user_id': user['user_id'],
        'amount': AMOUNT_PAISE, 'currency': CURRENCY, 'status': 'created',
        'created_at': datetime.utcnow(),
    })
    return {
        'order_id': order['id'], 'key_id': settings.RAZORPAY_KEY_ID,
        'amount': AMOUNT_PAISE, 'currency': CURRENCY,
        'name': user.get('name') or '', 'email': user.get('email') or '',
    }


async def _activate(db, payment_order, payment_id):
    now = datetime.utcnow()
    await db['trainer_memberships'].update_one(
        {'razorpay_order_id': payment_order['razorpay_order_id'], 'status': {'$ne': 'captured'}},
        {'$set': {'status': 'captured', 'razorpay_payment_id': payment_id, 'paid_at': now}},
    )
    membership = await db['trainer_memberships'].find_one(
        {'razorpay_order_id': payment_order['razorpay_order_id']}) or payment_order
    user_id = payment_order['trainer_user_id']
    await db['auth_users'].update_one({'user_id': user_id}, {'$set': {
        'trainer_membership_status': 'active', 'trainer_membership_paid_at': membership.get('paid_at') or now,
        'trainer_membership_payment_id': membership.get('razorpay_payment_id') or payment_id,
        'trainer_membership_amount': AMOUNT_PAISE, 'trainer_priority': True, 'updated_at': now,
    }})
    await db['trainer_profiles'].update_one({'owner_user_id': user_id}, {'$set': {
        'trainer_membership_status': 'active', 'trainer_priority': True, 'updated_at': now,
    }})
    profile = await db['trainer_profiles'].find_one({'owner_user_id': user_id}, {'trainer_id': 1}) or {}
    if profile.get('trainer_id'):
        await db['trainers'].update_one({'trainer_id': profile['trainer_id']}, {'$set': {
            'trainer_priority': True, 'trainer_membership_status': 'active', 'updated_at': now,
        }})
    return {'success': True, 'active': True, 'priority': True, 'paid_at': now.isoformat()}


@router.post('/verify')
async def verify_membership_payment(
    payload: PaymentVerification,
    x_authenticated_user_id: str = Header(default=''),
    db=Depends(get_db),
):
    user = await _trainer(x_authenticated_user_id, db)
    order = await db['trainer_memberships'].find_one({
        'razorpay_order_id': payload.razorpay_order_id, 'trainer_user_id': user['user_id'],
        'amount': AMOUNT_PAISE, 'currency': CURRENCY,
    })
    if not order:
        raise HTTPException(404, 'Trainer membership payment order not found')
    settings = get_settings()
    message = f'{payload.razorpay_order_id}|{payload.razorpay_payment_id}'.encode()
    expected = hmac.new(settings.RAZORPAY_KEY_SECRET.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        raise HTTPException(400, 'Payment signature could not be verified')
    try:
        async with httpx.AsyncClient(timeout=12, auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)) as client:
            response = await client.get(f'https://api.razorpay.com/v1/payments/{payload.razorpay_payment_id}')
        response.raise_for_status()
        payment = response.json()
    except Exception:
        raise HTTPException(502, 'Payment status could not be verified yet. Please refresh and try again.')
    if (payment.get('order_id') != payload.razorpay_order_id or payment.get('amount') != AMOUNT_PAISE
            or payment.get('currency') != CURRENCY or payment.get('status') != 'captured'):
        raise HTTPException(409, 'Payment is not captured for the trainer priority membership')
    return await _activate(db, order, payload.razorpay_payment_id)

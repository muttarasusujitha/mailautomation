"""Self-service trainer registration profiles and the staff-facing directory."""
import json
import re
import secrets
import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from shared.database.service import get_db
from app.routes.trainers import _UploadPart, _post_to_document_service
from app.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_RESUME_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.pdf', '.doc', '.docx'}


async def _account(user_id: str, db):
    if not user_id:
        raise HTTPException(401, 'Sign in required')
    user = await db['auth_users'].find_one({'user_id': user_id, 'status': 'active'})
    if not user:
        raise HTTPException(401, 'Account is unavailable')
    return user


async def _notify_trainer(profile, subject, body):
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(settings.EMAIL_SERVICE_URL.rstrip('/') + '/api/v1/email/send', json={
                'to': profile.get('email'), 'subject': subject, 'body': body,
                'mail_type': 'trainer_application_update',
                'idempotency_key': f"trainer-application:{profile.get('owner_user_id')}:{profile.get('status')}:{int(datetime.utcnow().timestamp()) // 60}",
                'ai_generate': False,
            })
        if response.status_code >= 400 or not response.json().get('success'):
            logger.warning('Trainer application update email was not accepted')
    except Exception:
        logger.warning('Trainer application update email could not be delivered')


def _json_field(value: str, field: str, fallback: Any):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f'Invalid {field} data')


def _clean_list(value, label):
    if not isinstance(value, list):
        raise HTTPException(400, f'{label} must be a list')
    return [str(item).strip() for item in value if str(item).strip()]


@router.get('/portal/profile')
async def get_my_profile(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _account(x_authenticated_user_id, db)
    if user.get('role') != 'trainer':
        raise HTTPException(403, 'Trainer account required')
    profile = await db['trainer_profiles'].find_one({'owner_user_id': user['user_id']}, {'_id': 0})
    if not profile:
        return {'profile': {'profile_name': user.get('name', ''), 'email': user.get('email', ''),
                            'domains': [user['registration_domain']] if user.get('registration_domain') else [],
                            'experience_years': '', 'linkedin_url': '', 'skills': [], 'certifications': [],
                            'summary': '', 'status': 'incomplete', 'resume_filename': ''}}
    return {'profile': profile}


@router.post('/portal/profile')
async def save_my_profile(
    profile_name: str = Form(...), experience_years: float = Form(...),
    linkedin_url: str = Form(default=''), domains_json: str = Form(...),
    skills_json: str = Form(...), certifications_json: str = Form(default='[]'),
    summary: str = Form(default=''), availability: str = Form(default=''),
    timezone: str = Form(default=''), preferred_delivery_modes_json: str = Form(default='[]'),
    expected_day_rate: str = Form(default=''), file: UploadFile | None = File(default=None),
    x_authenticated_user_id: str = Header(default=''), db=Depends(get_db),
):
    user = await _account(x_authenticated_user_id, db)
    if user.get('role') != 'trainer':
        raise HTTPException(403, 'Trainer account required')
    profile_name = profile_name.strip()
    if not profile_name or len(profile_name) > 120:
        raise HTTPException(400, 'Enter a profile name (up to 120 characters)')
    if not 0 <= experience_years <= 70:
        raise HTTPException(400, 'Experience must be between 0 and 70 years')
    linkedin_url = linkedin_url.strip()
    if linkedin_url and not re.fullmatch(r'https?://(www\.)?linkedin\.com/in/[A-Za-z0-9_%~-]+/?', linkedin_url, re.I):
        raise HTTPException(400, 'Enter a valid LinkedIn profile URL')

    domains = _clean_list(_json_field(domains_json, 'domain', []), 'Domains')
    raw_skills = _json_field(skills_json, 'skills', [])
    raw_certs = _json_field(certifications_json, 'certifications', [])
    if not domains:
        raise HTTPException(400, 'Add at least one training domain')
    if not isinstance(raw_skills, list) or not raw_skills:
        raise HTTPException(400, 'Add at least one skill')
    skills = []
    for item in raw_skills:
        if not isinstance(item, dict) or not str(item.get('name', '')).strip():
            continue
        skills.append({'name': str(item['name']).strip()[:100],
                       'subskills': _clean_list(item.get('subskills', []), 'Subskills')})
    if not skills:
        raise HTTPException(400, 'Add at least one skill')
    certifications = _clean_list(raw_certs, 'Certifications')
    if any(len(item) > 120 for item in certifications):
        raise HTTPException(400, 'Certification names must be 120 characters or fewer')
    delivery_modes = _clean_list(_json_field(preferred_delivery_modes_json, 'delivery mode', []), 'Delivery modes')
    if len(delivery_modes) > 10 or any(len(item) > 80 for item in delivery_modes):
        raise HTTPException(400, 'Use up to 10 delivery modes, each 80 characters or fewer')
    if len(availability.strip()) > 500 or len(timezone.strip()) > 80:
        raise HTTPException(400, 'Availability or timezone is too long')
    day_rate = None
    if expected_day_rate.strip():
        try:
            day_rate = float(expected_day_rate)
        except ValueError:
            raise HTTPException(400, 'Expected day rate must be a number')
        if day_rate < 0 or day_rate > 10000000:
            raise HTTPException(400, 'Expected day rate must be between 0 and 10,000,000')

    existing = await db['trainer_profiles'].find_one({'owner_user_id': user['user_id']})
    upload_id = existing.get('resume_upload_id') if existing else None
    resume_filename = existing.get('resume_filename', '') if existing else ''
    if file and file.filename:
        extension = '.' + file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, 'Upload your resume as PDF or DOC/DOCX')
        content = await file.read(MAX_RESUME_BYTES + 1)
        if not content or len(content) > MAX_RESUME_BYTES:
            raise HTTPException(413, 'Resume must be smaller than 10 MB')
        uploaded = await _post_to_document_service(_UploadPart(file.filename, content, file.content_type or 'application/octet-stream'))
        if not uploaded.get('success') or not uploaded.get('upload_id'):
            raise HTTPException(502, 'Resume could not be processed. Please try again.')
        upload_id = uploaded['upload_id']
        resume_filename = file.filename[:240]
        await db['resume_uploads'].update_one({'upload_id': upload_id}, {'$set': {
            'source_category': 'trainer_registration', 'owner_user_id': user['user_id'],
            'trainer_account_email': user['email'], 'trainer_profile_name': profile_name,
        }})
    if not upload_id:
        raise HTTPException(400, 'Upload a resume to complete your trainer profile')

    now = datetime.utcnow()
    doc = {
        'owner_user_id': user['user_id'], 'email': user['email'], 'profile_name': profile_name,
        'experience_years': experience_years, 'linkedin_url': linkedin_url,
        'domains': domains, 'skills': skills, 'certifications': certifications,
        'summary': summary.strip()[:2000], 'resume_upload_id': upload_id,
        'availability': availability.strip(), 'timezone': timezone.strip(),
        'preferred_delivery_modes': delivery_modes, 'expected_day_rate': day_rate,
        'resume_filename': resume_filename, 'source_category': 'trainer_registration',
        'trainer_membership_status': user.get('trainer_membership_status') or 'free',
        'trainer_priority': user.get('trainer_membership_status') == 'active',
        'status': 'pending_review', 'updated_at': now,
    }
    if not existing:
        doc['created_at'] = now
    await db['trainer_profiles'].update_one({'owner_user_id': user['user_id']},
        {'$set': doc, '$unset': {'review_note': ''}}, upsert=True)
    return {'success': True, 'profile': {**doc, 'created_at': (existing or {}).get('created_at', now)}}


@router.get('/portal/applications')
async def list_trainer_applications(
    domain: str = Query(default='', max_length=120), search: str = Query(default='', max_length=120),
    x_authenticated_user_id: str = Header(default=''), db=Depends(get_db),
):
    user = await _account(x_authenticated_user_id, db)
    if user.get('role') != 'admin':
        raise HTTPException(403, 'Staff access required')
    query = {}
    if domain.strip():
        query['domains'] = {'$regex': '^' + re.escape(domain.strip()) + '$', '$options': 'i'}
    if search.strip():
        pattern = re.escape(search.strip())
        query['$or'] = [{'profile_name': {'$regex': pattern, '$options': 'i'}},
                        {'email': {'$regex': pattern, '$options': 'i'}},
                        {'domains': {'$regex': pattern, '$options': 'i'}},
                        {'linkedin_url': {'$regex': pattern, '$options': 'i'}}]
    cursor = db['trainer_profiles'].find(query, {'_id': 0}).sort('updated_at', -1).limit(500)
    return {'items': [item async for item in cursor]}


@router.get('/portal/applications/{profile_id}/resume')
async def get_trainer_resume(profile_id: str, x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _account(x_authenticated_user_id, db)
    if user.get('role') != 'admin':
        raise HTTPException(403, 'Staff access required')
    profile = await db['trainer_profiles'].find_one({'owner_user_id': profile_id}, {'resume_upload_id': 1})
    if not profile or not profile.get('resume_upload_id'):
        raise HTTPException(404, 'Resume not found')
    resume = await db['resume_uploads'].find_one({'upload_id': profile['resume_upload_id'],
                                                   'source_category': 'trainer_registration'})
    if not resume or not resume.get('original_file'):
        raise HTTPException(404, 'Resume file not found')
    filename = re.sub(r'[^A-Za-z0-9._ -]', '_', resume.get('filename') or 'trainer-resume')
    return Response(content=bytes(resume['original_file']),
                    media_type=resume.get('content_type') or 'application/octet-stream',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@router.post('/portal/applications/{profile_id}/approve')
async def approve_trainer_application(profile_id: str, x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    reviewer = await _account(x_authenticated_user_id, db)
    if reviewer.get('role') != 'admin':
        raise HTTPException(403, 'Staff access required')
    profile = await db['trainer_profiles'].find_one({'owner_user_id': profile_id})
    if not profile:
        raise HTTPException(404, 'Trainer application not found')
    upload = await db['resume_uploads'].find_one({
        'upload_id': profile.get('resume_upload_id'), 'source_category': 'trainer_registration',
    })
    if not upload:
        raise HTTPException(404, 'Trainer resume not found')
    extracted = upload.get('extracted_data') or {}
    email = str(profile.get('email') or '').strip().lower()
    existing = await db['trainers'].find_one({'email': {'$regex': '^' + re.escape(email) + '$', '$options': 'i'}}) if email else None
    trainer_id = (existing or {}).get('trainer_id') or upload.get('trainer_id') or ('TR-' + secrets.token_hex(4).upper())
    skills = []
    for skill in profile.get('skills') or []:
        if isinstance(skill, dict):
            skills.extend([str(skill.get('name') or '').strip(), *[str(item).strip() for item in skill.get('subskills') or []]])
        elif skill:
            skills.append(str(skill).strip())
    skills = list(dict.fromkeys(item for item in skills if item))
    domains = profile.get('domains') or []
    trainer_doc = {
        'trainer_id': trainer_id, 'name': profile.get('profile_name') or extracted.get('name') or '',
        'email': email, 'experience_years': profile.get('experience_years') or 0,
        'linkedin': profile.get('linkedin_url') or extracted.get('linkedin') or '',
        'skills': skills, 'technology_category': domains[0] if domains else 'Multi-Skillset',
        'secondary_categories': domains[1:], 'certifications': profile.get('certifications') or [],
        'availability': profile.get('availability') or '', 'timezone': profile.get('timezone') or '',
        'preferred_delivery_modes': profile.get('preferred_delivery_modes') or [],
        'expected_day_rate': profile.get('expected_day_rate'),
        'bio': profile.get('summary') or extracted.get('summary') or '',
        'resume': str(upload.get('extracted_text') or '')[:50000],
        'trainer_priority': profile.get('trainer_priority') is True,
        'trainer_membership_status': profile.get('trainer_membership_status') or 'free',
        'source': 'trainer_registration', 'category': 'trainer_registration',
        'needs_review': False, 'profile_reviewed_by': reviewer.get('user_id'),
        'profile_reviewed_at': datetime.utcnow(), 'status': (existing or {}).get('status') or 'new',
        'updated_at': datetime.utcnow(),
    }
    if not existing:
        trainer_doc['created_at'] = datetime.utcnow()
    await db['trainers'].update_one({'trainer_id': trainer_id}, {'$set': trainer_doc}, upsert=True)
    await db['resume_uploads'].update_one({'upload_id': profile['resume_upload_id']}, {'$set': {'trainer_id': trainer_id}})
    await db['trainer_profiles'].update_one({'owner_user_id': profile_id}, {'$set': {
        'status': 'approved', 'trainer_id': trainer_id, 'reviewed_by': reviewer.get('user_id'),
        'reviewed_at': datetime.utcnow(), 'updated_at': datetime.utcnow(),
    }})
    await _notify_trainer(profile, 'Your TrainerSync application is approved',
                          f"Hi {profile.get('profile_name') or 'Trainer'},\n\nYour trainer profile has been approved and added to matching.\n\nTrainerSync")
    return {'success': True, 'status': 'approved', 'trainer_id': trainer_id}


@router.patch('/portal/applications/{profile_id}/status')
async def update_trainer_application_status(profile_id: str, payload: dict = Body(...),
                                            x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    reviewer = await _account(x_authenticated_user_id, db)
    if reviewer.get('role') != 'admin':
        raise HTTPException(403, 'Staff access required')
    status = str(payload.get('status') or '').strip().lower()
    note = str(payload.get('note') or '').strip()[:1000]
    if status not in {'needs_information', 'rejected'}:
        raise HTTPException(400, 'Choose needs_information or rejected')
    if status == 'needs_information' and not note:
        raise HTTPException(400, 'Add a note describing the information needed')
    profile = await db['trainer_profiles'].find_one({'owner_user_id': profile_id})
    if not profile:
        raise HTTPException(404, 'Trainer application not found')
    if profile.get('status') == 'approved':
        raise HTTPException(409, 'Approved trainer applications cannot be changed here')
    now = datetime.utcnow()
    await db['trainer_profiles'].update_one({'owner_user_id': profile_id}, {'$set': {
        'status': status, 'review_note': note, 'reviewed_by': reviewer.get('user_id'),
        'reviewed_at': now, 'updated_at': now,
    }})
    updated = {**profile, 'status': status, 'review_note': note}
    label = 'More information is needed' if status == 'needs_information' else 'Your application was not approved'
    body = f"Hi {profile.get('profile_name') or 'Trainer'},\n\n{label}.\n"
    if note:
        body += f"\nTeam note: {note}\n"
    body += '\nSign in to your TrainerSync portal to see the update.\n\nTrainerSync'
    await _notify_trainer(updated, 'Update on your TrainerSync application', body)
    return {'success': True, 'status': status, 'review_note': note, 'updated_at': now.isoformat()}


def _staff_account(user):
    if user.get('role') != 'admin':
        raise HTTPException(403, 'Staff access required')


def _clean_opportunity(payload):
    fields = ('company_name', 'title', 'domain', 'description', 'location', 'delivery_mode', 'duration', 'start_date')
    result = {key: str(payload.get(key) or '').strip() for key in fields}
    for key, limit in (('company_name', 160), ('title', 160), ('domain', 120), ('description', 3000),
                       ('location', 160), ('delivery_mode', 80), ('duration', 120), ('start_date', 80)):
        if len(result[key]) > limit:
            raise HTTPException(400, f'{key.replace("_", " ").capitalize()} is too long')
    if not result['company_name'] or not result['title'] or not result['domain']:
        raise HTTPException(400, 'Company, opportunity title, and domain are required')
    skills = payload.get('required_skills') or []
    if not isinstance(skills, list):
        raise HTTPException(400, 'Required skills must be a list')
    result['required_skills'] = list(dict.fromkeys(str(item).strip()[:100] for item in skills if str(item).strip()))[:40]
    result['status'] = 'active' if payload.get('status', 'active') == 'active' else 'inactive'
    return result


@router.get('/portal/opportunities')
async def list_my_opportunities(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _account(x_authenticated_user_id, db)
    if user.get('role') != 'trainer':
        raise HTTPException(403, 'Trainer account required')
    if user.get('trainer_membership_status') != 'active':
        raise HTTPException(403, 'A one-time Trainer Priority membership is required to view opportunities.')
    profile = await db['trainer_profiles'].find_one({'owner_user_id': user['user_id']}) or {}
    profile_domains = profile.get('domains') or ([user.get('registration_domain')] if user.get('registration_domain') else [])
    domains = [str(value).casefold() for value in profile_domains if value]
    skill_names = []
    for skill in profile.get('skills') or []:
        if isinstance(skill, dict):
            skill_names.extend([skill.get('name', ''), *(skill.get('subskills') or [])])
        elif skill:
            skill_names.append(skill)
    skill_names = {str(value).casefold() for value in skill_names if value}
    cursor = db['partner_opportunities'].find({'status': 'active'}, {'_id': 0}).sort('created_at', -1).limit(250)
    items = []
    for item in await cursor.to_list(length=250):
        domain_matches = str(item.get('domain') or '').casefold() in domains
        required = {str(value).casefold() for value in item.get('required_skills') or []}
        skill_matches = bool(required & skill_names)
        if (domains or skill_names) and not (domain_matches or skill_matches):
            continue
        interest = await db['trainer_opportunity_interests'].find_one(
            {'user_id': user['user_id'], 'opportunity_id': item['opportunity_id']}, {'_id': 0, 'created_at': 1})
        item['interest_submitted'] = bool(interest)
        items.append(item)
    return {'items': items, 'profile_complete': bool(domains and skill_names)}


@router.post('/portal/opportunities/{opportunity_id}/interest')
async def express_opportunity_interest(opportunity_id: str, x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _account(x_authenticated_user_id, db)
    if user.get('role') != 'trainer':
        raise HTTPException(403, 'Trainer account required')
    if user.get('trainer_membership_status') != 'active':
        raise HTTPException(403, 'A one-time Trainer Priority membership is required to express interest.')
    opportunity = await db['partner_opportunities'].find_one(
        {'opportunity_id': opportunity_id, 'status': 'active'}, {'_id': 0, 'opportunity_id': 1})
    if not opportunity:
        raise HTTPException(404, 'This opportunity is no longer available')
    profile = await db['trainer_profiles'].find_one({'owner_user_id': user['user_id']}) or {}
    now = datetime.utcnow()
    await db['trainer_opportunity_interests'].update_one(
        {'user_id': user['user_id'], 'opportunity_id': opportunity_id},
        {'$setOnInsert': {'user_id': user['user_id'], 'opportunity_id': opportunity_id,
                          'email': user.get('email', ''), 'profile_name': profile.get('profile_name') or user.get('name', ''),
                          'status': 'new', 'created_at': now}}, upsert=True)
    return {'success': True, 'message': 'Your interest has been shared with the TrainerSync team.'}


@router.get('/portal/opportunities/manage')
async def list_opportunities_for_staff(x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _account(x_authenticated_user_id, db)
    _staff_account(user)
    cursor = db['partner_opportunities'].find({}, {'_id': 0}).sort('created_at', -1).limit(500)
    items = []
    async for item in cursor:
        interest_cursor = db['trainer_opportunity_interests'].find(
            {'opportunity_id': item['opportunity_id']}, {'_id': 0, 'profile_name': 1, 'email': 1, 'status': 1, 'created_at': 1}
        ).sort('created_at', -1).limit(500)
        interested_trainers = [interest async for interest in interest_cursor]
        item['interested_trainers'] = interested_trainers
        item['interest_count'] = len(interested_trainers)
        items.append(item)
    return {'items': items}


@router.post('/portal/opportunities/manage')
async def create_partner_opportunity(payload: dict = Body(...), x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _account(x_authenticated_user_id, db)
    _staff_account(user)
    now = datetime.utcnow()
    item = {'opportunity_id': 'OPP-' + secrets.token_hex(8).upper(), **_clean_opportunity(payload),
            'created_by': user['user_id'], 'created_at': now, 'updated_at': now}
    await db['partner_opportunities'].insert_one(item)
    item.pop('_id', None)
    return {'success': True, 'item': item}


@router.patch('/portal/opportunities/manage/{opportunity_id}')
async def update_partner_opportunity(opportunity_id: str, payload: dict = Body(...), x_authenticated_user_id: str = Header(default=''), db=Depends(get_db)):
    user = await _account(x_authenticated_user_id, db)
    _staff_account(user)
    existing = await db['partner_opportunities'].find_one({'opportunity_id': opportunity_id})
    if not existing:
        raise HTTPException(404, 'Opportunity not found')
    merged = {**existing, **payload}
    clean = _clean_opportunity(merged)
    clean['updated_at'] = datetime.utcnow()
    await db['partner_opportunities'].update_one({'opportunity_id': opportunity_id}, {'$set': clean})
    return {'success': True, 'item': {**{key: value for key, value in existing.items() if key != '_id'}, **clean}}

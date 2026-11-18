"""Server-side list filters, counts and paging for the lead pages."""
import asyncio
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import pytest
from fastapi import HTTPException

from app.clients import lead_queries
from app.routes import client_leads, trainer_profile_leads
from app.routes.client_leads import delete_client_leads_by_domain, list_client_leads
from app.routes.trainer_profile_leads import delete_trainer_leads_by_domain, list_trainer_leads
from fake_mongo import FakeDB

T0 = datetime(2026, 11, 1, 8, 0)


def trainer_list(db, **params):
    base = dict(page=1, page_size=50, limit=None)
    return asyncio.run(list_trainer_leads(**{**base, **params}, db=db))


def client_list(db, **params):
    base = dict(page=1, page_size=50, limit=None)
    return asyncio.run(client_leads.list_client_leads(**{**base, **params}, db=db))


def seed(db, collection, rows):
    for index, row in enumerate(rows):
        asyncio.run(db[collection].insert_one({'lead_id': f'L{index}', 'status': 'new',
                                               'created_at': T0 + timedelta(minutes=index), **row}))


# ---- the browser filters these kinds replace, transcribed from the pages ------------------

def js_text(lead, fields):
    return ' '.join('' if lead.get(field) is None else str(lead.get(field)) for field in fields).lower()


def js_domain_terms(domain):
    generic = {'trainer', 'training', 'corporate', 'freelance', 'technical', 'online', 'instructor',
               'consultant', 'developer', 'india', 'indian'}
    return [term for term in re.findall(r'[a-z0-9+#.]+', str(domain or '').lower()) if len(term) > 1 and term not in generic]


def linkedin_search_page_shows(lead):
    text = js_text(lead, ('trainer_name', 'name', 'headline', 'profile_text', 'snippet', 'notes', 'domain'))
    terms = js_domain_terms(lead.get('domain'))
    has_skill = not terms or any(term in text for term in terms)
    url = lead.get('source_url') or ''
    has_url = any(part in url for part in ('linkedin.com/in/', 'linkedin.com/posts/', 'linkedin.com/feed/update')) \
        or lead.get('lead_type') == 'resume_trainer_post'
    has_name = bool(str(lead.get('trainer_name') or lead.get('name') or lead.get('headline') or '').strip())
    says = bool(re.search(r'trainer|instructor|corporate training|training consultant|facilitator|coach', text, re.I))
    shown = not terms or has_skill or says or lead.get('lead_type') == 'trainer_profile'
    return bool(has_url and (has_skill or shown) and (says or has_name or lead.get('lead_type') == 'trainer_profile'))


SHORTLIST_FIELDS = ('domain', 'trainer_name', 'headline', 'profile_text', 'company_name', 'contact_name', 'post_text', 'notes')


def shortlist_page_shows(lead):
    text = js_text(lead, SHORTLIST_FIELDS)
    if any(token in text for token in lead_queries._SHORTLIST_BLOCKERS):
        return False
    return any(token in text for token in lead_queries._SHORTLIST_SIGNALS)


def naukri_page_shows(lead):
    parts = urlsplit(lead.get('source_url') or '')
    path = parts.path or '/'
    return (lead.get('source') == 'naukri' and bool(re.search(r'(^|\.)naukri\.com$', parts.hostname or '', re.I))
            and bool(re.search(r'(?:^|/)(?:resume|profile|candidate)(?:/|$)|(?:^|/)(?:resume|candidate|profile)-', path, re.I))
            and not re.search(r'(?:^|/)(?:jobs?|job-listings?|career-advice|profile-summary|blog|campus|companies|company|'
                              r'services|resume-maker|resume-templates|recruiter-zone)(?:/|$)|-jobs?(?:-|$)', path, re.I))


SAMPLES = [
    {'source_url': 'https://www.linkedin.com/in/a', 'name': 'Asha', 'domain': 'Python', 'profile_text': 'Corporate trainer'},
    {'source_url': 'https://www.linkedin.com/in/b', 'name': '', 'headline': '', 'domain': 'Python', 'profile_text': 'Python coach'},
    {'source_url': 'https://www.linkedin.com/in/c', 'domain': 'AWS', 'profile_text': 'cloud architect'},
    {'source_url': 'https://www.linkedin.com/in/d', 'domain': 'AWS', 'lead_type': 'trainer_profile'},
    {'source_url': 'https://www.linkedin.com/posts/x-activity-71234567890', 'name': 'Post', 'domain': 'SAP',
     'lead_type': 'resume_trainer_post', 'profile_text': 'Freelance trainer profile attached'},
    {'source_url': 'https://www.naukri.com/resume/java-dev', 'source': 'naukri', 'name': 'Java dev', 'domain': 'Java'},
    {'source_url': 'https://www.naukri.com/java-jobs', 'source': 'naukri', 'name': 'Java jobs', 'domain': 'Java'},
    {'source_url': 'https://naukri.com/profile-summary/java', 'source': 'naukri', 'domain': 'Java'},
    {'source_url': 'https://www.naukri.com/candidate/123?ref=x', 'source': 'naukri', 'domain': 'Java'},
    {'source_url': 'https://www.naukri.com/resume-maker', 'source': 'naukri', 'domain': 'Java'},
    {'source_url': 'https://example.com/resume/x', 'source': 'naukri', 'domain': 'Java'},
    {'source_url': 'https://www.naukri.com/resume/x', 'source': 'linkedin', 'domain': 'Java'},
    {'source_url': 'https://www.linkedin.com/in/e', 'trainer_name': 'Ravi', 'headline': 'Technical trainer | Python', 'domain': 'Python'},
    {'source_url': 'https://www.linkedin.com/in/f', 'trainer_name': 'Meena', 'headline': 'Python trainer',
     'profile_text': 'Current CTC 10 LPA, notice period 30 days', 'domain': 'Python'},
    {'source_url': 'https://www.linkedin.com/in/g', 'trainer_name': 'Kiran', 'headline': 'Instructor at Acme Technologies', 'domain': 'DevOps'},
    {'source_url': 'https://www.linkedin.com/in/h', 'trainer_name': 'Job', 'headline': 'Mentor', 'domain': 'Python'},
    {'source_url': 'https://www.linkedin.com/in/i', 'trainer_name': 'Anil', 'headline': 'Mentor and coach', 'domain': 'Python',
     'profile_text': 'Experience\n12 years'},
    {'source_url': 'https://www.linkedin.com/in/j', 'trainer_name': 'Sita', 'headline': 'Faculty', 'domain': 'Python',
     'profile_text': 'Experience 12 years'},
    {'source_url': 'https://www.linkedin.com/in/k', 'trainer_name': 'Om', 'headline': 'Online training for jobs seekers',
     'domain': 'Python'},
    {'source_url': 'https://www.linkedin.com/in/l', 'trainer_name': 'Uma', 'headline': 'Classroom training', 'notes': 'Job',
     'domain': 'Python'},
]


@pytest.mark.parametrize('kind,page_shows', [
    ('linkedin_profile', linkedin_search_page_shows),
    ('shortlist', shortlist_page_shows),
    ('naukri_profile', naukri_page_shows),
])
def test_server_kinds_list_what_the_pages_used_to_show(kind, page_shows):
    db = FakeDB()
    seed(db, 'trainer_profile_leads', SAMPLES)
    listed = {lead['lead_id'] for lead in trainer_list(db, kind=kind)['leads']}
    expected = {f'L{index}' for index, lead in enumerate(SAMPLES) if page_shows(lead)}
    assert expected, 'the samples must include leads this page shows'
    assert listed == expected


def test_pipeline_filters_and_unknown_kind():
    db = FakeDB()
    seed(db, 'trainer_profile_leads', [
        {'source': 'linkedin', 'domain': 'Python', 'email': 'a@x.co', 'requirement_id': 'REQ-1'},
        {'source': '', 'domain': 'Python', 'phone': '+919999999999'},
        {'source': 'naukri', 'source_url': 'https://www.naukri.com/resume/x', 'domain': 'Python', 'email': 'b@x.co'},
        {'source': 'naukri', 'linkedin_url': 'https://www.linkedin.com/in/x', 'domain': 'Python', 'email': 'c@x.co'},
        {'source': 'linkedin', 'domain': 'Java', 'profile_text': 'Python trainer too', 'email': 'd@x.co', 'requirement_id': 'REQ-2'},
        {'source': 'linkedin', 'domain': 'Python', 'email': '  '},
    ])
    rows = trainer_list(db, kind='linkedin', topic='python', has_contact=True, requirement_scope='REQ-1')['leads']
    assert [lead['lead_id'] for lead in rows] == ['L3', 'L1', 'L0']
    with pytest.raises(HTTPException) as error:
        trainer_list(db, kind='everything')
    assert error.value.status_code == 400


def test_pages_do_not_overlap_when_a_search_saved_leads_at_one_time():
    db = FakeDB()
    for index in range(130):
        asyncio.run(db['trainer_profile_leads'].insert_one({'lead_id': f'L{index}', 'status': 'new', 'created_at': T0}))
    pages = [trainer_list(db, page=page) for page in (1, 2, 3)]
    ids = [lead['lead_id'] for page in pages for lead in page['leads']]
    assert [len(page['leads']) for page in pages] == [50, 50, 30]
    assert len(set(ids)) == 130
    assert pages[0]['total'] == 130 and pages[0]['pages'] == 3


def test_counts_ignore_their_own_filter_and_group_domain_spellings():
    db = FakeDB()
    seed(db, 'trainer_profile_leads', [
        {'domain': 'Python', 'status': 'new', 'email': 'a@x.co'},
        {'domain': ' python ', 'status': 'contacted', 'phone': '+911111111111'},
        {'domain': 'AWS', 'status': 'new'},
        {'domain': '', 'status': 'new'},
        {'status': 'rejected'},
    ])
    result = trainer_list(db, status='new', domain_exact='python', include_counts=True)
    assert [lead['lead_id'] for lead in result['leads']] == ['L0']
    counts = result['counts']
    assert counts['by_status'] == {'new': 1, 'contacted': 1}
    assert counts['by_domain'] == [
        {'value': 'aws', 'domain': 'AWS', 'total': 1, 'by_status': {'new': 1}},
        {'value': '__none__', 'domain': 'Other', 'total': 1, 'by_status': {'new': 1}},
        {'value': 'python', 'domain': 'Python', 'total': 1, 'by_status': {'new': 1}},
    ]
    assert counts['all_domains_total'] == 3 and counts['domains_total'] == 3
    assert counts['with_email'] == 1 and counts['with_phone'] == 0
    blank = trainer_list(db, domain_exact='__none__', statuses='new,rejected')['leads']
    assert sorted(lead['lead_id'] for lead in blank) == ['L3', 'L4']


def test_search_text_and_domains_are_literal_text():
    db = FakeDB()
    seed(db, 'trainer_profile_leads', [{'domain': 'C++', 'name': 'C++ trainer'}, {'domain': 'Cloud', 'name': 'Cloud trainer'}])
    seed(db, 'client_leads', [{'domain': 'C++', 'company_name': 'Acme (India)'}, {'domain': 'Cloud', 'company_name': 'Beta'}])
    assert [lead['lead_id'] for lead in trainer_list(db, domain='C++')['leads']] == ['L0']
    assert [lead['lead_id'] for lead in trainer_list(db, topic='c++')['leads']] == ['L0']
    # An unescaped "(" or "+" made the client list a database error.
    assert [lead['lead_id'] for lead in client_list(db, q='Acme (India')['leads']] == ['L0']
    assert [lead['lead_id'] for lead in client_list(db, q='c++')['leads']] == ['L0']


def test_client_list_filters_and_counts():
    db = FakeDB()
    seed(db, 'client_leads', [
        {'domain': 'Python', 'status': 'new', 'post_text': 'Need a trainer'},
        {'domain': 'Python', 'status': 'contacted', 'contact_email': 'hr@acme.co'},
        {'domain': 'SAP', 'status': 'converted', 'matched_domains': ['Python']},
        {'domain': 'SAP', 'status': 'found'},
    ])
    result = client_list(db, statuses='new,contacted,converted', topic='python', include_counts=True)
    assert sorted(lead['lead_id'] for lead in result['leads']) == ['L0', 'L1', 'L2']
    assert result['counts']['by_status'] == {'new': 1, 'contacted': 1, 'converted': 1}
    assert [(chip['domain'], chip['total']) for chip in result['counts']['by_domain']] == [('Python', 2), ('SAP', 1)]
    assert result['counts']['with_email'] == 1


@pytest.mark.parametrize('router', [trainer_profile_leads.router, client_leads.router])
def test_delete_by_domain_is_matched_before_the_lead_id_route(router):
    deletes = [route.path for route in router.routes if 'DELETE' in route.methods]
    assert deletes.index('/by-domain') < deletes.index('/{lead_id}')


def test_delete_by_domain_removes_only_what_the_chip_counted():
    db = FakeDB()
    seed(db, 'trainer_profile_leads', [
        {'domain': 'Python', 'source_url': 'https://www.linkedin.com/in/a', 'name': 'A'},
        {'domain': ' python', 'source_url': 'https://www.linkedin.com/in/b', 'name': 'B', 'status': 'contacted'},
        {'domain': 'Python', 'source': 'naukri', 'source_url': 'https://www.naukri.com/resume/c'},
        {'domain': 'Python3', 'source_url': 'https://www.linkedin.com/in/d', 'name': 'D'},
        {'domain': '', 'source_url': 'https://www.linkedin.com/in/e', 'name': 'E'},
    ])
    result = asyncio.run(delete_trainer_leads_by_domain(domain='python', kind='linkedin_profile', db=db))
    assert result['deleted_count'] == 2
    assert sorted(doc['lead_id'] for doc in db['trainer_profile_leads'].docs) == ['L2', 'L3', 'L4']
    assert asyncio.run(delete_trainer_leads_by_domain(domain='__none__', db=db))['deleted_count'] == 1
    for call in (lambda: delete_trainer_leads_by_domain(domain='  ', db=db),
                 lambda: delete_client_leads_by_domain(domain='', db=db)):
        with pytest.raises(HTTPException) as error:
            asyncio.run(call())
        assert error.value.status_code == 400


def test_client_delete_by_domain_respects_the_status_tab():
    db = FakeDB()
    seed(db, 'client_leads', [{'domain': 'SAP', 'status': 'new'}, {'domain': 'sap', 'status': 'contacted'}])
    result = asyncio.run(delete_client_leads_by_domain(domain='SAP', status='new', db=db))
    assert result['deleted_count'] == 1 and db['client_leads'].docs[0]['status'] == 'contacted'

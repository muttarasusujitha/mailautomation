"""Generate synthetic preview drafts only; no database writes or email sends."""
import asyncio
import importlib.util
import json
import sys

sys.path.insert(0, '/app')
spec = importlib.util.spec_from_file_location('natural_reply_preview', '/tmp/inbox_actions_natural.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CASES = [
    {
        'name': 'simple_acknowledgement',
        'subject': 'Re: Interview details',
        'body': 'Received the invite, thank you.',
        'workflow_context': {
            'classification': {'scenario': 'acknowledgement', 'person_type': 'trainer'},
            'extracted_request': {'sender_name': 'Mira'},
            'verified_conversation_history': [{'direction': 'outbound', 'text': 'Your interview invitation has been sent.'}],
            'recent_replies_to_this_sender': ['Hi Mira, Thank you for sharing your availability. We have sent your interview invitation.'],
        },
        'reference_reply': {'body': 'The trainer acknowledges receiving the invite. Nothing further is needed from them.'},
    },
    {
        'name': 'one_question',
        'subject': 'Session mode',
        'body': 'Is this session online or at your office?',
        'workflow_context': {'extracted_request': {'sender_name': 'Mira'},
                             'verified_facts': {'delivery_mode': 'online', 'platform': 'Google Meet'}},
        'reference_reply': {'body': 'The session is online through Google Meet. No office visit is required.'},
    },
    {
        'name': 'several_questions',
        'subject': 'DevOps session details',
        'body': 'Can you confirm the session dates, timing and delivery mode? Do attendees need their own laptops? Also, has the trainer been confirmed?',
        'workflow_context': {'extracted_request': {'sender_name': 'Mira'}, 'verified_facts': {
            'dates': '12-14 October 2026', 'time': '10:00 AM-1:00 PM IST', 'mode': 'online',
            'laptops': 'Each attendee needs their own laptop.', 'trainer': 'Awaiting confirmation',
        }},
        'reference_reply': {'body': 'Confirmed dates: 12-14 October 2026. Time: 10:00 AM-1:00 PM IST. Mode: online. Each attendee needs their own laptop. The trainer is not yet confirmed.'},
    },
    {
        'name': 'missing_azure_syllabus',
        'subject': 'Azure syllabus',
        'body': 'Please send the Azure syllabus.',
        'workflow_context': {'extracted_request': {'sender_name': 'Mira', 'technology_needed': 'Azure', 'toc_requested': True},
                             'business_features': {'toc': {'exists': False}}},
        'reference_reply': {'body': 'The requested Azure syllabus is not yet verified or available to attach. A coordinator must check it. There are no confirmed dates or trainer availability.'},
    },
]


async def main():
    results = []
    for case in CASES:
        if len(sys.argv) > 1 and case['name'] not in sys.argv[1:]:
            continue
        name = case.pop('name')
        print('DRAFTING ' + name, flush=True)
        reply = await module._ai_draft_reply(**case, require_openai=True)
        result = {'case': name, 'body': reply, 'words': len(reply.split()),
                  'needs_human_review': (case['workflow_context'].get('reply_analysis') or {}).get('needs_human_review')}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not reply:
            raise RuntimeError('No usable draft for ' + name)
    with open('/tmp/natural_email_previews.json', 'w') as output:
        json.dump(results, output, indent=2)


asyncio.run(main())

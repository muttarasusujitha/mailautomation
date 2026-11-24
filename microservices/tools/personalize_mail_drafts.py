from pathlib import Path
import re

src = Path('outputs/clahan_mail_documentation.md')
dst = Path('outputs/clahan_mail_documentation_personalized.md')
lines = src.read_text(encoding='utf-8').splitlines()
group = 'Unclassified'; message = ''

def draft(group, text):
    t = text.lower()
    if any(x in t for x in ('availability','available','slot','schedule','timing')):
        return 'Thank you for sharing your availability. We will review the proposed slots and confirm the interview/training schedule, meeting link, and next steps shortly.'
    if any(x in t for x in ('rate','commercial','quotation','quote','pricing','cost','fee','budget')):
        return 'Thank you for sharing the commercials. We are reviewing the budget and scope internally and will confirm the approved rate, inclusions, taxes, and next steps.'
    if any(x in t for x in ('resume','profile','curriculum vitae','cv','linkedin')):
        return 'Thank you for sharing your profile. We will review your experience against the training requirement and contact you with the shortlist decision and next steps.'
    if any(x in t for x in ('toc','table of contents','course outline','agenda','day-wise')):
        return 'Thank you for sharing the course outline. We will review the agenda and lab coverage against the client requirement and confirm any requested changes.'
    if any(x in t for x in ('lab','hands-on','access','laboratory')):
        return 'Thank you for the lab details. We will validate the environment, access requirements, and estimated cost, then confirm the approved setup and timeline.'
    if any(x in t for x in ('interview','meeting','discussion','call')):
        return 'Thank you for the update. We will coordinate with the relevant client/trainer and confirm the meeting time, attendees, link, and next action.'
    if any(x in t for x in ('requirement','training program','training programme','technology','duration','participant')):
        return 'Thank you for sharing the training requirement. We are reviewing the technology, duration, audience, delivery mode, and timeline and will respond with the suitable trainer/proposal.'
    if group == 'Trainer':
        return 'Thank you for your message. We have recorded the details and will review them against the active requirements before confirming the next step.'
    if group == 'Client':
        return 'Thank you for your message. We have recorded your request and will verify the details before confirming the next step and timeline.'
    return 'Thank you for your message. We have recorded the information and will review it before confirming the appropriate next step.'

out=[]
for line in lines:
    if line.startswith('## '):
        group = line[3:].split(' messages',1)[0]
    if line.startswith('- Message: '):
        message = line[len('- Message: '):]
    if line.startswith('- Clahan reply draft:'):
        line = '- Clahan personalized reply draft: ' + draft(group, message)
    out.append(line)
dst.write_text('\n'.join(out)+'\n', encoding='utf-8')
print(f'Wrote {dst}')

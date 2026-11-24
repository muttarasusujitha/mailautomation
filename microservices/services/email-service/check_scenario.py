import sys
sys.path.insert(0, r'C:\Users\sujit\Desktop\mail\mailautomation\trainer-platform-v8\microservices\services\email-service')
from app.agents.email_classifier import _text, _score, SCENARIO_KEYWORDS

sample_subject = 'Training Requirement for Python'
sample_body = '''Dear Team,

We need a Python training program for 20 participants.

Duration: 3 days
Preferred Dates: 15-17 July
Daily Training Timings: 10:00 AM - 5:00 PM
Audience Level: Intermediate
Mode: Online
Budget: INR 80,000

Regards,
Client'''
text = _text(sample_subject, sample_body, 'client@example.com', 'Client')
print('text:', text)
for name, needles in SCENARIO_KEYWORDS:
    score = _score(text, needles)
    if score > 0:
        print(f'{name}: {score}')

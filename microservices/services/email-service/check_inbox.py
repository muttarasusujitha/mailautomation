import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\sujit\Desktop\mail\mailautomation\trainer-platform-v8\microservices\services\email-service")
from app.routes import inbox
from app.agents import reply_templates

sample_subject = 'Training Requirement for Python'
sample_body = """Dear Team,

We need a Python training program for 20 participants.

Duration: 3 days
Preferred Dates: 15-17 July
Daily Training Timings: 10:00 AM - 5:00 PM
Audience Level: Intermediate
Mode: Online
Budget: INR 80,000

Regards,
Client"""
extracted = inbox._extract_requirement_from_email(sample_subject, sample_body, sender_email='client@example.com', sender_name='Client')
classification = inbox.classify_email(subject=sample_subject, body=sample_body, sender_email='client@example.com', sender_name='Client')
reply = reply_templates.build_auto_reply(classification, extracted, subject=sample_subject, sender_name='Client')
print('extracted:', extracted)
print('classification:', classification)
print('reply:', reply)

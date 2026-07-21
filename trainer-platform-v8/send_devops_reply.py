import os

import requests


BASE_URL = os.getenv("INBOX_API_BASE_URL", "http://127.0.0.1:8000/api")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5174")


def api_get(path, **params):
    url = f"{BASE_URL}{path}"
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def api_post(path, timeout=30, **payload):
    url = f"{BASE_URL}{path}"
    print(f"DEBUG: POST -> {url}")
    response = requests.post(url, json=payload, timeout=timeout)
    print(f"DEBUG: response status={response.status_code}")
    if response.status_code >= 400:
        print(f"Response: {response.text[:500]}")
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        return {}


def find_devops_email():
    data = api_get("/inbox", status="all", limit=200)
    emails = data.get("emails") or data.get("items") or []
    for email in emails:
        subject = email.get("subject") or ""
        body = email.get("body") or email.get("raw_body") or ""
        if "devops" in f"{subject}\n{body}".lower():
            return email
    return None


def ensure_requirement_created(email_id):
    result = api_post(f"/inbox/{email_id}/create-requirement", timeout=120)
    requirement_id = result.get("requirement_id")
    if requirement_id:
        print(f"Requirement created: {requirement_id}")
        print(f"Open shortlist1: {FRONTEND_URL}/shortlist1?requirement_id={requirement_id}")
    else:
        print(f"Create requirement result: {result}")
    return result


print("=== SEARCHING FOR CALHAN DEVOPS EMAIL ===\n")

try:
    email = find_devops_email()
    if not email:
        print("DevOps email not found in the live inbox API")
        raise SystemExit(1)

    email_id = email.get("email_id")
    status = email.get("status") or email.get("reply_status")
    print("Found email!")
    print(f"  Email ID: {email_id}")
    print(f"  From: {email.get('from_email')}")
    print(f"  Subject: {email.get('subject')}")
    print(f"  Status: {status}")
    print(f"  Confidence: {email.get('confidence')}")

    if status == "pending_approval":
        print("\nSending auto-reply...")
    else:
        print(f"\nEmail status is '{status}', not pending_approval")
        print("Trying to send it anyway...")

    result = api_post(f"/inbox/{email_id}/approve")
    print(f"Reply sent! Result: {result}")

    requirement_id = result.get("requirement_id") or email.get("requirement_id")
    if requirement_id:
        print(f"Open shortlist1: {FRONTEND_URL}/shortlist1?requirement_id={requirement_id}")
    else:
        print("\nNo requirement_id returned from approve; creating requirement/shortlist handoff...")
        ensure_requirement_created(email_id)
except Exception as exc:
    print(f"Error: {exc}")
    raise

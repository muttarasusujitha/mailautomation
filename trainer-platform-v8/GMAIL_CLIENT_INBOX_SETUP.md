# TrainerSync Gmail Client Inbox Setup

This setup connects Gmail API push notifications to `POST /api/gmail/webhook`, where the Client Intelligence Agent extracts client requirements, drafts Calhan Technologies replies, creates requirements, and queues approvals.

## 1. Google Cloud Project and APIs

1. Open Google Cloud Console and create/select a project.
2. Enable these APIs:
   - Gmail API
   - Cloud Pub/Sub API
3. Configure OAuth consent screen:
   - App type: External or Internal depending on your Google Workspace.
   - Add your Gmail account as a test user if the app is in testing.
4. Create OAuth client credentials:
   - Desktop app is simplest for local setup.
   - Web app is fine if you later build a browser OAuth flow.
5. Download the OAuth file as `credentials.json`.
6. Put it here:
   - `backend/config/credentials.json`

## 2. Generate Gmail OAuth Token

From the backend folder:

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
python scripts/gmail_auth.py
```

The browser consent flow creates:

```text
backend/config/token.json
```

The token scopes are:

```text
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.send
```

## 3. Pub/Sub Topic and Push Subscription

Replace `PROJECT_ID` and `YOUR_PUBLIC_BACKEND_URL`.

```bash
gcloud config set project PROJECT_ID
gcloud services enable gmail.googleapis.com pubsub.googleapis.com
gcloud pubsub topics create trainersync-inbox
gcloud pubsub topics add-iam-policy-binding trainersync-inbox \
  --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
  --role=roles/pubsub.publisher
gcloud pubsub subscriptions create trainersync-inbox-push \
  --topic=trainersync-inbox \
  --push-endpoint=https://YOUR_PUBLIC_BACKEND_URL/api/gmail/webhook \
  --ack-deadline=30
```

For local testing, expose FastAPI with a public HTTPS URL such as ngrok and use that URL as the push endpoint.

## 4. Environment Variables

Add these to `backend/.env`:

```env
GMAIL_USER=recruitment@calhantech.com
PUBSUB_TOPIC=projects/PROJECT_ID/topics/trainersync-inbox
ANTHROPIC_API_KEY=sk-ant-...

GOOGLE_CREDENTIALS_FILE=backend/config/credentials.json
GOOGLE_TOKEN_FILE=backend/config/token.json

TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
VENDOR_WHATSAPP_NUMBER=whatsapp:+91XXXXXXXXXX
```

`GMAIL_USER` must be the mailbox that was authorized by `scripts/gmail_auth.py`.

## 5. Start or Renew Gmail Watch

After credentials and token are ready:

```bash
curl -X POST http://localhost:8000/api/gmail/renew-watch
```

Or use Admin Settings > Gmail Client Inbox > Connect / Renew.

The backend calls Gmail `users.watch` for the `INBOX` label and stores the returned `historyId` in MongoDB `gmail_sync`.

Gmail watches expire within 7 days. `agents/scheduler.py` renews the watch every 6 days through APScheduler.

## 6. New Backend Dependencies

Most dependencies already exist in `backend/requirements.txt`. To install the complete set:

```bash
pip install anthropic google-auth google-auth-oauthlib google-api-python-client PyMuPDF apscheduler httpx
```

## 7. MongoDB Indexes

Run these in `mongosh`:

```javascript
db.client_emails.createIndex({ email_id: 1 }, { unique: true })
db.client_emails.createIndex({ status: 1, received_at: -1 })
db.client_emails.createIndex({ received_at: -1 })
db.client_emails.createIndex({ requirement_id: 1 })
db.client_emails.createIndex({ from_email: 1 })
db.client_emails.createIndex({ "extracted.technology_needed": 1 })

db.gmail_sync.createIndex({ sync_id: 1 }, { unique: true })
db.requirements.createIndex({ client_email_domain: 1, technology_needed: 1, created_at: -1 })
db.whatsapp_logs.createIndex({ event_type: 1, created_at: -1 })
```

## 8. Runtime Flow

1. Gmail publishes `{ emailAddress, historyId }` to Pub/Sub.
2. Pub/Sub pushes the message to `/api/gmail/webhook`.
3. Backend uses Gmail History API to fetch new message IDs since the last `historyId`.
4. The Client Intelligence Agent reads the full email, strips quotes/signatures, extracts PDF text, and asks Claude for structured JSON.
5. If it is a training request, a requirement is created with `source: "email_auto"`.
6. Claude drafts a Calhan Technologies reply.
7. Recruiter reviews it in `/inbox`, or the system auto-sends when confidence and domain rules pass.

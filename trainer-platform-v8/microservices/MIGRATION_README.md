# TrainerSync — Monolith → Microservices Migration Guide

## Overview

This document describes the full migration of **TrainerSync** from a single
FastAPI monolith (`trainer-platform-v8/backend/`) to a microservices
architecture (`trainer-platform-v8/microservices/`).

---

## Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
                         │          CLIENTS (Browser / Mobile)     │
                         └───────────────────┬─────────────────────┘
                                             │ HTTP :80
                         ┌───────────────────▼─────────────────────┐
                         │          API Gateway (nginx)             │
                         │   Rate limiting · CORS · Path routing    │
                         └───┬───────┬───────┬───────┬──────┬──────┘
                             │       │       │       │      │
          ┌──────────────────┘       │       │       │      └──────────────┐
          │                          │       │       │                     │
  ┌───────▼──────┐  ┌────────────────▼─┐  ┌─▼─────────────────┐  ┌───────▼──────┐
  │  core-api    │  │  email-service   │  │notification-service│  │trainer-service│
  │  :8001       │  │  :8002           │  │  :8003             │  │  :8004        │
  │  Customers   │  │  SMTP/IMAP/OAuth │  │  WhatsApp · Teams  │  │  CRUD · Match │
  │  Requirements│  │  Send · Inbox    │  │  Twilio/AiSensy/   │  │  Slots · TOC  │
  │  Journeys    │  │  Templates       │  │  Meta              │  │               │
  │  Automations │  └──────────────────┘  └────────────────────┘  └───────────────┘
  │  Stats · Logs│
  └──────────────┘

  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────────────────┐
  │intelligence-     │  │document-service  │  │     scheduler-service           │
  │service :8005     │  │:8006             │  │     :8007 (FastAPI API)          │
  │  Categorisation  │  │  Resume upload   │  │     celery-worker               │
  │  Client intel.   │  │  PDF / PO gen    │  │     celery-beat (periodic)      │
  │  Contact finder  │  │  Excel export    │  │     Inbox poll every 5 min      │
  │  Free search     │  │  Excel import    │  │     Interview reminders 10 min  │
  └──────────────────┘  └──────────────────┘  └─────────────────────────────────┘

                    ┌────────────────────────────────────┐
                    │  Infrastructure                    │
                    │  MongoDB 7.0 (shared database)     │
                    │  Redis 7.2    (broker + cache)     │
                    └────────────────────────────────────┘
```

---

## Service Port Map

| Service | Port | Description |
|---|---|---|
| gateway (nginx) | **80** | Public entry point |
| core-api | 8001 | Customers, Requirements, Journeys, Automations |
| email-service | 8002 | Gmail SMTP/IMAP send, inbox polling, templates |
| notification-service | 8003 | WhatsApp + Teams notifications |
| trainer-service | 8004 | Trainer CRUD, matching, slots, TOC |
| intelligence-service | 8005 | AI categorisation, contact finder, email analysis |
| document-service | 8006 | Resume upload/parse, PDF gen, Excel export |
| scheduler-service | 8007 | Celery task management API |
| MongoDB | 27017 | Internal only |
| Redis | 6379 | Internal only |

---

## Directory Structure

```
microservices/
├── docker-compose.yml          ← Orchestrates everything
├── .env.example                ← Copy to .env and fill in secrets
├── MIGRATION_README.md         ← This file
│
├── shared/                     ← Shared Python package (installed in every service)
│   ├── models/schemas.py       ← Pydantic models (Customer, Requirement, etc.)
│   ├── database/connection.py  ← Motor async MongoDB helper
│   └── events/redis_events.py  ← Redis Streams event bus helpers
│
├── gateway/
│   ├── nginx.conf              ← Upstream routing, rate limiting, CORS
│   └── Dockerfile
│
└── services/
    ├── core-api/               ← :8001
    ├── email-service/          ← :8002
    ├── notification-service/   ← :8003
    ├── trainer-service/        ← :8004
    ├── intelligence-service/   ← :8005
    ├── document-service/       ← :8006
    └── scheduler-service/      ← :8007  +  celery-worker  +  celery-beat
```

Each service contains:
```
app/
├── __init__.py
├── config.py        ← Pydantic Settings (env vars)
├── database.py      ← Motor connection wrapper
├── main.py          ← FastAPI app, router wiring, lifespan
└── routes/          ← One file per resource/domain
```

---

## Quick Start

### 1. Copy and populate the environment file

```bash
cd trainer-platform-v8/microservices
cp .env.example .env
# Edit .env — at minimum set:
#   GMAIL_USER, GMAIL_APP_PASSWORD (or GOOGLE_TOKEN_FILE for OAuth)
#   ANTHROPIC_API_KEY
#   GEMINI_API_KEY
#   TWILIO_ACCOUNT_SID / AISENSY_API_KEY  (depending on WhatsApp provider)
#   SECRET_KEY
```

### 2. (Optional) Copy Gmail OAuth token

If you use Gmail OAuth rather than an app password:
```bash
mkdir -p gmail_config
cp /path/to/your/token.json gmail_config/token.json
```
The `email-service` mounts the `gmail_config` Docker volume to `/app/config/`.

### 3. Build and start all services

```bash
docker-compose up --build -d
```

### 4. Verify everything is healthy

```bash
docker-compose ps
# All services should show "healthy"

curl http://localhost/health
# → {"status":"ok","gateway":"nginx"}
```

### 5. Access individual service docs (Swagger UI)

While services are running you can hit them directly during development:

| Service | Swagger UI |
|---|---|
| core-api | http://localhost:8001/docs |
| email-service | http://localhost:8002/docs |
| notification-service | http://localhost:8003/docs |
| trainer-service | http://localhost:8004/docs |
| intelligence-service | http://localhost:8005/docs |
| document-service | http://localhost:8006/docs |
| scheduler-service | http://localhost:8007/docs |

In production, all traffic goes through the gateway on port 80 only.

---

## Monolith → Microservice Mapping

| Monolith file | Microservice |
|---|---|
| `backend/agents/email_agent.py` | `email-service` |
| `backend/agents/whatsapp_agent.py` | `notification-service` |
| `backend/agents/teams_agent.py` | `notification-service` |
| `backend/agents/teams_direct_agent.py` | `notification-service` |
| `backend/agents/trainer_slot_agent.py` | `trainer-service` |
| `backend/agents/toc_generation_agent.py` | `trainer-service` |
| `backend/agents/resume_agent.py` | `document-service` |
| `backend/agents/document_agent.py` | `document-service` |
| `backend/agents/excel_store_agent.py` | `document-service` |
| `backend/utils/pdf_generator.py` | `document-service` |
| `backend/agents/categorisation_agent.py` | `intelligence-service` |
| `backend/agents/client_intelligence_agent.py` | `intelligence-service` |
| `backend/agents/contact_finder_agent.py` | `intelligence-service` |
| `backend/agents/free_search_agent.py` | `intelligence-service` |
| `backend/agents/linkedin_agent.py` | `intelligence-service` |
| `backend/agents/pipeline.py` | `core-api` (automations) |
| `backend/scheduler/email_scheduler.py` | `scheduler-service` |
| `backend/scheduler/interview_reminder.py` | `scheduler-service` |
| `backend/scheduler/tasks.py` | `scheduler-service` |
| `backend/agents/reminder_tasks.py` | `scheduler-service` |
| `backend/routes/api.py` | `core-api` + all services |
| `backend/models/schemas.py` | `shared/models/schemas.py` |
| `backend/database.py` | `shared/database/connection.py` |

---

## API Endpoint Mapping

All public endpoints are exposed via the gateway at `http://localhost/api/v1/...`

### Core API (8001)
| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/v1/customers` | List / create customers |
| GET/PATCH/DELETE | `/api/v1/customers/{id}` | Get / update / delete customer |
| GET/POST | `/api/v1/requirements` | List / create requirements |
| GET/PATCH/DELETE | `/api/v1/requirements/{id}` | Get / update / delete requirement |
| GET/POST | `/api/v1/journeys` | List / create journeys |
| GET/POST | `/api/v1/automations` | List / create automations |
| POST | `/api/v1/automations/{id}/trigger` | Manually trigger an automation |
| GET | `/api/v1/stats/overview` | Dashboard stats |
| GET | `/api/v1/logs/email` | Email log listing |
| GET | `/api/v1/logs/whatsapp` | WhatsApp log listing |

### Email Service (8002)
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/email/send` | Send a single email |
| POST | `/api/v1/email/send/bulk` | Send bulk emails |
| POST | `/api/v1/email/inbox/poll` | Trigger async inbox poll |
| POST | `/api/v1/email/inbox/poll/sync` | Sync inbox poll (returns counts) |
| GET | `/api/v1/email/inbox/unprocessed` | Unprocessed inbound emails |
| PATCH | `/api/v1/email/inbox/{id}/mark-processed` | Mark as processed |
| POST | `/api/v1/email/templates/shortlist-first` | Compose stage-1 email |
| POST | `/api/v1/email/templates/interview` | Compose interview email |
| POST | `/api/v1/email/templates/toc-request` | Compose TOC request email |

### Notification Service (8003)
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/notifications/whatsapp/send` | Send WhatsApp message |
| POST | `/api/v1/notifications/whatsapp/pipeline` | Stage-specific pipeline message |
| POST | `/api/v1/notifications/whatsapp/interview-reminder` | Interview reminder |
| POST | `/api/v1/notifications/teams/send` | Send Teams adaptive card |

### Trainer Service (8004)
| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/v1/trainers` | List / create trainers |
| GET/PATCH/DELETE | `/api/v1/trainers/{id}` | Get / update / delete trainer |
| POST | `/api/v1/trainers/match` | Score + rank trainers for a requirement |
| GET | `/api/v1/trainers/shortlist/{req_id}` | Get shortlisted trainers |
| POST | `/api/v1/trainer-slots/parse` | Parse availability slots from email text |
| GET | `/api/v1/trainer-slots/responses/{req_id}` | Slot responses for a requirement |
| POST | `/api/v1/trainer-slots/book` | Book an interview slot |
| POST | `/api/v1/toc/generate` | Generate training TOC |

### Intelligence Service (8005)
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/intelligence/categorise` | AI categorise a trainer (Claude) |
| POST | `/api/v1/intelligence/categorise/bulk` | Bulk categorise all uncategorised |
| POST | `/api/v1/intelligence/analyse-email` | Extract requirement from email |
| POST | `/api/v1/intelligence/score-intent` | Intent score for an email |
| POST | `/api/v1/intelligence/contacts/find` | Find email/phone for a trainer |
| POST | `/api/v1/intelligence/contacts/find/bulk` | Bulk contact find |
| POST | `/api/v1/intelligence/trainers/search` | Free web search for trainers |

### Document Service (8006)
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/documents/resume/upload` | Upload + parse a resume (PDF/DOCX) |
| GET | `/api/v1/documents/resume/uploads` | List resume uploads |
| POST | `/api/v1/documents/pdf/purchase-order` | Generate Purchase Order PDF |
| GET | `/api/v1/documents/excel/trainers` | Export trainers to Excel |
| GET | `/api/v1/documents/excel/requirements` | Export requirements to Excel |
| POST | `/api/v1/documents/excel/import` | Bulk-import rows from Excel |

### Scheduler Service (8007)
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/scheduler/tasks/inbox-poll` | Manually trigger inbox poll task |
| POST | `/api/v1/scheduler/tasks/interview-reminders` | Trigger interview reminders |
| POST | `/api/v1/scheduler/tasks/followup-reminders` | Trigger follow-up reminders |
| GET | `/api/v1/scheduler/tasks/status/{task_id}` | Get Celery task status |

---

## Celery Beat Schedule

| Task | Schedule | What it does |
|---|---|---|
| `poll_inbox` | Every 5 min | Polls Gmail IMAP for new inbound emails |
| `send_due_reminders` | Every 10 min | Fires WhatsApp interview reminders 1h before |
| `send_followup_reminders` | 9:00 AM UTC daily | Emails trainers who haven't replied in 3 days |
| `cleanup_old_logs` | 2:00 AM UTC daily | Deletes processed inbound logs older than 90 days |

---

## Data Model (Shared MongoDB Collections)

All services read/write the **same MongoDB database** (`trainer_platform`).

| Collection | Owner service | Purpose |
|---|---|---|
| `customers` | core-api | CRM clients |
| `requirements` | core-api | Training requirements |
| `journeys` | core-api | Client pipeline journeys |
| `automations` | core-api | Automation rules |
| `trainers` | trainer-service | Trainer profiles |
| `trainer_slot_responses` | trainer-service | Parsed availability slots |
| `slots` | trainer-service | Booked interview/training slots |
| `toc_generations` | trainer-service | Saved TOC outputs |
| `email_logs` | email-service | All sent/received emails |
| `whatsapp_logs` | notification-service | WhatsApp send logs |
| `teams_logs` | notification-service | Teams card send logs |
| `resume_uploads` | document-service | Resume upload records |
| `linkedin_leads` | intelligence-service | LinkedIn search leads |
| `email_analysis` | intelligence-service | AI email analysis results |
| `admin_settings` | all services | Global config (SMTP, webhook URLs, etc.) |

---

## Adding a New Service

1. Copy an existing service as a template:
   ```bash
   cp -r microservices/services/core-api microservices/services/my-service
   ```
2. Update `app/config.py` — change `SERVICE_NAME` and `PORT`.
3. Add your routes under `app/routes/`.
4. Wire them in `app/main.py`.
5. Add a `Dockerfile` (or reuse the pattern from another service).
6. Add the service block to `docker-compose.yml`.
7. Add an nginx `upstream` block and `location` rule to `gateway/nginx.conf`.

---

## Development (without Docker)

Run each service locally using `uvicorn`:

```bash
# Terminal 1 — MongoDB (or use Atlas)
mongod

# Terminal 2 — Redis
redis-server

# Terminal 3 — Core API
cd microservices/services/core-api
PYTHONPATH=../../ uvicorn app.main:app --port 8001 --reload

# Terminal 4 — Email Service
cd microservices/services/email-service
PYTHONPATH=../../ uvicorn app.main:app --port 8002 --reload

# (repeat for other services)

# Celery worker (scheduler-service directory)
cd microservices/services/scheduler-service
PYTHONPATH=. celery -A app.celery_app worker --loglevel=info
```

---

## Production Checklist

- [ ] Set a strong random `SECRET_KEY` (256-bit)
- [ ] Use MongoDB Atlas or a managed MongoDB with auth enabled
- [ ] Use a managed Redis (ElastiCache, Upstash, etc.)
- [ ] Mount Gmail `token.json` into the `email-service` container via a secret
- [ ] Add TLS termination (nginx `ssl_certificate` or an upstream load balancer)
- [ ] Set `ALLOWED_ORIGINS` to your actual frontend domain
- [ ] Set `FRONTEND_URL` for Teams shortlist links
- [ ] Enable MongoDB authentication (`MONGODB_URL=mongodb://user:pass@host/db`)
- [ ] Configure Celery beat with a persistent volume (`celery_beat_data`)
- [ ] Set up log aggregation (Loki, CloudWatch, etc.)
- [ ] Configure health-check alerts on all 7 service containers

# TrainerSync Microservices Architecture

This repository already contains a complete microservices architecture in `trainer-platform-v8/microservices/`.

## Overview

The architecture is designed as a gateway-backed microservices stack with one-to-one API routing for each service.

- `frontend` is the React/Vite SPA on port `5173` and talks to backend APIs through the gateway
- `gateway` (nginx) is the public backend entry point on port `80`
- `microservices` are the backend services exposed through `/api/v1/...`
- `database` includes MongoDB and Redis for storage, broker, and cache
- Internal microservices communicate over Docker network DNS names and container ports

## Application Layers

- `frontend` — React UI, login, client requests, pipeline dashboards, trainer workflow, inbox and reporting
- `backend` — gateway + microservices deliver functionality for requirements, email, trainer matching, notifications, AI, documents, and scheduling
- `microservices` — each FastAPI service owns a specific domain and API surface
- `database` — MongoDB stores shared application state; Redis is used for Celery task brokering and caching

## Architecture Diagram

```
        Browser / Mobile
                │
                ▼
        ┌──────────────────────┐
        │   API Gateway (80)   │
        │  nginx path routing  │
        └──────────────────────┘
           │     │     │      │
  ┌────────┴┐ ┌──┴──┐ ┌───┴───┐ ┌───────────┐
  │ auth    │ │ core │ │ email │ │ trainer   │
  │ service │ │ api  │ │ svc   │ │ service   │
  │ :8008   │ │:8001 │ │:8002  │ │:8004     │
  └─────────┘ └──────┘ └──────┘ └───────────┘
      │           │         │            │
      │           │         │            │
      │    ┌──────┴──┐  ┌───┴────┐  ┌────┴─────┐
      │    │notif-   │  │ intel- │  │ document │
      │    │service   │  │service │  │ service  │
      │    │:8003     │  │:8005   │  │:8006    │
      │    └──────────┘  └────────┘  └─────────┘
      │                              
      │                       ┌───────────────┐
      └───────────────────────▶│ scheduler svc │
                              │ :8007        │
                              └───────────────┘
                                      │
                                      ▼
                             ┌─────────────────┐
                             │ Celery worker   │
                             │ Celery beat     │
                             └─────────────────┘

         ┌─────────────────┐   ┌─────────────────┐
         │ MongoDB 27017   │   │ Redis 6379      │
         └─────────────────┘   └─────────────────┘
```

## Services and Responsibilities

### `gateway` (nginx)
- Listens on port `80`
- Routes public requests to service-specific upstreams
- Applies CORS, rate limiting, and path rewriting
- Example routes:
  - `/api/v1/auth` → `auth-service`
  - `/api/v1/customers` → `core-api`
  - `/api/v1/email` → `email-service`
  - `/api/v1/notifications` → `notification-service`
  - `/api/v1/trainers` → `trainer-service`
  - `/api/v1/intelligence` → `intelligence-service`
  - `/api/v1/documents` → `document-service`
  - `/api/v1/scheduler/tasks` → `scheduler-service`

### `auth-service` (:8008)
- Authentication and admin config APIs
- Password reset flow
- Admin settings endpoints

### `core-api` (:8001)
- Central business API for customer and requirement management
- Exposes these API groups:
  - `/api/v1/customers` — customer profiles, contacts, accounts
  - `/api/v1/requirements` — training requests, budgets, schedules, status updates
  - `/api/v1/journeys` — requirement lifecycle, client and trainer journey stages
  - `/api/v1/automations` — automation triggers, email/workflow automation state
  - `/api/v1/stats` — dashboard metrics and pipeline KPIs
  - `/api/v1/logs` — activity logging and audit events
  - `/api/v1/dashboard` — dashboard totals, charts, and client pipeline summaries
  - `/api/v1/client-pipeline` — client request / shortlist workflow state
  - `/api/v1/database` — database health, cleanup, and support utilities
- Responsible for requirement creation, shortlist orchestration, client request status, and automation coordination

### `email-service` (:8002)
- Email and inbox automation service for client/trainer communication
- Handles:
  - `/api/v1/email` — outbound email send operations and message composition
  - `/api/v1/email/inbox` — client inbox mail processing, generated reply workflow, and inbox item approval
  - `/api/v1/inbox` — inbox actions such as approve/reject/regenerate replies
  - `/api/v1/gmail` — Gmail OAuth setup, watch sync, polling, and inbox sync endpoints
  - `/api/v1/emails` — email log retrieval, search, and history
  - `/api/v1/email/templates` — email template management and dynamic template rendering
  - `/api/v1/email-open` — tracking pixel/open tracking for outbound email engagement
  - `/api/v1/client-conversations` — client conversation threads, AI reply context, and inbox summaries
  - `/api/v1/scheduler` — scheduler config for inbox sync and automation timing
  - `/api/v1/business-excel` — Excel export/import for business reporting
  - `/api/v1/client-updates` — client update notifications and post-send status updates
- Responsible for Gmail/SMTP send, reply detection, AI-generated client replies, and inbox-driven automation

### `notification-service` (:8003)
- WhatsApp messaging
- Microsoft Teams messaging
- Webhook callback handling

### `trainer-service` (:8004)
- Trainer CRUD and matching
- Resume upload and parsing
- Shortlists, slots, interview reminders
- TOC generation, invoices, purchase orders

### `intelligence-service` (:8005)
- AI categorization and analytics
- Contact finder and search
- Trainer intelligence and lead generation

### `document-service` (:8006)
- Resume upload parsing
- PDF generation
- Excel export/import

### `scheduler-service` (:8007)
- FastAPI management API for scheduled tasks
- Celery task orchestration
- Periodic jobs via `celery-beat`

### `Celery worker`
- Executes asynchronous jobs from the scheduler
- Uses Redis as broker + result backend

## Infrastructure

- `mongo`  (MongoDB 7.0) stores shared application data
- `redis`  (Redis 7.2) handles Celery broker and task state

## One-to-One API Routing

The architecture is designed so each service has a dedicated API surface:
- `/api/v1/auth/*` → auth-service
- `/api/v1/customers/*` → core-api
- `/api/v1/email/*` → email-service
- `/api/v1/notifications/*` → notification-service
- `/api/v1/trainers/*` → trainer-service
- `/api/v1/intelligence/*` → intelligence-service
- `/api/v1/documents/*` → document-service
- `/api/v1/scheduler/*` → scheduler-service

This means every microservice communicates through explicit HTTP API boundaries and not via a shared monolithic entrypoint.

## Running the Complete Stack

From `trainer-platform-v8/microservices`:

```powershell
cp .env.example .env
# fill secrets, Google, Gmail, Twilio, etc.
docker compose up --build -d
```

Frontend development runs separately:

```powershell
cd trainer-platform-v8/frontend
npm install
npm run dev
```

## Notes

- The frontend proxies `/api` to the gateway.
- Services use Docker DNS names like `email-service`, `notification-service`, `trainer-service`, etc.
- MongoDB and Redis are shared infrastructure components.
- Scheduler service uses Redis and Celery for one-to-one task processing.

## Next step

If you want, I can also add a service interaction flow diagram showing exact request chains for common use cases such as:
- trainer matchmaking
- email pipeline processing
- resume upload and AI parsing
- WhatsApp / Teams notification delivery

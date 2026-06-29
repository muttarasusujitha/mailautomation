# TrainerSync Microservice Based Architecture

TrainerSync is moving from a modular monolith to a microservice-based architecture.

## Current State

The existing application is a modular monolith:

- React frontend
- One FastAPI backend
- One MongoDB database
- Background scheduler inside the backend process
- Modules under `backend/agents` and `backend/routes`

## Target Architecture

```text
React Frontend
      |
API Gateway
      |
------------------------------------------------
| Auth Service                                  |
| Trainer Service                               |
| Requirement Service                           |
| Resume / AI Matching Service                  |
| Email / Gmail Service                         |
| Interview / Calendar Service                  |
| Notification Service                          |
| Document / Invoice Service                    |
| Admin / Configuration Service                 |
------------------------------------------------
      |
MongoDB / Redis / Message Queue / File Storage
```

## Implemented Microservice Topology

This repository now contains a complete microservice topology:

- `services/api-gateway`
  - Frontend entry point for `/api/*`
  - Routes `/api/auth/google/*` to `auth-service`
  - Routes each business domain to its service

- `services/auth-service`
  - Owns Google login
  - Exposes `/auth/google/client-id`
  - Exposes `/auth/google/login`
  - Stores Google users in MongoDB `auth_users`

- `services/domain-proxy`
  - Reusable FastAPI service shell for extracted domains
  - Runs as separate containers for trainer, requirement, email, AI, notification, document, interview, and admin services
  - Proxies to `legacy-backend` until each service owns its internal business logic

- `legacy-backend`
  - Existing FastAPI backend
  - Temporary compatibility service during migration
  - Continues to execute existing business logic until modules are moved into their owning services

## Runtime Services

| Runtime Container | Source | Responsibility |
| --- | --- | --- |
| `frontend` | `frontend` | React UI |
| `api-gateway` | `services/api-gateway` | Single API entry point and routing |
| `auth-service` | `services/auth-service` | Google login and user identity |
| `trainer-service` | `services/domain-proxy` | Trainer and resume routes |
| `requirement-service` | `services/domain-proxy` | Requirements, shortlists, pipeline routes |
| `email-service` | `services/domain-proxy` | Email, Gmail, inbox, conversation routes |
| `ai-service` | `services/domain-proxy` | Assistant, AI, client lead, trainer lead routes |
| `notification-service` | `services/domain-proxy` | WhatsApp and Teams routes |
| `document-service` | `services/domain-proxy` | TOC, purchase order, invoice routes |
| `interview-service` | `services/domain-proxy` | Interview schedule and reminder routes |
| `admin-service` | `services/domain-proxy` | Admin, dashboard, scheduler, business Excel routes |
| `legacy-backend` | `backend` | Temporary compatibility backend |
| `mongo` | MongoDB image | Data store |
| `redis` | Redis image | Cache, queues, scheduler dependencies |

## API Gateway Routing

| API Prefix | Routed To |
| --- | --- |
| `/api/auth/google/*` | `auth-service` |
| `/api/trainers/*`, `/api/resume-uploads/*`, `/api/resume-data/*`, `/api/contact-finder/*` | `trainer-service` |
| `/api/requirements/*`, `/api/shortlists/*`, `/api/client-pipeline/*` | `requirement-service` |
| `/api/emails/*`, `/api/gmail/*`, `/api/inbox/*`, `/api/email-open/*`, `/api/client-conversations/*`, `/api/client-updates/*` | `email-service` |
| `/api/ai/*`, `/api/assistant/*`, `/api/client-leads/*`, `/api/trainer-profile-leads/*` | `ai-service` |
| `/api/whatsapp/*`, `/api/teams-direct/*` | `notification-service` |
| `/api/toc/*`, `/api/purchase-orders/*`, `/api/invoices/*` | `document-service` |
| `/api/interview-reminders/*`, `/api/interview-schedules/*` | `interview-service` |
| `/api/admin/*`, `/api/scheduler/*`, `/api/business-excel/*`, `/api/dashboard/*`, `/api/database/*` | `admin-service` |
| Unmapped `/api/*` | `legacy-backend` fallback |

## Service Ownership Plan

| Service | Responsibility |
| --- | --- |
| Auth Service | Google login, roles, identity, future JWT/session ownership |
| Trainer Service | Trainer profiles, categories, domains, availability |
| Requirement Service | Client requirements, shortlist records, selection workflow |
| Resume / AI Service | Resume parsing, AI matching, domain extraction, lead enrichment |
| Email / Gmail Service | Gmail OAuth, email sending, inbox polling, reply tracking |
| Interview Service | Calendar events, Meet links, schedule management |
| Notification Service | WhatsApp, Teams, reminders, alerts |
| Document Service | TOC, purchase orders, invoices, PDF/Excel generation |
| Admin Service | Runtime configuration, provider credentials, scheduler settings |

## Communication Pattern

- Frontend talks only to the API Gateway.
- API Gateway routes requests to the correct service.
- Services use REST for synchronous requests.
- Long-running work should use Redis/Celery or RabbitMQ events.
- Heavy services like Resume / AI and Email can scale independently.

## Run Microservice Mode

```bash
docker compose -f docker-compose.microservices.yml up --build
```

Then open:

```text
http://localhost:5173
```

Frontend requests go to:

```text
http://localhost:5173/api/*
```

The Vite proxy sends them to the API Gateway:

```text
api-gateway:8080
```

## Migration Roadmap

1. Move Email / Gmail logic from `legacy-backend` into `email-service`.
2. Move Resume and AI matching logic into `ai-service`.
3. Move Trainer profile logic into `trainer-service`.
4. Move Requirement and shortlist logic into `requirement-service`.
5. Move WhatsApp and Teams logic into `notification-service`.
6. Move TOC, purchase order, and invoice logic into `document-service`.
7. Move interview reminders and schedule logic into `interview-service`.
8. Move admin settings and scheduler ownership into `admin-service`.

This lets TrainerSync become microservice-based without rewriting the whole application at once.

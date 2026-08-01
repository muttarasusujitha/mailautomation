# TrainerSync Project Documentation

This document describes the main architecture of the TrainerSync project, including the frontend route structure, gateway routing, SMTP and Gmail integration, and the request flow for key features.

---

## 1. Project Overview

TrainerSync is a full-stack trainer matching and client communication platform built with:

- React + Vite frontend
- FastAPI microservices backend
- Nginx gateway for API routing
- MongoDB for persistence
- Redis + Celery for background jobs
- Gmail API + SMTP/IMAP for inbox and outbound email automation

The system is designed around a gateway-backed microservice architecture where each domain has its own API surface.

---

## 2. High-Level Architecture

```text
Browser / User
   │
   ▼
React Frontend (Vite)
   │
   ▼
Nginx Gateway (port 80 / 8000)
   │
   ├─ Auth Service
   ├─ Core API
   ├─ Email Service
   ├─ Trainer Service
   ├─ Notification Service
   ├─ Intelligence Service
   ├─ Document Service
   └─ Scheduler Service

Shared infrastructure:
- MongoDB
- Redis
- Celery Worker / Celery Beat
```

---

## 3. Frontend Route Map

The frontend uses React Router and renders the following main pages:

| Route | Page | Purpose |
|---|---|---|
| /login | Login | Authentication screen |
| /dashboard | Dashboard | Main analytics and summary dashboard |
| /admin-dashboard | AdminDashboard | Admin overview and admin-level operations |
| /trainers | Trainers | Manage trainer profiles and data |
| /requirements | Requirements | Create and manage client requirements |
| /emails | Emails | Email management and outreach workflow |
| /client-requests | ClientRequests | Review and manage client requests |
| /client-pipeline | ClientPipeline | Client workflow pipeline |
| /resume-upload | ResumeUpload | Upload resumes and process trainer data |
| /inbox | Inbox | Inbox-driven workflow and approval actions |
| /admin | Admin | Configuration, Gmail, Teams, SMTP, and automation settings |
| /shortlist | Shortlist | Trainer shortlist management |
| /communication-pipeline | CommunicationPipeline | Communication workflow overview |
| /profile | Profile | User profile page |
| /auth/callback | GmailCallback | Gmail OAuth callback handler |
| /auth/linkedin/callback | LinkedInCallback | LinkedIn OAuth callback handler |

### Route-to-Service Mapping

Most frontend pages call the gateway, which forwards the request to the appropriate backend service.

Examples:
- Dashboard → Core API
- Requirements → Core API
- Emails / Inbox / Gmail → Email Service
- Trainers / Shortlist / Resume Upload → Trainer Service
- Admin settings → Auth Service
- Notifications → Notification Service

---

## 4. Gateway Architecture

The gateway is implemented with nginx and acts as the public entry point.

### Responsibilities

- Receive incoming HTTP requests from the frontend
- Route requests to the proper microservice by path prefix
- Apply rate limiting and basic security headers
- Handle CORS preflight requests
- Forward requests to internal Docker service names

### Gateway Upstreams

The gateway routes requests to internal services using Docker DNS names:

- auth-service → port 8008
- core-api → port 8001
- email-service → port 8002
- notification-service → port 8003
- trainer-service → port 8004
- intelligence-service → port 8005
- document-service → port 8006
- scheduler-service → port 8007

### Example Routing Rules

| Path Prefix | Target Service |
|---|---|
| /api/v1/auth | Auth Service |
| /api/v1/admin | Auth Service |
| /api/v1/customers | Core API |
| /api/v1/requirements | Core API |
| /api/v1/dashboard | Core API |
| /api/v1/email | Email Service |
| /api/v1/inbox | Email Service |
| /api/v1/gmail | Email Service |
| /api/v1/notifications | Notification Service |
| /api/v1/trainers | Trainer Service |
| /api/v1/resume-uploads | Trainer Service |
| /api/v1/toc | Trainer Service |
| /api/v1/scheduler/tasks | Scheduler Service |

---

## 5. Backend Service Responsibilities

### 5.1 Auth Service
Used for authentication, admin settings, and system configuration.

Typical responsibilities:
- Login and session handling
- Admin configuration endpoints
- SMTP / IMAP / Teams config storage
- Email and notification test actions

### 5.2 Core API
Acts as the central orchestration layer for business data.

Typical responsibilities:
- Customer and requirement management
- Journey and workflow state
- Dashboard stats and analytics
- Client pipeline tracking
- Automation coordination

### 5.3 Email Service
Handles all email workflow and Gmail integration.

Typical responsibilities:
- Outbound email sending
- Inbox polling and processing
- Gmail OAuth authorization
- Gmail watch / webhook handling
- Auto-reply generation and approval workflows
- Email tracking and conversation threads

### 5.4 Trainer Service
Handles trainer workflows and content generation.

Typical responsibilities:
- Trainer CRUD operations
- Matching and shortlist logic
- Resume upload handling
- Interview scheduling
- TOC generation and invoice-related flows

### 5.5 Notification Service
Handles messaging integrations such as:
- WhatsApp
- Microsoft Teams
- Incoming webhook callback processing

### 5.6 Scheduler Service
Runs scheduled jobs using Celery.

Typical responsibilities:
- Polling inbox periodically
- Triggering reminder workflows
- Background processing for email and notification flows

---

## 6. SMTP Flow

SMTP is used for sending outbound emails from the platform.

### Typical flow

1. A user or automation triggers an outbound email request.
2. The frontend sends the request through the gateway.
3. The gateway forwards the request to the Email Service.
4. The Email Service builds the message and sends it using SMTP.
5. The email is delivered to the target recipient.

### Common SMTP settings

The Email Service supports:
- SMTP host
- SMTP port
- SMTP username
- SMTP password
- fallback SMTP credentials
- sender name and sender email

### Why SMTP is used

SMTP is used when the platform must send emails directly from the configured mailbox or provider, especially for:
- auto-replies
- outreach emails
- recruiter communications
- follow-up messages

---

## 7. Gmail API Flow

The platform also integrates with Gmail using the Gmail API and OAuth 2.0.

### Main Gmail capabilities

- OAuth connection to the Gmail account
- Reading inbox messages
- Monitoring inbox changes via Gmail watch
- Processing inbound client emails automatically
- Sending mail through Gmail-backed flows
- Managing Gmail history and push notifications

### OAuth flow

1. The user clicks connect in the UI.
2. The frontend calls the Gmail OAuth endpoint through the gateway.
3. The Email Service generates an OAuth URL.
4. Google redirects back to the configured callback route.
5. The system saves the OAuth token for future requests.

### Gmail webhook / push flow

1. Gmail publishes updates for the inbox.
2. The Gmail push subscription sends a webhook request to the backend.
3. The Email Service receives the webhook and processes the new message.
4. The system extracts the email content, classifies it, and triggers the corresponding workflow.

### Gmail-related endpoints

The gateway exposes Gmail routes through:

- /api/v1/gmail/auth-status
- /api/v1/gmail/oauth-url
- /api/v1/gmail/oauth-callback
- /api/v1/gmail/renew-watch
- /api/v1/gmail/webhook

---

## 8. End-to-End Example: Sending a Client Reply

### Flow

1. A recruiter or automation opens the inbox or client communication page.
2. The frontend calls the appropriate API through the gateway.
3. The request is routed to the Email Service.
4. The Email Service prepares the draft/reply.
5. The system sends the email using SMTP or Gmail-backed delivery.
6. The reply is logged and tracked in the system.

### Result

The platform can:
- process inbound emails
- generate a reply draft
- send the message
- track delivery or response activity

---

## 9. Infrastructure Components

### MongoDB
Stores:
- requirements
- trainer data
- email logs
- automation state
- Gmail sync information
- admin configuration

### Redis
Used for:
- Celery broker
- task state
- background job coordination

### Celery Worker / Beat
Used for:
- periodic inbox polling
- scheduled reminders
- asynchronous processing

---

## 10. Recommended Documentation Structure for Future Pages

If you want to build a multi-page documentation site, the following pages would work well:

1. Home / Overview
2. Architecture and Gateway Routing
3. Frontend Route Map
4. SMTP and Email Delivery
5. Gmail API and OAuth Setup
6. Microservices Breakdown
7. Background Jobs and Scheduling
8. Deployment and Environment Configuration

---

## 11. Summary

TrainerSync combines:
- a React frontend with many business pages
- an nginx gateway for routing
- microservices for auth, core operations, emails, trainers, notifications, documents, and scheduling
- SMTP and Gmail API for communication automation
- MongoDB, Redis, and Celery for data storage and background processing

This architecture allows the platform to support high-volume email workflows, recruiter operations, trainer matching, and client communication from one integrated system.

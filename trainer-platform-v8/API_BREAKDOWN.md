# TrainerSync Application - Complete API Breakdown

## Overview
TrainerSync uses **11+ external APIs** + **8 internal microservices**. The application is designed as a microservices architecture with specialized services for different functions.

---

## 📡 EXTERNAL APIs USED

### 1. **AI/LLM APIs** (via Intelligence Service - Port 8006)
**Purpose:** Content analysis, resume parsing, profile matching, conversational AI

| API | Service | Use Case | Location |
|-----|---------|----------|----------|
| **Anthropic Claude** | `ANTHROPIC_API_KEY` | Resume analysis, client intelligence extraction | Intelligence Service |
| **Google Gemini** | `GEMINI_API_KEY` | Alternative AI model for categorization | Intelligence Service |
| **OpenAI GPT** | `OPENAI_API_KEY` | LLM fallback, text generation | Intelligence Service |
| **Ollomo AI** | `OLLOMO_API_KEY` + `OLLOMO_API_URL` | Custom AI model for specialized tasks | Intelligence Service |

**Config Location:** `trainer-platform-v8/backend/.env`

---

### 2. **Email APIs** (Email Service - Port 8002)
**Purpose:** Send/receive emails, SMTP/IMAP, Gmail OAuth

| API | Provider | Use Case | Authentication |
|-----|----------|----------|-----------------|
| **Gmail API** | Google Cloud | OAuth token-based email access | `GOOGLE_TOKEN_FILE: config/token.json` |
| **SMTP** | Gmail | Email sending via app password | `GMAIL_APP_PASSWORD` / `GMAIL_FALLBACK_APP_PASSWORD` |
| **IMAP** | Gmail | Inbox synchronization, mail retrieval | Same as SMTP |

**Config:**
```
GMAIL_USER=<REDACTED>
GMAIL_APP_PASSWORD=<REDACTED>
GMAIL_FALLBACK_USER=<REDACTED>
GMAIL_FALLBACK_APP_PASSWORD=<REDACTED>
SMTP_HOST=smtp.gmail.com:587
IMAP_HOST=imap.gmail.com:993
```

---

### 3. **Search APIs** (Intelligence Service - Port 8006)
**Purpose:** Find trainers, job postings, company data

| API | Purpose | Rate Limit |
|-----|---------|-----------|
| **Tavily Search API** | `TAVILY_API_KEY` | Free search for trainer discovery | `FREE_SEARCH_MAX_RESULTS=20` |

**Config:**
```
TAVILY_API_KEY=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
TAVILY_SEARCH_DEPTH=basic
FREE_SEARCH_TIMEOUT=25 seconds
```

---

### 4. **WhatsApp/SMS Notification APIs** (Notification Service - Port 8003)
**Purpose:** Send notifications, alerts, interview reminders

| Provider | Use Case | Config |
|----------|----------|--------|
| **Twilio** | SMS + WhatsApp messaging | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` |
| **AiSensy** | WhatsApp templates | `AISENSY_API_KEY`, `AISENSY_API_URL`, Campaign templates |
| **Meta (Facebook)** | WhatsApp Business API | `META_WHATSAPP_PHONE_NUMBER_ID`, `META_WHATSAPP_ACCESS_TOKEN` |

**Config:**
```
WHATSAPP_PROVIDER=twilio (default)
TWILIO_ACCOUNT_SID=ACxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
VENDOR_WHATSAPP_NUMBER=+91XXXXXXXXXX
```

---

### 5. **Microsoft Teams API** (Notification Service - Port 8003)
**Purpose:** Send notifications to Teams channels, direct messages

| Endpoint | Purpose |
|----------|---------|
| **Teams Webhooks** | Post messages to Teams channels |
| **Microsoft Graph API** | Direct user messaging, integration |
| **Teams Direct** | User-to-user messaging |

**Config:**
```
MICROSOFT_TENANT_ID=common
MICROSOFT_CLIENT_ID=your_microsoft_client_id
MICROSOFT_CLIENT_SECRET=your_microsoft_client_secret
TEAMS_WEBHOOK_URL=your_teams_webhook_url
```

---

### 6. **Authentication/OAuth APIs**
**Purpose:** User login, session management

| Provider | Service | Location |
|----------|---------|----------|
| **Google OAuth 2.0** | Frontend login + Backend Gmail access | Login page (`http://localhost:5173/login`) |
| **GitHub OAuth** | Frontend login alternative | Login page |

**Config:**
```
GOOGLE_CLIENT_ID=<REDACTED>
GOOGLE_CLIENT_SECRET=<REDACTED>
GOOGLE_REDIRECT_URI=http://localhost:5173/auth/callback
```

---

## 🏗️ INTERNAL MICROSERVICES ARCHITECTURE

All services run on `0.0.0.0` with the following ports:

### Core Services

| Service | Port | Purpose | APIs Used |
|---------|------|---------|-----------|
| **Core API** | 8001 | Central hub - trainers, requirements, journeys, automations, stats, dashboard | Internal ↔ all services |
| **Auth Service** | 8008 | User authentication, JWT tokens, role management | OAuth (Google/GitHub) |
| **Email Service** | 8002 | Gmail SMTP/IMAP, inbox polling, email sending | Gmail API, SMTP/IMAP |
| **Trainer Service** | 8004 | Trainer profiles, skills, experience, certifications | Internal ↔ Core API |
| **Document Service** | 8005 | Resume parsing, PDF processing, file uploads | AI (Claude/Gemini) |
| **Intelligence Service** | 8006 | AI analysis, resume extraction, client intel, assistant chat, leads | Anthropic, Gemini, OpenAI, Tavily |
| **Notification Service** | 8003 | WhatsApp, Teams, SMS notifications | Twilio, AiSensy, Meta, Microsoft Teams |
| **Scheduler Service** | 8007 | Celery Beat - scheduled tasks, email polling, reminders | Redis, APScheduler |

---

## 🔄 SERVICE COMMUNICATION FLOW

```
Frontend (5173)
    ↓
Auth Service (8008) ←→ OAuth (Google/GitHub)
    ↓
Core API (8001)
    ├→ Trainer Service (8004)
    ├→ Document Service (8005)
    ├→ Email Service (8002) ←→ Gmail API / SMTP / IMAP
    ├→ Intelligence Service (8006)
    │   ├→ Anthropic Claude API
    │   ├→ Google Gemini API
    │   ├→ OpenAI API
    │   └→ Tavily Search API
    ├→ Notification Service (8003)
    │   ├→ Twilio API
    │   ├→ AiSensy API
    │   ├→ Meta WhatsApp API
    │   └→ Microsoft Teams API
    └→ Scheduler Service (8007)
        └→ Redis / Celery
```

---

## 📊 API USAGE BREAKDOWN BY MODULE

### **User Authentication (No Cost)**
- Google OAuth 2.0 ✓
- GitHub OAuth ✓

### **Email & Communication (Free with usage limits)**
- Gmail API (Free tier)
- SMTP/IMAP (Free)

### **AI/Intelligence (Paid per usage)**
- Anthropic: ~$3-15/MTok
- Gemini: ~$0.075-0.30/MTok
- OpenAI: ~$0.50-15/MTok
- Ollomo: Custom pricing

### **Search (Paid - $0.05 per request)**
- Tavily: Free tier 100req/month

### **Notifications (Paid per message)**
- Twilio: ~$0.0075/SMS, WhatsApp variable
- AiSensy: Custom WhatsApp pricing
- Meta: ~$0.0014-0.005 per WhatsApp message
- Microsoft Teams: Free

### **Data Processing**
- MongoDB: Local (free) / Atlas (paid)
- Redis: Local (free)

---

## 🚀 WHY THESE APIS?

| API | Why Used |
|-----|----------|
| **Multiple AI Models** | Redundancy + cost optimization + specialized use cases |
| **Gmail API** | Direct integration with business email workflows |
| **WhatsApp APIs** | Multi-channel notification (Twilio fallback, Meta primary) |
| **Tavily Search** | Low-cost trainer & job discovery |
| **Teams API** | Enterprise integration with Microsoft customers |
| **OAuth** | Secure login without password management |
| **Microservices** | Scale each component independently |
| **Celery/Scheduler** | Async task processing for long-running operations |

---

## 🔐 SECURITY NOTES

⚠️ **App Passwords Exposed Earlier:**
- `GMAIL_APP_PASSWORD`: <REDACTED>
- `GMAIL_FALLBACK_APP_PASSWORD`: <REDACTED>

**Action Required:**
1. Regenerate both passwords in Google Account
2. Update `.env` files with new passwords (avoid committing secrets)
3. Restart services

---

## 📋 CONFIGURATION FILES

- **Backend .env**: `trainer-platform-v8/backend/.env`
- **Microservices .env**: `trainer-platform-v8/microservices/.env`
- **Frontend .env**: `trainer-platform-v8/frontend/.env`
- **Docker Compose**: `trainer-platform-v8/microservices/docker-compose.yml`

---

## 🎯 CURRENTLY RUNNING SERVICES

✅ Frontend: `http://localhost:5173/`
✅ Core API: `http://localhost:8001/`
✅ Trainer Service: `http://localhost:8004/`
✅ Auth Service: `http://localhost:8008/`
✅ Document Service: `http://localhost:8005/`
✅ Intelligence Service: `http://localhost:8006/`
✅ Notification Service: `http://localhost:8003/`
✅ Scheduler Service: `http://localhost:8007/`
❌ Email Service: `http://localhost:8002/` (Needs MongoDB)

**Status Dashboard:** `http://localhost:8001/docs` (Swagger UI)

---

**Last Updated:** 2026-07-16

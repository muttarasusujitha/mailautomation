from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
from app.routes import whatsapp, teams, whatsapp_webhooks, teams_direct

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await shutdown_db()


app = FastAPI(
    title="Notification Service",
    description="WhatsApp (Twilio/AiSensy/Meta), Teams webhooks, Teams Direct messaging",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Outbound notifications
app.include_router(whatsapp.router,          prefix="/api/v1/notifications/whatsapp", tags=["whatsapp"])
app.include_router(teams.router,             prefix="/api/v1/notifications/teams",    tags=["teams"])

# Inbound webhooks
app.include_router(whatsapp_webhooks.router, prefix="/api/v1/whatsapp",               tags=["whatsapp-webhooks"])

# Teams Direct (Graph API)
app.include_router(teams_direct.router,      prefix="/api/v1/teams-direct",           tags=["teams-direct"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

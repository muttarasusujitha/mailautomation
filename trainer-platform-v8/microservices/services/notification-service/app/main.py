from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
from app.routes import whatsapp, teams

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await shutdown_db()


app = FastAPI(
    title="Notification Service",
    description="WhatsApp (Twilio / AiSensy / Meta) and Microsoft Teams notifications",
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

app.include_router(whatsapp.router, prefix="/api/v1/notifications/whatsapp", tags=["whatsapp"])
app.include_router(teams.router, prefix="/api/v1/notifications/teams", tags=["teams"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

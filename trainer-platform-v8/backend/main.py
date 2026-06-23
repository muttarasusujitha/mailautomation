import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from database import connect_db, close_db
from routes.api import router
from agents.scheduler import load_config_from_db, start_scheduler, stop_scheduler
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# SEC-001: SECRET_KEY must be explicitly set — no insecure fallback allowed
_secret_key = str(settings.secret_key or "").strip()
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Set a strong random secret in your .env file before starting the server."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await connect_db()
    await load_config_from_db()
    start_scheduler()
    yield
    # Shutdown
    await close_db()
    stop_scheduler()


app = FastAPI(
    title="TrainerSync API",
    description="AI-Powered Trainer Matching Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# SEC-003: Explicit CORS allowlist — never use wildcard with credentials
_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in [
        settings.frontend_url,
        "http://localhost:5173",
        "http://localhost:3000",
    ]
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)

app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "TrainerSync API is running", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}

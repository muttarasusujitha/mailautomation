from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
from app.routes import send, inbox, templates

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await shutdown_db()


app = FastAPI(
    title="Email Service",
    description="Gmail SMTP/IMAP send, inbox polling, inbound processing, auto-reply templates",
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

app.include_router(send.router, prefix="/api/v1/email", tags=["email-send"])
app.include_router(inbox.router, prefix="/api/v1/email/inbox", tags=["email-inbox"])
app.include_router(templates.router, prefix="/api/v1/email/templates", tags=["email-templates"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

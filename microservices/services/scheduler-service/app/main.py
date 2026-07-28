from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import tasks

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # Celery worker/beat are separate processes


app = FastAPI(
    title="Scheduler Service",
    description="Celery beat scheduler — inbox polling, interview reminders, follow-ups",
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

app.include_router(tasks.router, prefix="/api/v1/scheduler/tasks", tags=["tasks"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

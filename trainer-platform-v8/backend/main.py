from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from database import connect_db, close_db
from routes.api import router
from agents.scheduler import start_scheduler, stop_scheduler
from config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await connect_db()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)

app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "TrainerSync API is running 🚀", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}

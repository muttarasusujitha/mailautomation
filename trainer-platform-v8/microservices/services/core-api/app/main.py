from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
from app.routes import (
    customers,
    requirements,
    journeys,
    automations,
    stats,
    logs,
    dashboard,
    client_pipeline,
    database,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await shutdown_db()


app = FastAPI(
    title="Core API Service",
    description="Customers, Requirements, Journeys, Automations, Dashboard, Client Pipeline",
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

app.include_router(customers.router,       prefix="/api/v1/customers",       tags=["customers"])
app.include_router(requirements.router,    prefix="/api/v1/requirements",    tags=["requirements"])
app.include_router(journeys.router,        prefix="/api/v1/journeys",        tags=["journeys"])
app.include_router(automations.router,     prefix="/api/v1/automations",     tags=["automations"])
app.include_router(stats.router,           prefix="/api/v1/stats",           tags=["stats"])
app.include_router(logs.router,            prefix="/api/v1/logs",            tags=["logs"])
app.include_router(dashboard.router,       prefix="/api/v1/dashboard",       tags=["dashboard"])
app.include_router(client_pipeline.router, prefix="/api/v1/client-pipeline", tags=["client-pipeline"])
app.include_router(database.router,        prefix="/api/v1/database",        tags=["database"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

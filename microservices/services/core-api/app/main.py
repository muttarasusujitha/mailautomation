from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from shared.database.service import init_db as connect_service_db, shutdown_db
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
logger = logging.getLogger(__name__)


async def _create_index(db, collection: str, keys, **kwargs) -> None:
    try:
        await db[collection].create_index(keys, background=True, **kwargs)
    except Exception as exc:
        logger.warning("Skipping index for %s %s: %s", collection, keys, exc)


async def _ensure_indexes(db) -> None:
    indexes = [
        ("requirements", [("requirement_id", 1)], {}),
        ("requirements", [("status", 1), ("created_at", -1)], {}),
        ("requirements", [("customer_id", 1), ("status", 1), ("created_at", -1)], {}),
        ("requirements", [("client_email", 1), ("status", 1), ("created_at", -1)], {}),
        ("requirements", [("technology_needed", 1), ("status", 1)], {}),
        ("requirements", [("domain", 1), ("status", 1)], {}),
        ("requirements", [("metadata.source_email_id", 1)], {"sparse": True}),
        ("shortlists", [("requirement_id", 1)], {}),
        ("shortlists", [("updated_at", -1)], {}),
        ("email_logs", [("requirement_id", 1), ("created_at", -1)], {}),
        ("email_logs", [("direction", 1), ("status", 1), ("created_at", -1)], {}),
        ("client_emails", [("status", 1), ("created_at", -1)], {}),
        ("client_emails", [("requirement_id", 1), ("updated_at", -1)], {}),
        ("trainers", [("trainer_id", 1)], {}),
        ("trainers", [("created_at", -1)], {}),
        ("purchase_orders", [("requirement_id", 1), ("created_at", -1)], {}),
        ("invoices", [("requirement_id", 1), ("created_at", -1)], {}),
        ("whatsapp_logs", [("status", 1), ("created_at", -1)], {}),
    ]
    for collection, keys, options in indexes:
        await _create_index(db, collection, keys, **options)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await connect_service_db(settings)
    await _ensure_indexes(db)
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

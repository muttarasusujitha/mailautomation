from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from shared.database.service import init_db as connect_service_db, shutdown_db
from app.routes import accounts, admin
from app.security import ensure_indexes, require_admin

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_service_db(settings)
    from shared.database.service import get_db
    await ensure_indexes(await get_db())
    yield
    await shutdown_db()


app = FastAPI(
    title="Auth Service",
    description="Authentication, admin settings, and diagnostics",
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

app.include_router(accounts.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

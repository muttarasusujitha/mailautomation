from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
from app.routes import trainers, matching, slots, toc

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await shutdown_db()


app = FastAPI(
    title="Trainer Service",
    description="Trainer CRUD, requirement matching, slot management, and TOC generation",
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

app.include_router(trainers.router, prefix="/api/v1/trainers", tags=["trainers"])
app.include_router(matching.router, prefix="/api/v1/trainers", tags=["matching"])
app.include_router(slots.router, prefix="/api/v1/trainer-slots", tags=["slots"])
app.include_router(toc.router, prefix="/api/v1/toc", tags=["toc"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

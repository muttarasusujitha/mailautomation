from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, shutdown_db
from app.routes import resume, pdf, excel

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await shutdown_db()


app = FastAPI(
    title="Document Service",
    description="Resume upload & parsing, PDF generation, Excel export/import",
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

app.include_router(resume.router, prefix="/api/v1/documents/resume", tags=["resume"])
app.include_router(pdf.router, prefix="/api/v1/documents/pdf", tags=["pdf"])
app.include_router(excel.router, prefix="/api/v1/documents/excel", tags=["excel"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

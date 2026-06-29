import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    auth_service_url: str = "http://localhost:8101"
    trainer_service_url: str = "http://localhost:8201"
    requirement_service_url: str = "http://localhost:8202"
    email_service_url: str = "http://localhost:8203"
    ai_service_url: str = "http://localhost:8204"
    notification_service_url: str = "http://localhost:8205"
    document_service_url: str = "http://localhost:8206"
    interview_service_url: str = "http://localhost:8207"
    admin_service_url: str = "http://localhost:8208"
    legacy_backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    proxy_timeout_seconds: float = 300.0

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()

SERVICE_ROUTES = [
    (
        "trainer-service",
        settings.trainer_service_url,
        (
            "trainers",
            "resume-uploads",
            "resume-data",
            "contact-finder",
        ),
    ),
    (
        "requirement-service",
        settings.requirement_service_url,
        (
            "requirements",
            "shortlists",
            "client-pipeline",
        ),
    ),
    (
        "email-service",
        settings.email_service_url,
        (
            "emails",
            "gmail",
            "inbox",
            "email-open",
            "client-conversations",
            "client-updates",
        ),
    ),
    (
        "ai-service",
        settings.ai_service_url,
        (
            "ai",
            "assistant",
            "client-leads",
            "trainer-profile-leads",
        ),
    ),
    (
        "notification-service",
        settings.notification_service_url,
        (
            "whatsapp",
            "teams-direct",
        ),
    ),
    (
        "document-service",
        settings.document_service_url,
        (
            "toc",
            "purchase-orders",
            "invoices",
        ),
    ),
    (
        "interview-service",
        settings.interview_service_url,
        (
            "interview-reminders",
            "interview-schedules",
        ),
    ),
    (
        "admin-service",
        settings.admin_service_url,
        (
            "admin",
            "scheduler",
            "business-excel",
            "dashboard",
            "database",
        ),
    ),
]

app = FastAPI(
    title="TrainerSync API Gateway",
    description="Gateway that routes requests to TrainerSync microservices.",
    version="1.0.0",
)

allowed_origins = [
    origin.strip()
    for origin in settings.allowed_origins.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def forwarded_headers(request: Request) -> dict:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-proto"] = request.url.scheme
    return headers


def response_headers(upstream_headers: httpx.Headers) -> dict:
    return {
        key: value
        for key, value in upstream_headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


async def proxy_request(request: Request, upstream_base: str, upstream_path: str) -> Response:
    upstream_base = upstream_base.rstrip("/")
    upstream_path = upstream_path.lstrip("/")
    url = f"{upstream_base}/{upstream_path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body()
    timeout = httpx.Timeout(settings.proxy_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        upstream_response = await client.request(
            request.method,
            url,
            content=body,
            headers=forwarded_headers(request),
        )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )


def service_for_path(path: str) -> tuple[str, str]:
    normalized = path.strip("/")
    for service_name, service_url, prefixes in SERVICE_ROUTES:
        for prefix in prefixes:
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                return service_name, service_url
    return "legacy-backend", settings.legacy_backend_url


@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5) as client:
        service_urls = {
            "auth-service": settings.auth_service_url,
            "legacy-backend": settings.legacy_backend_url,
        }
        service_urls.update({
            service_name: service_url
            for service_name, service_url, _ in SERVICE_ROUTES
        })
        checks = {}
        for service_name, service_url in service_urls.items():
            try:
                response = await client.get(f"{service_url.rstrip('/')}/health")
                checks[service_name] = response.status_code
            except httpx.HTTPError:
                checks[service_name] = "unreachable"
    return {
        "status": "ok",
        "service": "api-gateway",
        "dependencies": checks,
    }


@app.api_route(
    "/api/auth/google/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def route_google_auth(path: str, request: Request):
    return await proxy_request(request, settings.auth_service_url, f"auth/google/{path}")


@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def route_legacy_backend(path: str, request: Request):
    _, service_url = service_for_path(path)
    return await proxy_request(request, service_url, f"api/{path}")


@app.get("/{full_path:path}", include_in_schema=False)
async def frontend_route_fallback(full_path: str, request: Request):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    target = f"{settings.frontend_url.rstrip('/')}/{full_path.lstrip('/')}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(target, status_code=302)

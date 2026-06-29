import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "domain-service"
    legacy_backend_url: str = "http://localhost:8000"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    proxy_timeout_seconds: float = 300.0

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
app = FastAPI(
    title=f"TrainerSync {settings.service_name}",
    description=(
        "Domain microservice boundary for TrainerSync. "
        "During migration it proxies matching requests to the legacy backend."
    ),
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
    headers["x-trainersync-service"] = settings.service_name
    return headers


def response_headers(upstream_headers: httpx.Headers) -> dict:
    return {
        key: value
        for key, value in upstream_headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


async def proxy_to_legacy(request: Request, path: str) -> Response:
    url = f"{settings.legacy_backend_url.rstrip('/')}/{path.lstrip('/')}"
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


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.service_name}


@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_api(path: str, request: Request):
    return await proxy_to_legacy(request, f"api/{path}")

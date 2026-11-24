from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "trainersync"
    google_client_id: str = ""
    frontend_url: str = "http://localhost:5173"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
mongo_client: AsyncIOMotorClient | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_db():
    if mongo_client is None:
        raise HTTPException(503, "Auth service database is not connected")
    return mongo_client[settings.mongodb_db]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client
    mongo_client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    await mongo_client.admin.command("ping")
    await get_db()["auth_users"].create_index("email", unique=True, background=True)
    yield
    if mongo_client is not None:
        mongo_client.close()
        mongo_client = None


app = FastAPI(
    title="TrainerSync Auth Service",
    description="Authentication and identity microservice for TrainerSync.",
    version="1.0.0",
    lifespan=lifespan,
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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)


def google_login_client_id() -> str:
    return str(settings.google_client_id or "").strip()


async def google_profile_from_access_token(access_token: str, client_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        token_info_res = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": access_token},
        )
        if token_info_res.status_code != 200:
            raise HTTPException(401, "Google login token is invalid or expired")

        token_info = token_info_res.json()
        token_audience = str(token_info.get("aud") or "").strip()
        if token_audience and token_audience != client_id:
            raise HTTPException(401, "Google login token was issued for another app")

        userinfo_res = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_res.status_code != 200:
            raise HTTPException(401, "Could not read Google profile")
        return userinfo_res.json()


def google_profile_from_id_token(credential: str, client_id: str) -> dict:
    try:
        return google_id_token.verify_oauth2_token(
            credential,
            GoogleAuthRequest(),
            client_id,
        )
    except ValueError as exc:
        raise HTTPException(401, "Google login token is invalid or expired") from exc


def google_email_verified(profile: dict) -> bool:
    value = profile.get("email_verified")
    if isinstance(value, bool):
        return value
    return str(value or "").lower() in {"true", "1", "yes"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "auth-service"}


@app.get("/auth/google/client-id")
async def get_google_client_id():
    client_id = google_login_client_id()
    if not client_id:
        raise HTTPException(500, "Google client ID is not configured")
    return {"client_id": client_id}


@app.get("/auth/google/callback")
async def google_oauth_compat_callback(request: Request):
    frontend_url = str(settings.frontend_url or "http://localhost:5173").rstrip("/")
    callback_url = f"{frontend_url}/auth/callback"
    query = str(request.url.query or "").strip()
    redirect_hint = urlencode({"oauth_redirect_uri": str(request.url).split("?", 1)[0]})
    query = f"{query}&{redirect_hint}" if query else redirect_hint
    if query:
        callback_url = f"{callback_url}?{query}"
    return RedirectResponse(callback_url, status_code=302)


@app.post("/auth/google/login")
async def google_login(payload: dict):
    client_id = google_login_client_id()
    if not client_id:
        raise HTTPException(500, "Google client ID is not configured")

    access_token = str(payload.get("access_token") or "").strip()
    credential = str(payload.get("credential") or payload.get("id_token") or "").strip()
    if credential:
        profile = google_profile_from_id_token(credential, client_id)
    elif access_token:
        profile = await google_profile_from_access_token(access_token, client_id)
    else:
        raise HTTPException(400, "Google login token is missing")

    email = str(profile.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(401, "Google did not return a valid email address")
    if not google_email_verified(profile):
        raise HTTPException(401, "Google email address is not verified")

    role = str(payload.get("role") or "recruiter").strip().lower()
    if role not in {"recruiter", "trainer", "employee"}:
        role = "recruiter"

    now = utc_now()
    user = {
        "email": email,
        "name": profile.get("name") or email.split("@", 1)[0],
        "picture": profile.get("picture") or "",
        "google_sub": profile.get("sub") or "",
        "role": role,
        "auth_provider": "google",
        "email_verified": True,
    }
    await get_db()["auth_users"].update_one(
        {"email": email},
        {
            "$set": {
                **user,
                "last_login_at": now,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return {"message": "Google login successful", "user": user, "loggedIn": True}

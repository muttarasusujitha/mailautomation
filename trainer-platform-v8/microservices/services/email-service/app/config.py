import os
from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


PLACEHOLDER_EMAILS = {
    "your-gmail-address@gmail.com",
    "your-email@gmail.com",
    "yourname@example.com",
    "your-email@example.com",
    "email@example.com",
    "test@example.com",
    "your@email.com",
}


def _normalize_email_value(value: str) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("mailto:"):
        raw = raw[7:]
    raw = raw.split("?", 1)[0].strip()
    if raw.lower() in PLACEHOLDER_EMAILS:
        return ""
    return raw


class Settings(BaseSettings):
    SERVICE_NAME: str = "email-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    DEBUG: bool = False

    MONGODB_URL: str = "mongodb://127.0.0.1:27017"
    MONGODB_DB_NAME: str = "trainersync"
    REDIS_URL: str = "redis://127.0.0.1:6379"

    # Gmail / SMTP
    GMAIL_USER: str = ""
    GMAIL_APP_PASSWORD: str = ""
    GMAIL_PASS: str = ""          # alias
    GMAIL_FALLBACK_USER: str = ""
    GMAIL_FALLBACK_APP_PASSWORD: str = ""
    GMAIL_FALLBACK_PASS: str = ""
    GMAIL_FALLBACK_FROM_NAME: str = ""
    GMAIL_FALLBACK_FROM_EMAIL: str = ""
    FROM_NAME: str = "TrainerSync"
    FROM_EMAIL: str = ""
    GOOGLE_TOKEN_FILE: str = "config/token.json"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    GOOGLE_CALENDAR_ID: str = "primary"
    GOOGLE_CALENDAR_TIMEZONE: str = "Asia/Kolkata"
    GMAIL_PUBSUB_TOPIC: str = ""
    FRONTEND_URL: str = "http://localhost:5173"
    CORE_API_URL: str = "http://core-api:8001"
    TRAINER_SERVICE_URL: str = "http://trainer-service:8004"
    INTERNAL_SERVICE_TOKEN: str = ""

    @field_validator("FROM_EMAIL", mode="before")
    @classmethod
    def normalize_from_email(cls, value: str) -> str:
        return _normalize_email_value(value)

    @field_validator("GMAIL_USER", mode="before")
    @classmethod
    def normalize_gmail_user(cls, value: str) -> str:
        return _normalize_email_value(value)

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug(cls, value: str) -> bool:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "0", "false", "no", "n", "off"}:
                return False
            if normalized in {"1", "true", "yes", "y", "on", "debug"}:
                return True
        return value

    # SMTP overrides
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "z-ai/glm-5.2[im]"
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def effective_gmail_pass(self) -> str:
        return (self.GMAIL_APP_PASSWORD or self.GMAIL_PASS).replace(" ", "")

    @property
    def effective_gmail_fallback_pass(self) -> str:
        return (self.GMAIL_FALLBACK_APP_PASSWORD or self.GMAIL_FALLBACK_PASS).replace(" ", "")

    class Config:
        env_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        env_file = os.path.join(env_dir, ".env")
        env_file_encoding = "utf-8"
        extra = "allow"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()

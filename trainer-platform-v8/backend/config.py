import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


_BACKEND_DIR = Path(__file__).resolve().parent
_ENV_FILE_PATH = _BACKEND_DIR / ".env"


def _read_env_value(name: str) -> str:
    value = os.getenv(name.upper(), "").strip()
    if value:
        return value
    if not _ENV_FILE_PATH.exists():
        return ""
    for line in _ENV_FILE_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name.upper()}="):
            return stripped.split("=", 1)[1].strip().strip("\"'")
    return ""


def _write_env_value(name: str, value: str) -> None:
    if not _ENV_FILE_PATH.exists():
        _ENV_FILE_PATH.write_text("", encoding="utf-8")
    lines = _ENV_FILE_PATH.read_text(encoding="utf-8").splitlines()
    updated_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{name.upper()}="):
            updated_lines.append(f"{name.upper()}={value}")
            found = True
        else:
            updated_lines.append(line)
    if not found:
        if updated_lines and updated_lines[-1]:
            updated_lines.append("")
        updated_lines.append(f"{name.upper()}={value}")
    _ENV_FILE_PATH.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "trainersync"
    gmail_user: str = ""
    gmail_app_password: str = ""
    gmail_pass: str = ""  # alias for gmail_app_password
    from_email: str = ""
    from_name: str = "TrainerSync"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:5173/auth/callback"
    google_cloud_project: str = ""
    pubsub_topic: str = ""
    google_credentials_file: str = ""
    google_token_file: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    secret_key: str = ""
    frontend_url: str = "http://localhost:5173"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    teams_webhook_url: str = ""
    free_search_provider: str = "auto"
    free_search_max_results: int = 20
    free_search_timeout: int = 30
    tavily_api_key: str = ""
    tavily_search_depth: str = "basic"
    tavily_endpoint: str = "https://api.tavily.com/search"

    class Config:
        env_file = str(_ENV_FILE_PATH)
        extra = "allow"


@lru_cache()
def get_settings():
    secret_key = _read_env_value("SECRET_KEY")
    if not secret_key:
        secret_key = secrets.token_urlsafe(32)
        _write_env_value("SECRET_KEY", secret_key)
    os.environ.setdefault("SECRET_KEY", secret_key)
    settings = Settings()
    if not (settings.secret_key or "").strip():
        settings.secret_key = secret_key
    return settings

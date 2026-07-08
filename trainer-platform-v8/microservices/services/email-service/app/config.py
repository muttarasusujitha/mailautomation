from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    SERVICE_NAME: str = "email-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    DEBUG: bool = False

    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "trainersync"
    REDIS_URL: str = "redis://localhost:6379"

    # Gmail / SMTP
    GMAIL_USER: str = ""
    GMAIL_APP_PASSWORD: str = ""
    GMAIL_PASS: str = ""          # alias
    FROM_NAME: str = "TrainerSync"
    FROM_EMAIL: str = ""
    GOOGLE_TOKEN_FILE: str = "config/token.json"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    GMAIL_PUBSUB_TOPIC: str = ""
    FRONTEND_URL: str = "http://localhost:5173"
    CORE_API_URL: str = "http://core-api:8001"
    TRAINER_SERVICE_URL: str = "http://trainer-service:8004"

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

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    SERVICE_NAME: str = "scheduler-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8007
    DEBUG: bool = False

    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "trainersync"

    # Redis / Celery broker
    REDIS_URL: str = "redis://localhost:6379"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Internal service URLs (for HTTP calls between services)
    EMAIL_SERVICE_URL: str = "http://email-service:8002"
    NOTIFICATION_SERVICE_URL: str = "http://notification-service:8003"

    # Reminder lead-time in hours
    INTERVIEW_REMINDER_HOURS_BEFORE: int = 1

    ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

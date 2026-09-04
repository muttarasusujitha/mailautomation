from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URL: str = "mongodb://mongo:27017"
    MONGODB_DB_NAME: str = "trainersync"
    MEET_BOT_ENABLED: bool = False
    MEET_BOT_PROFILE_PATH: str = "/data/chrome-profile"
    MEET_BOT_JOIN_MINUTES_BEFORE: int = 3
    MEET_BOT_DEFAULT_DURATION_MINUTES: int = 60
    MEET_BOT_LEAVE_MINUTES_AFTER: int = 10
    MEET_BOT_AUTO_ADMIT: bool = False
    MEET_BOT_HEADLESS: bool = False
    MEET_BOT_POLL_SECONDS: int = 20
    MEET_BOT_HEALTH_PORT: int = 8010
    MEET_BOT_ALLOWED_HOSTS: str = "meet.google.com"
    MEET_BOT_MAX_ATTEMPTS: int = 3

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache
def get_settings() -> Settings:
    return Settings()

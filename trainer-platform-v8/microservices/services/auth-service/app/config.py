from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    SERVICE_NAME: str = "auth-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8008
    DEBUG: bool = False

    MONGODB_URL: str = "mongodb://127.0.0.1:27017"
    MONGODB_DB_NAME: str = "trainersync"
    REDIS_URL: str = "redis://127.0.0.1:6379"
    SECRET_KEY: str = "change-me"
    ALLOWED_ORIGINS: str = "https://localhost:3000"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

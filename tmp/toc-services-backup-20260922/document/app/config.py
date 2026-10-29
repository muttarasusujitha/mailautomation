from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    SERVICE_NAME: str = "document-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8006
    DEBUG: bool = False

    MONGODB_URL: str = "mongodb://127.0.0.1:27017"
    MONGODB_DB_NAME: str = "trainersync"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5.5"

    # Max resume upload size in bytes (default 10 MB)
    MAX_UPLOAD_BYTES: int = 10_485_760

    ALLOWED_ORIGINS: str = "http://localhost:5174,http://127.0.0.1:5174,https://localhost:3000"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "0", "false", "no", "n", "off"}:
                return False
            if normalized in {"1", "true", "yes", "y", "on", "debug"}:
                return True
        return value

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

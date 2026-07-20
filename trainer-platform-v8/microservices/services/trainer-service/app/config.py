from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    SERVICE_NAME: str = "trainer-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8004
    DEBUG: bool = False

    MONGODB_URL: str = "mongodb://127.0.0.1:27017"
    MONGODB_DB_NAME: str = "trainersync"
    REDIS_URL: str = "redis://127.0.0.1:6379"
    DOCUMENT_SERVICE_URL: str = "http://127.0.0.1:8006"
    EMAIL_SERVICE_URL: str = "http://127.0.0.1:8002"
    NOTIFICATION_SERVICE_URL: str = "http://127.0.0.1:8003"
    INTERNAL_SERVICE_TOKEN: str = ""

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    ANTHROPIC_API_KEY: str = ""

    ALLOWED_ORIGINS: str = "http://localhost:3000"

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

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        _base_env_dir = Path(__file__).resolve()
        for _ in range(6):
            if (_base_env_dir / '.env').exists() or (_base_env_dir / '.env.local').exists():
                break
            if _base_env_dir.parent == _base_env_dir:
                break
            _base_env_dir = _base_env_dir.parent

        _local_env_file = _base_env_dir / '.env.local'
        env_file = str(_local_env_file if _local_env_file.exists() else _base_env_dir / '.env')
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

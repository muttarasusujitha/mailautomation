from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    SERVICE_NAME: str = "intelligence-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8005
    DEBUG: bool = False

    MONGODB_URL: str = "mongodb://127.0.0.1:27017"
    MONGODB_DB_NAME: str = "trainersync"
    REDIS_URL: str = "redis://127.0.0.1:6379"

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "z-ai/glm-5.2[im]"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # Local Ollama Sonnet model settings
    OLLAMA_BINARY: str = "ollama"
    OLLAMA_SONNET_MODEL: str = "claude-sonnet-4-20250514"

    # LinkedIn / search
    PROXYCURL_API_KEY: str = ""
    SERPER_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    TAVILY_API_URL: str = "https://api.tavily.dev"

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

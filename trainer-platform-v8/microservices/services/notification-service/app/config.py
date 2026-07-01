from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    SERVICE_NAME: str = "notification-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8003
    DEBUG: bool = False

    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "trainersync"
    REDIS_URL: str = "redis://localhost:6379"

    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = ""

    # AiSensy
    AISENSY_API_KEY: str = ""
    AISENSY_CAMPAIGN_NAME: str = ""
    AISENSY_SOURCE: str = "TrainerSync"
    AISENSY_TEMPLATE_PARAM_FIELDS: str = "message"
    AISENSY_TAGS: str = "trainersync"

    # Meta / WhatsApp Cloud API
    META_WHATSAPP_PHONE_NUMBER_ID: str = ""
    META_WHATSAPP_ACCESS_TOKEN: str = ""
    META_WHATSAPP_TEMPLATE_NAME: str = ""
    META_WHATSAPP_LANGUAGE_CODE: str = "en_US"
    META_GRAPH_API_VERSION: str = "v23.0"

    # Teams
    TEAMS_WEBHOOK_URL: str = ""
    FRONTEND_URL: str = "http://localhost:3000"

    WHATSAPP_PROVIDER: str = "twilio"
    VENDOR_WHATSAPP_NUMBER: str = ""
    DEFAULT_COUNTRY_CODE: str = "+91"

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

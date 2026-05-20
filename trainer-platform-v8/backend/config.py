from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "trainersync"
    gmail_user: str = ""
    gmail_app_password: str = ""
    gmail_pass: str = ""          # alias for gmail_app_password
    from_email: str = ""
    from_name: str = "TrainerSync"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    google_cloud_project: str = ""
    pubsub_topic: str = ""
    google_credentials_file: str = ""
    google_token_file: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    secret_key: str = "changeme_use_random_string"
    frontend_url: str = "http://localhost:5173"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    teams_webhook_url: str = ""

    class Config:
        env_file = ".env"
        extra = "allow"

@lru_cache()
def get_settings():
    return Settings()

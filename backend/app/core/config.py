import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Neuro-Seller"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = "gpt-4-turbo-preview"
    
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    
    API_V1_PREFIX: str = "/api/v1"
    
    class Config:
        case_sensitive = True

settings = Settings()

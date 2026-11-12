from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    PROJECT_NAME: str = "CivicFix AI — Autonomous Citizen Complaint Resolution Platform"
    API_V1_STR: str = "/api"
    
    # Database
    DATABASE_URL: str = "sqlite:///./civicfix.db"
    
    # Security
    JWT_SECRET_KEY: str = "dev_secret_key_civicfix_ai_super_secure_92384729"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # LLM Settings
    LLM_PROVIDER: str = "fallback"  # "openai", "anthropic", "gemini", or "fallback"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4o-mini"
    
    # File Storage
    UPLOAD_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: list[str] = [".jpg", ".jpeg", ".png", ".webp", ".pdf"]
    
    # CORS
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    
    model_config = {"env_file": ".env", "case_sensitive": True}

settings = Settings()
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

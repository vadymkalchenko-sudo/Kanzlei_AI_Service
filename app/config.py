"""
Configuration management for AI Service
"""
from pydantic_settings import BaseSettings
from typing import Literal
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # LLM Provider
    llm_provider: Literal["gemini", "loki"] = "gemini"

    # Gemini Configuration
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"  # Stand Feb 2026 — stable

    # Loki Configuration (Hybrid Two-Model Architecture)
    loki_url: str = "http://10.10.10.5:11434"
    loki_vision_model: str = "llama-vision-work"
    loki_mapping_model: str = "qwen-work"

    # Backend API
    backend_url: str = "http://localhost:8000"
    backend_api_token: str = ""

    # Service Configuration
    service_port: int = 5000
    debug: bool = True

    # File Upload
    max_file_size_mb: int = 50
    allowed_extensions: str = ".eml,.msg,.pdf,.jpg,.jpeg,.png,.doc,.docx"

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/ai-service.log"

    class Config:
        # Absoluter Pfad damit uvicorn die .env auch findet
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        case_sensitive = False


# Global settings instance
settings = Settings()

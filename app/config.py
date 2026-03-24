"""
Configuration management for AI Service
"""
from pydantic_settings import BaseSettings
from typing import Literal
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # LLM Provider: "gemini" = Gemini Developer API (lokal), "vertex" = Vertex AI (Prod/DSGVO), "loki" = Ollama
    llm_provider: Literal["gemini", "vertex", "loki"] = "gemini"

    # Gemini Developer API (lokal / Fallback)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Vertex AI (Produktion — DSGVO, EU-Region europe-west3 = Frankfurt)
    vertex_project_id: str = ""
    vertex_location: str = "europe-west3"
    vertex_model: str = "gemini-2.5-flash"
    google_application_credentials: str = "/app/google_service_account.json"

    # Loki Configuration (Hybrid Two-Model Architecture)
    loki_url: str = "http://10.10.10.5:11434"
    loki_model: str = "llama3"
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
        extra = "ignore"


# Global settings instance
settings = Settings()

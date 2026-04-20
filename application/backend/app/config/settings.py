"""
AdviceRoom — Configuration (pydantic-settings).

Charge les variables d'environnement depuis le .env.
Chaque setting est documenté et typé.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration AdviceRoom, chargée depuis les variables d'environnement."""

    # --- General ---
    version: str = "0.1.0"
    log_level: str = "INFO"

    # --- Backend ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # --- LLMaaS (Cloud Temple SecNumCloud) ---
    llmaas_api_url: str = "https://api.ai.cloud-temple.com"
    llmaas_api_key: str = ""
    llmaas_default_model: str = "gpt-oss:120b"

    # --- Google Gemini ---
    google_api_key: str = ""
    google_default_model: str = "gemini-3.1-pro-preview"

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_api_url: str = "https://api.openai.com/v1"
    openai_default_model: str = "gpt-5.2"

    # --- Anthropic ---
    anthropic_api_key: str = ""
    anthropic_api_url: str = "https://api.anthropic.com"
    anthropic_default_model: str = "claude-opus-4.6"

    # --- S3 Storage ---
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "adviceroom"
    s3_region: str = "fr1"

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"

    # --- Auth ---
    auth_service_url: str = "http://auth:8001"
    jwt_public_key_url: str = "http://auth:8001/.well-known/jwks.json"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Singleton des settings (cached)."""
    return Settings()

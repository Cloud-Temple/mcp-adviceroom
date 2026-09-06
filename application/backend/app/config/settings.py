"""
AdviceRoom — Configuration (pydantic-settings).

Charge les variables d'environnement depuis le .env.
Chaque setting est documenté et typé.
"""
import hmac
from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration AdviceRoom, chargée depuis les variables d'environnement."""

    # --- General ---
    version: str = "0.1.0"
    log_level: str = "INFO"

    # --- Backend / MCP Server ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # --- Auth (pattern Cloud Temple) ---
    # Défaut VIDE et non "changeme-in-production" : une valeur par défaut connue
    # publiquement (le dépôt est open source) donnait un accès admin total à
    # tout déploiement ayant oublié de définir la variable.
    #
    # Vide = bootstrap DÉSACTIVÉ (fail-closed). L'accès admin passe alors
    # uniquement par les tokens du Token Store S3. Toute comparaison doit passer
    # par bootstrap_key_matches(), qui refuse une clé vide — sans quoi
    # hmac.compare_digest("", "") authentifierait un porteur sans secret.
    admin_bootstrap_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ADMIN_BOOTSTRAP_KEY",
            "ADVICEROOM_BOOTSTRAP_KEY",
        ),
    )

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
    openai_default_model: str = "gpt-5.4"

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

    # --- MCP Tools (outils disponibles pour les LLMs pendant le débat) ---
    mcp_tools_url: str = ""
    mcp_tools_token: str = ""

    # --- Auth ---
    auth_service_url: str = "http://auth:8001"
    jwt_public_key_url: str = "http://auth:8001/.well-known/jwks.json"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    @property
    def bootstrap_enabled(self) -> bool:
        """True si une clé de bootstrap admin est configurée."""
        return bool(self.admin_bootstrap_key)

    def bootstrap_key_matches(self, token: str) -> bool:
        """
        Compare un token à la clé de bootstrap admin, en temps constant.

        Point unique de comparaison : toute vérification du bootstrap doit
        passer par ici. Un token vide ou une clé non configurée renvoient False
        AVANT tout appel à compare_digest — car compare_digest("", "") est vrai
        et accorderait sinon un accès admin total sans aucun secret.
        """
        if not token or not self.admin_bootstrap_key:
            return False
        return hmac.compare_digest(token, self.admin_bootstrap_key)


@lru_cache()
def get_settings() -> Settings:
    """Singleton des settings (cached)."""
    return Settings()

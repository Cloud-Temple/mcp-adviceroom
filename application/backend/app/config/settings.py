"""
AdviceRoom — Configuration (pydantic-settings).

Charge les variables d'environnement depuis le .env.
Chaque setting est documenté et typé.
"""
import hmac
from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field, SecretStr
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
    admin_bootstrap_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "ADMIN_BOOTSTRAP_KEY",
            "ADVICEROOM_BOOTSTRAP_KEY",
        ),
    )

    # ------------------------------------------------------------------
    # SECRETS — HIGH #3 de l'audit du 24/08/2026
    #
    # Typés SecretStr : en `str` nu, `repr(settings)` les imprimait EN CLAIR.
    # Une trace d'exception, un log de debug ou un dump de configuration
    # suffisait donc à les exposer. SecretStr affiche `**********` et impose
    # `.get_secret_value()` pour lire la valeur — ce qui rend chaque lecture
    # d'un secret visible à la relecture du code.
    #
    # Portée : cela protège le repr des settings, PAS l'environnement du
    # processus. Les providers LLM lisent d'ailleurs encore leurs clés via
    # os.getenv() (voir services/llm/*.py) : un dump d'environnement resterait
    # une fuite. C'est une atténuation, pas une élimination.
    # ------------------------------------------------------------------

    # --- LLMaaS (Cloud Temple SecNumCloud) ---
    llmaas_api_url: str = "https://api.ai.cloud-temple.com"
    llmaas_api_key: SecretStr = SecretStr("")
    llmaas_default_model: str = "gpt-oss:120b"

    # --- Google Gemini ---
    google_api_key: SecretStr = SecretStr("")
    google_default_model: str = "gemini-3.1-pro-preview"

    # --- OpenAI ---
    openai_api_key: SecretStr = SecretStr("")
    openai_api_url: str = "https://api.openai.com/v1"
    openai_default_model: str = "gpt-5.4"

    # --- Anthropic ---
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_api_url: str = "https://api.anthropic.com"
    anthropic_default_model: str = "claude-opus-4.6"

    # --- S3 Storage ---
    s3_endpoint: str = ""
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_bucket: str = "adviceroom"
    s3_region: str = "fr1"

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"

    # --- Rate limiting (HIGH #2 et #5, audit du 24/08/2026) ---
    # Un débat mobilise jusqu'à 5 LLMs plus un synthétiseur : sans plafond, un
    # porteur de token valide peut épuiser le budget LLM. Les valeurs par défaut
    # visent un usage humain confortable tout en bornant l'abus.
    # Mettre 0 désactive la garde correspondante (déconseillé en production).
    rate_limit_debates_per_minute: int = 10   # créations de débats / min / client
    rate_limit_max_active_debates: int = 5    # débats simultanés / client
    rate_limit_tokens_per_minute: int = 10    # créations de tokens admin / min

    # --- MCP Tools (outils disponibles pour les LLMs pendant le débat) ---
    mcp_tools_url: str = ""
    mcp_tools_token: SecretStr = SecretStr("")

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
        return bool(self.admin_bootstrap_key.get_secret_value())

    def bootstrap_key_matches(self, token: str) -> bool:
        """
        Compare un token à la clé de bootstrap admin, en temps constant.

        Point unique de comparaison : toute vérification du bootstrap doit
        passer par ici. Un token vide ou une clé non configurée renvoient False
        AVANT tout appel à compare_digest — car compare_digest("", "") est vrai
        et accorderait sinon un accès admin total sans aucun secret.
        """
        key = self.admin_bootstrap_key.get_secret_value()
        if not token or not key:
            return False
        return hmac.compare_digest(token, key)


@lru_cache()
def get_settings() -> Settings:
    """Singleton des settings (cached)."""
    return Settings()

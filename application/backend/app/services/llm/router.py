"""
LLM Router — Routeur multi-provider pour les appels LLM.

Résout la catégorie utilisateur (externe/snc) en un modèle + provider
concret, puis dispatch l'appel au bon adapter.

Pipeline :
1. Charger le registre de modèles (llm_models.yaml)
2. Résoudre catégorie → modèle par défaut
3. Instancier le provider (GoogleProvider ou LLMaaSProvider)
4. Appeler chat_completion / chat_completion_stream
5. Retourner un LLMResponse / LLMStreamChunk normalisé

Usage :
    router = get_llm_router()
    response = await router.chat_completion(
        messages=[...], tools=[...], llm_category="snc"
    )
"""
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import yaml

from .base import (
    BaseLLMProvider,
    LLMResponse,
    LLMStreamChunk,
    ModelConfig,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LLMRouter",
    "get_llm_router",
    "init_llm_router",
]

# Chemin par défaut de la config
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm_models.yaml"


class LLMRouter:
    """
    Routeur LLM multi-provider.

    Charge le registre de modèles depuis YAML, instancie les providers,
    et route les appels vers le bon provider selon la catégorie.

    Singleton accessible via get_llm_router().
    """

    def __init__(self):
        self.models: Dict[str, ModelConfig] = {}
        self.categories: Dict[str, dict] = {}
        self.default_category: str = "externe"
        self._providers: Dict[str, BaseLLMProvider] = {}
        self._loaded = False

    def load(self, config_path: Optional[Path] = None) -> None:
        """
        Charge le registre de modèles depuis le fichier YAML.

        Args:
            config_path: Chemin vers llm_models.yaml.
        """
        path = config_path or _CONFIG_PATH
        if not path.exists():
            logger.error(f"✗ Config LLM non trouvée : {path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Catégorie par défaut
        self.default_category = config.get("default_category", "externe")

        # Catégories
        self.categories = config.get("categories", {})

        # Modèles
        self.models = {}
        for model_id, model_cfg in config.get("models", {}).items():
            self.models[model_id] = ModelConfig(
                id=model_id,
                display_name=model_cfg.get("display_name", model_id),
                provider=model_cfg.get("provider", "llmaas"),
                category=model_cfg.get("category", "snc"),
                api_model_id=model_cfg.get("api_model_id", model_id),
                capabilities=model_cfg.get("capabilities", []),
                context_window=model_cfg.get("context_window", 128000),
                default=model_cfg.get("default", False),
                active=model_cfg.get("active", True),
            )

        # Instancier les providers
        self._init_providers()

        self._loaded = True
        active_count = sum(1 for m in self.models.values() if m.active)
        logger.info(
            f"✓ LLM Router chargé : {active_count} modèles actifs, "
            f"{len(self.categories)} catégories, "
            f"{len(self._providers)} providers, "
            f"défaut={self.default_category}"
        )

    def _init_providers(self) -> None:
        """Instancie les providers nécessaires selon les modèles configurés."""
        provider_types = {m.provider for m in self.models.values() if m.active}

        for ptype in provider_types:
            if ptype == "google":
                from .google import GoogleProvider
                self._providers["google"] = GoogleProvider()
                logger.info("  ✓ GoogleProvider initialisé")
            elif ptype == "llmaas":
                from .llmaas import LLMaaSProvider
                self._providers["llmaas"] = LLMaaSProvider()
                logger.info("  ✓ LLMaaSProvider initialisé")
            elif ptype == "openai":
                from .openai import OpenAIProvider
                self._providers["openai"] = OpenAIProvider()
                logger.info("  ✓ OpenAIProvider initialisé")
            elif ptype == "anthropic":
                from .anthropic import AnthropicProvider
                self._providers["anthropic"] = AnthropicProvider()
                logger.info("  ✓ AnthropicProvider initialisé")

    @property
    def loaded(self) -> bool:
        return self._loaded

    # ─── Résolution de modèle ───────────────────────────────

    def get_default_model(self, category: str) -> Optional[ModelConfig]:
        """
        Retourne le modèle par défaut d'une catégorie.

        Args:
            category: "externe" ou "snc"

        Returns:
            ModelConfig du modèle par défaut, ou None.
        """
        # Chercher le modèle default=True de la catégorie
        for model in self.models.values():
            if model.category == category and model.default and model.active:
                return model

        # Fallback : premier modèle actif de la catégorie
        for model in self.models.values():
            if model.category == category and model.active:
                return model

        # Fallback ultime : premier modèle actif
        for model in self.models.values():
            if model.active:
                logger.warning(
                    f"⚠ Aucun modèle actif pour catégorie '{category}' — "
                    f"fallback vers '{model.id}'"
                )
                return model

        return None

    def set_default_model(self, category: str, model_id: str) -> bool:
        """Change le modèle par défaut pour une catégorie (runtime, en mémoire).

        Args:
            category: "externe" ou "snc"
            model_id: ID du modèle à définir comme défaut

        Returns:
            True si le changement a réussi.
        """
        target = self.models.get(model_id)
        if not target or target.category != category or not target.active:
            return False

        # Reset tous les defaults de cette catégorie, activer le nouveau
        for model in self.models.values():
            if model.category == category:
                model.default = (model.id == model_id)

        logger.info(f"✓ Modèle par défaut changé : {category} → {model_id}")
        return True

    def get_provider(self, provider_name: str) -> Optional[BaseLLMProvider]:
        """Retourne l'instance du provider."""
        return self._providers.get(provider_name)

    def get_model_by_id(self, model_id: str) -> Optional[ModelConfig]:
        """Retourne un modèle par son ID."""
        return self.models.get(model_id)

    # ─── Chat completion ────────────────────────────────────

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        llm_category: str = "externe",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """
        Chat completion via le provider résolu depuis la catégorie.

        Args:
            messages: Messages au format OpenAI.
            tools: Tool definitions au format OpenAI.
            llm_category: "externe" ou "snc".
            temperature: Température de génération.
            max_tokens: Limite de tokens en sortie.

        Returns:
            LLMResponse normalisée.
        """
        model = self.get_default_model(llm_category)
        if not model:
            return LLMResponse(
                content=f"Aucun modèle disponible pour la catégorie '{llm_category}'.",
                finish_reason="error",
                provider="none",
            )

        provider = self.get_provider(model.provider)
        if not provider:
            return LLMResponse(
                content=f"Provider '{model.provider}' non initialisé.",
                finish_reason="error",
                model=model.api_model_id,
                provider=model.provider,
            )

        logger.info(
            f"🔀 LLM Router [{llm_category}] → {model.display_name} "
            f"({model.provider}/{model.api_model_id})"
        )

        return await provider.chat_completion(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            model_override=model.api_model_id,
        )

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        llm_category: str = "externe",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        Chat completion streaming via le provider résolu.

        Yields:
            LLMStreamChunk normalisés.
        """
        model = self.get_default_model(llm_category)
        if not model:
            yield LLMStreamChunk(
                delta_content=f"Aucun modèle disponible pour '{llm_category}'.",
                finish_reason="error",
                provider="none",
            )
            return

        provider = self.get_provider(model.provider)
        if not provider:
            yield LLMStreamChunk(
                delta_content=f"Provider '{model.provider}' non initialisé.",
                finish_reason="error",
                model=model.api_model_id,
                provider=model.provider,
            )
            return

        logger.info(
            f"🔀 LLM Router stream [{llm_category}] → {model.display_name} "
            f"({model.provider}/{model.api_model_id})"
        )

        async for chunk in provider.chat_completion_stream(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            model_override=model.api_model_id,
        ):
            yield chunk

    # ─── API publique (pour endpoints) ──────────────────────

    def get_models_by_category(self) -> Dict[str, Any]:
        """
        Retourne les modèles groupés par catégorie (pour GET /api/v1/llm/models).
        """
        result = {}
        for cat_id, cat_cfg in self.categories.items():
            cat_models = [
                {
                    "id": m.id,
                    "display_name": m.display_name,
                    "provider": m.provider,
                    "capabilities": m.capabilities,
                    "context_window": m.context_window,
                    "default": m.default,
                }
                for m in self.models.values()
                if m.category == cat_id and m.active
            ]
            result[cat_id] = {
                **cat_cfg,
                "models": cat_models,
            }

        return {
            "categories": result,
            "default_category": self.default_category,
        }

    def get_status(self) -> Dict[str, Any]:
        """Retourne le statut du routeur (pour endpoint admin)."""
        return {
            "loaded": self._loaded,
            "default_category": self.default_category,
            "categories": list(self.categories.keys()),
            "models_total": len(self.models),
            "models_active": sum(1 for m in self.models.values() if m.active),
            "providers": list(self._providers.keys()),
        }


# ============================================================
# Singleton
# ============================================================

_router_instance: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """
    Récupère l'instance singleton du LLM Router.

    Crée une instance non-chargée si elle n'existe pas.
    L'initialisation se fait via init_llm_router().
    """
    global _router_instance
    if _router_instance is None:
        _router_instance = LLMRouter()
    return _router_instance


def init_llm_router(config_path: Optional[Path] = None) -> LLMRouter:
    """
    Initialise le LLM Router (appelé par init_app.py au démarrage).

    Args:
        config_path: Chemin vers llm_models.yaml (optionnel).

    Returns:
        Instance initialisée du LLMRouter.
    """
    global _router_instance
    _router_instance = LLMRouter()
    _router_instance.load(config_path)
    return _router_instance

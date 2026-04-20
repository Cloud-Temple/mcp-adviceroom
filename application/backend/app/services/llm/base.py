"""
BaseLLMProvider — Interface commune pour tous les providers LLM.

Format interne normalisé = OpenAI :
- Messages : [{"role": "...", "content": "..."}]
- Tools : [{"type": "function", "function": {...}}]
- Réponses : LLMResponse (dataclass normalisée)
- Streaming : AsyncGenerator[LLMStreamChunk]

Chaque provider traduit depuis/vers ce format si nécessaire :
- LLMaaSProvider : pass-through (déjà OpenAI-compatible)
- GoogleProvider : traduction bidirectionnelle Google ↔ OpenAI
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "BaseLLMProvider",
    "LLMResponse",
    "LLMStreamChunk",
    "ModelConfig",
]


# ============================================================
# Dataclasses normalisées
# ============================================================

@dataclass
class LLMResponse:
    """
    Réponse normalisée d'un provider LLM.

    Tous les champs sont au format OpenAI pour cohérence interne.
    """
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: str = "stop"
    model: str = ""
    provider: str = ""
    usage: Optional[Dict[str, int]] = None  # {prompt_tokens, completion_tokens, total_tokens}

    @property
    def has_tool_calls(self) -> bool:
        """True si la réponse contient des appels d'outils."""
        return bool(self.tool_calls)


@dataclass
class LLMStreamChunk:
    """
    Chunk de streaming normalisé.

    delta_content et delta_tool_calls sont mutuellement exclusifs
    dans la pratique (un chunk contient l'un ou l'autre).
    """
    delta_content: Optional[str] = None
    delta_tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None  # Non-None = dernier chunk
    model: str = ""
    provider: str = ""


@dataclass
class ModelConfig:
    """
    Configuration d'un modèle chargée depuis llm_models.yaml.

    Représente un modèle spécifique (pas une catégorie).
    """
    id: str                              # Clé YAML (ex: "gemini-3.1-pro")
    display_name: str                    # Nom affiché (ex: "Gemini 3.1 Pro")
    provider: str                        # "google" ou "llmaas"
    category: str                        # "externe" ou "snc"
    api_model_id: str                    # ID API exact (ex: "gemini-3.1-pro-preview")
    capabilities: List[str] = field(default_factory=list)  # [chat, tools, vision, streaming]
    context_window: int = 128000
    default: bool = False                # Modèle par défaut de la catégorie
    active: bool = True                  # Désactivable par l'admin

    @property
    def supports_tools(self) -> bool:
        return "tools" in self.capabilities

    @property
    def supports_vision(self) -> bool:
        return "vision" in self.capabilities

    @property
    def supports_streaming(self) -> bool:
        return "streaming" in self.capabilities


# ============================================================
# Interface commune
# ============================================================

class BaseLLMProvider(ABC):
    """
    Interface commune pour tous les providers LLM.

    Chaque provider implémente chat_completion et chat_completion_stream
    avec des messages et tools au format OpenAI.

    Les providers existants (gemini_service, llmaas_service) sont wrappés
    dans des adapters qui implémentent cette interface, sans modification
    du code existant.
    """

    provider_name: str = "base"

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> LLMResponse:
        """
        Chat completion non-streaming.

        Args:
            messages: Messages au format OpenAI.
            tools: Tool definitions au format OpenAI function calling.
            temperature: Température de génération (0.0-2.0).
            max_tokens: Limite de tokens en sortie.
            model_override: Force un modèle spécifique (sinon défaut du provider).

        Returns:
            LLMResponse normalisée.
        """
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        Chat completion streaming.

        Yields:
            LLMStreamChunk normalisés. Le dernier chunk a finish_reason != None.
        """
        ...
        # Nécessaire pour que Python reconnaisse le type AsyncGenerator
        yield  # type: ignore

    @abstractmethod
    async def test_connectivity(self) -> Dict[str, Any]:
        """
        Teste la connectivité au provider.

        Returns:
            {"status": "ok"/"error", "details": ...}
        """
        ...

    def get_capabilities(self) -> Dict[str, bool]:
        """Retourne les capabilities du provider."""
        return {
            "tools": True,
            "vision": True,
            "streaming": True,
        }

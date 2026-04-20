"""
LLM Package — Providers et routeur multi-provider.

Composants :
- base.py : BaseLLMProvider, LLMResponse, LLMStreamChunk, ModelConfig
- llmaas.py : LLMaaSProvider (Cloud Temple SecNumCloud)
- google.py : GoogleProvider (Google Gemini)
- openai.py : OpenAIProvider (à créer)
- anthropic.py : AnthropicProvider (à créer)
- router.py : LLMRouter (routage par catégorie)
"""
from .base import BaseLLMProvider, LLMResponse, LLMStreamChunk, ModelConfig
from .router import LLMRouter, get_llm_router, init_llm_router

__all__ = [
    "BaseLLMProvider",
    "LLMResponse",
    "LLMStreamChunk",
    "ModelConfig",
    "LLMRouter",
    "get_llm_router",
    "init_llm_router",
]

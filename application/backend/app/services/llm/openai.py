"""
OpenAI Provider — Adapter pour l'API OpenAI.

OpenAI est le format natif interne d'AdviceRoom → quasi pass-through
(comme LLMaaSProvider). Les messages, tools et réponses sont déjà au
bon format.

Modèles supportés :
- gpt-5.2 (chat principal, tool calling)

Ref: DESIGN/architecture.md §5
"""
import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from .base import BaseLLMProvider, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)

__all__ = ["OpenAIProvider"]


class OpenAIProvider(BaseLLMProvider):
    """
    Adapter OpenAI API.

    Quasi pass-through : l'API OpenAI EST le format interne d'AdviceRoom.
    Les messages, tools et réponses n'ont pas besoin de traduction.

    Utilise httpx directement pour le contrôle fin du streaming.
    """

    provider_name = "openai"

    def __init__(self) -> None:
        """Initialise le provider avec les env vars."""
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv(
            "OPENAI_API_URL", "https://api.openai.com/v1"
        ).rstrip("/")
        self.default_model = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5.2")

    def _headers(self) -> Dict[str, str]:
        """Headers d'authentification OpenAI."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ─── Chat completion (non-streaming) ─────────────────────

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> LLMResponse:
        """
        Chat completion non-streaming via OpenAI.

        Pass-through : messages et tools sont déjà au format OpenAI.
        """
        model = model_override or self.default_model

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if max_tokens:
            # GPT-5+ utilise max_completion_tokens au lieu de max_tokens
            payload["max_completion_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            # Parser la réponse OpenAI standard
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            usage = data.get("usage")

            return LLMResponse(
                content=message.get("content"),
                tool_calls=message.get("tool_calls"),
                finish_reason=choice.get("finish_reason", "stop"),
                model=data.get("model", model),
                provider=self.provider_name,
                usage=usage,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"✗ OpenAI HTTP {e.response.status_code}: {e.response.text[:200]}")
            return LLMResponse(
                content=f"Erreur OpenAI : HTTP {e.response.status_code}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )
        except Exception as e:
            logger.error(f"✗ OpenAI erreur : {e}")
            return LLMResponse(
                content="Erreur temporaire du provider OpenAI",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )

    # ─── Chat completion (streaming) ─────────────────────────

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        Chat completion streaming via OpenAI.

        OpenAI envoie des chunks SSE au format standard :
        data: {"choices": [{"delta": {"content": "..."}}]}
        """
        model = model_override or self.default_model

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if max_tokens:
            # GPT-5+ utilise max_completion_tokens au lieu de max_tokens
            payload["max_completion_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        data_str = line[6:]  # Strip "data: "
                        if data_str.strip() == "[DONE]":
                            yield LLMStreamChunk(
                                finish_reason="stop",
                                model=model,
                                provider=self.provider_name,
                            )
                            return

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choice = data.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        finish = choice.get("finish_reason")

                        yield LLMStreamChunk(
                            delta_content=delta.get("content"),
                            delta_tool_calls=delta.get("tool_calls"),
                            finish_reason=finish,
                            model=data.get("model", model),
                            provider=self.provider_name,
                        )

                        if finish:
                            return

        except httpx.HTTPStatusError as e:
            logger.error(f"✗ OpenAI stream HTTP {e.response.status_code}")
            yield LLMStreamChunk(
                delta_content=f"Erreur OpenAI streaming : HTTP {e.response.status_code}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )
        except Exception as e:
            logger.error(f"✗ OpenAI stream erreur : {e}")
            yield LLMStreamChunk(
                delta_content="Erreur temporaire du provider OpenAI (streaming)",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )

    # ─── Connectivité ────────────────────────────────────────

    async def test_connectivity(self) -> Dict[str, Any]:
        """Teste la connectivité à OpenAI."""
        if not self.api_key:
            return {"status": "disabled", "details": "OPENAI_API_KEY non configurée"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                models = [m.get("id", "?") for m in data.get("data", [])]
                return {"status": "ok", "models_count": len(models)}
        except Exception as e:
            logger.error(f"✗ Erreur connectivité OpenAI: {e}")
            return {"status": "error", "details": "Erreur de connectivité OpenAI"}

    def get_capabilities(self) -> Dict[str, bool]:
        """Capabilities du provider OpenAI."""
        return {
            "tools": True,
            "vision": True,
            "streaming": True,
        }

"""
LLMaaS Provider — Adapter Cloud Temple LLMaaS (SecNumCloud).

LLMaaS est déjà OpenAI-compatible → cet adapter est quasi pass-through.
Il wrappe le singleton llmaas_service existant sans le modifier.

Modèles supportés :
- gpt-oss:120b (chat principal SNC, tool calling)
- Qwen/Qwen3.5-35B-A3B-GPTQ-Int4 (vision)
- Qwen/Qwen3.5-122B-A10B-GPTQ-Int4 (gros modèle)
- Qwen/Qwen3.5-27B-GPTQ-Int4 (rapide)
"""
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from .base import BaseLLMProvider, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)

__all__ = ["LLMaaSProvider"]


class LLMaaSProvider(BaseLLMProvider):
    """
    Adapter LLMaaS (Cloud Temple SecNumCloud).

    Quasi pass-through : LLMaaS expose une API OpenAI-compatible.
    Les messages, tools et réponses sont déjà au bon format.

    Utilise directement httpx au lieu de wrapper llmaas_service.py
    pour avoir un contrôle fin sur le streaming et les tool_calls.
    """

    provider_name = "llmaas"

    def __init__(self):
        """Initialise le provider avec les env vars."""
        import os
        self.api_key = os.getenv("LLMAAS_API_KEY", os.getenv("LLM_API_KEY", ""))
        self.base_url = os.getenv(
            "LLMAAS_API_URL",
            os.getenv("LLM_API_URL", "https://api.ai.cloud-temple.com"),
        ).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        """Headers d'authentification LLMaaS."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ─── Chat completion (non-streaming) ────────────────────

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> LLMResponse:
        """
        Chat completion non-streaming via LLMaaS.

        Pass-through : les messages et tools sont déjà au format OpenAI.
        """
        model = model_override or "gpt-oss:120b"

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
            payload["max_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
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
            logger.error(f"✗ LLMaaS HTTP {e.response.status_code}: {e.response.text[:200]}")
            return LLMResponse(
                content=f"Erreur LLMaaS : HTTP {e.response.status_code}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )
        except Exception as e:
            logger.error(f"✗ LLMaaS erreur : {e}")
            return LLMResponse(
                content=f"Erreur LLMaaS : {str(e)}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )

    # ─── Chat completion (streaming) ────────────────────────

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        Chat completion streaming via LLMaaS.

        LLMaaS envoie des chunks SSE au format OpenAI standard :
        data: {"choices": [{"delta": {"content": "..."}}]}
        """
        model = model_override or "gpt-oss:120b"

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
            payload["max_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        data_str = line[6:]  # Strip "data: " prefix
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
            logger.error(f"✗ LLMaaS stream HTTP {e.response.status_code}")
            yield LLMStreamChunk(
                delta_content=f"Erreur LLMaaS streaming : HTTP {e.response.status_code}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )
        except Exception as e:
            logger.error(f"✗ LLMaaS stream erreur : {e}")
            yield LLMStreamChunk(
                delta_content=f"Erreur LLMaaS streaming : {str(e)}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )

    # ─── Connectivité ───────────────────────────────────────

    async def test_connectivity(self) -> Dict[str, Any]:
        """Teste la connectivité à LLMaaS."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                models = [m.get("id", "?") for m in data.get("data", [])]
                return {"status": "ok", "models": models}
        except Exception as e:
            return {"status": "error", "details": str(e)}

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "tools": True,
            "vision": True,  # qwen3.5:27b supporte la vision
            "streaming": True,
        }

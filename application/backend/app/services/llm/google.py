"""
Google Provider — Adapter Google Gemini.

Traduit entre le format interne OpenAI et le format natif Google Gemini.
Wrappe le singleton gemini_service existant pour les cas complexes,
et utilise httpx directement pour les appels normalisés.

Traductions :
- Messages OpenAI → Google contents[] (system → system_instruction)
- Tools OpenAI → Google functionDeclarations
- Réponse Google → LLMResponse (format OpenAI)
- Streaming Google → LLMStreamChunk

Modèles supportés :
- gemini-3.1-pro-preview (chat principal)
- gemini-3.1-flash-preview (chat rapide)
"""
import json
import logging
import os
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from .base import BaseLLMProvider, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)

__all__ = ["GoogleProvider"]

# Base URL de l'API Google Gemini
_GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GoogleProvider(BaseLLMProvider):
    """
    Adapter Google Gemini API.

    Responsabilité principale : traduction bidirectionnelle entre
    le format OpenAI (standard interne) et le format Google natif.

    L'API Google utilise un format différent pour :
    - system → system_instruction (séparé des contents)
    - tool_calls → functionCall (dans les parts du modèle)
    - tool_results → functionResponse (dans les parts de l'utilisateur)
    - tools → functionDeclarations (sous tools[].functionDeclarations)
    """

    provider_name = "google"

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.default_model = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")

    def _url(self, model: str, method: str) -> str:
        """Construit l'URL API Google Gemini."""
        return (
            f"{_GOOGLE_API_BASE}/models/{model}:{method}"
            f"?key={self.api_key}"
        )

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json"}

    # ============================================================
    # Traduction OpenAI → Google
    # ============================================================

    @staticmethod
    def _openai_messages_to_google(
        messages: List[Dict[str, Any]],
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """
        Traduit les messages OpenAI en format Google.

        Returns:
            (system_instruction, contents[])

        Mapping :
        - role "system"    → system_instruction (extrait, pas dans contents)
        - role "user"      → role "user", parts [{"text": ...}]
        - role "assistant" → role "model", parts [{"text": ...}] ou [{"functionCall": ...}]
        - role "tool"      → role "user", parts [{"functionResponse": ...}]
        """
        system_text = None
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content")

            if role == "system":
                # System → extrait comme system_instruction
                system_text = content
                continue

            if role == "user":
                parts = []
                if isinstance(content, str):
                    parts.append({"text": content})
                elif isinstance(content, list):
                    # Multi-modal (texte + images)
                    for item in content:
                        if item.get("type") == "text":
                            parts.append({"text": item["text"]})
                        elif item.get("type") == "image_url":
                            # Google accepte les images inline en base64
                            url = item.get("image_url", {}).get("url", "")
                            if url.startswith("data:"):
                                # data:image/png;base64,xxxx
                                mime_end = url.index(";")
                                mime = url[5:mime_end]
                                b64 = url[url.index(",") + 1:]
                                parts.append({
                                    "inline_data": {
                                        "mime_type": mime,
                                        "data": b64,
                                    }
                                })
                contents.append({"role": "user", "parts": parts})

            elif role == "assistant":
                parts = []
                # Texte
                if content:
                    parts.append({"text": content})
                # Tool calls
                tool_calls = msg.get("tool_calls", [])
                for tc in tool_calls:
                    # Gemini 3.x : réutiliser le part brut original (avec thought_signature)
                    # pour éviter les 400 "missing thought_signature"
                    raw_part = tc.get("_google_raw_part")
                    if raw_part and "functionCall" in raw_part:
                        parts.append(raw_part)
                    else:
                        # Fallback : reconstruire le functionCall (sans thought_signature)
                        fn = tc.get("function", {})
                        try:
                            args = json.loads(fn.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            args = {}
                        parts.append({
                            "functionCall": {
                                "name": fn.get("name", ""),
                                "args": args,
                            }
                        })
                # Google requiert au moins un part — si seulement des functionCall
                # sans texte, ajouter un text vide pour éviter les 400
                if not parts:
                    parts.append({"text": ""})
                contents.append({"role": "model", "parts": parts})

            elif role == "tool":
                # Tool result → functionResponse
                tool_call_id = msg.get("tool_call_id", "")
                # Trouver le nom de la fonction à partir du tool_call_id
                # On cherche dans les messages précédents
                fn_name = msg.get("name", "")
                if not fn_name:
                    # Fallback : chercher dans l'historique
                    for prev in messages:
                        for tc in prev.get("tool_calls", []):
                            if tc.get("id") == tool_call_id:
                                fn_name = tc.get("function", {}).get("name", "unknown")
                                break

                try:
                    result_data = json.loads(content) if isinstance(content, str) else content
                except (json.JSONDecodeError, TypeError):
                    result_data = {"result": content}

                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": fn_name,
                            "response": result_data if isinstance(result_data, dict) else {"result": str(result_data)},
                        }
                    }]
                })

        return system_text, contents

    @staticmethod
    def _openai_tools_to_google(
        tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Traduit les tool definitions OpenAI en Google functionDeclarations.

        OpenAI : [{"type": "function", "function": {"name", "description", "parameters"}}]
        Google : [{"functionDeclarations": [{"name", "description", "parameters"}]}]
        """
        declarations = []
        for tool in tools:
            if tool.get("type") != "function":
                continue
            fn = tool.get("function", {})
            decl = {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
            }
            params = fn.get("parameters")
            if params:
                decl["parameters"] = params
            declarations.append(decl)

        if not declarations:
            return []
        return [{"functionDeclarations": declarations}]

    # ============================================================
    # Traduction Google → OpenAI
    # ============================================================

    @staticmethod
    def _google_response_to_openai(
        data: Dict[str, Any], model: str
    ) -> LLMResponse:
        """
        Traduit une réponse Google Gemini en LLMResponse normalisée.

        Google response :
          candidates[0].content.parts[] → peut contenir text et/ou functionCall
          candidates[0].finishReason → STOP, MAX_TOKENS, etc.
          usageMetadata → {promptTokenCount, candidatesTokenCount, totalTokenCount}
        """
        candidates = data.get("candidates", [])
        if not candidates:
            return LLMResponse(
                content="Pas de réponse du modèle.",
                finish_reason="error",
                model=model,
                provider="google",
            )

        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        finish = candidate.get("finishReason", "STOP")

        # Extraire texte et tool_calls
        text_parts = []
        tool_calls = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {})),
                    },
                })

        # Mapping finish_reason Google → OpenAI
        finish_map = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "stop",
        }
        openai_finish = finish_map.get(finish, "stop")
        if tool_calls:
            openai_finish = "tool_calls"

        # Usage
        usage_meta = data.get("usageMetadata", {})
        usage = None
        if usage_meta:
            usage = {
                "prompt_tokens": usage_meta.get("promptTokenCount", 0),
                "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
                "total_tokens": usage_meta.get("totalTokenCount", 0),
            }

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=openai_finish,
            model=model,
            provider="google",
            usage=usage,
        )

    # ============================================================
    # Chat completion (non-streaming)
    # ============================================================

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> LLMResponse:
        """Chat completion non-streaming via Google Gemini."""
        model = model_override or self.default_model

        # Traduire messages
        system_text, contents = self._openai_messages_to_google(messages)

        # Construire le payload Google
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }

        if system_text:
            payload["system_instruction"] = {"parts": [{"text": system_text}]}

        if max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens

        if tools:
            payload["tools"] = self._openai_tools_to_google(tools)
            payload["toolConfig"] = {
                "functionCallingConfig": {"mode": "AUTO"}
            }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    self._url(model, "generateContent"),
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            return self._google_response_to_openai(data, model)

        except httpx.HTTPStatusError as e:
            logger.error(f"✗ Google HTTP {e.response.status_code}: {e.response.text[:200]}")
            return LLMResponse(
                content=f"Erreur Google Gemini : HTTP {e.response.status_code}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )
        except Exception as e:
            logger.error(f"✗ Google erreur : {e}")
            return LLMResponse(
                content=f"Erreur Google Gemini : {str(e)}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )

    # ============================================================
    # Chat completion (streaming)
    # ============================================================

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        Chat completion streaming via Google Gemini.

        Google streaming : retourne des chunks JSON séparés par des lignes.
        Chaque chunk a la même structure que generateContent mais partielle.
        """
        model = model_override or self.default_model

        system_text, contents = self._openai_messages_to_google(messages)

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }

        if system_text:
            payload["system_instruction"] = {"parts": [{"text": system_text}]}

        if max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens

        if tools:
            payload["tools"] = self._openai_tools_to_google(tools)
            payload["toolConfig"] = {
                "functionCallingConfig": {"mode": "AUTO"}
            }

        # Compteur pour émuler le format indexé OpenAI des tool_calls
        tool_call_index = 0

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                url = self._url(model, "streamGenerateContent") + "&alt=sse"

                # Debug : log du payload pour diagnostiquer les 400
                logger.debug(
                    f"Google payload: {len(contents)} contents, "
                    f"system={'yes' if system_text else 'no'}, "
                    f"tools={len(payload.get('tools', [{}])[0].get('functionDeclarations', [])) if payload.get('tools') else 0}"
                )

                async with client.stream(
                    "POST", url,
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    # Vérifier le status AVANT de streamer
                    # (en streaming, raise_for_status ne donne pas le body)
                    if response.status_code != 200:
                        error_body = (await response.aread()).decode("utf-8", errors="replace")[:500]
                        logger.error(
                            f"✗ Google stream HTTP {response.status_code}: {error_body}"
                        )
                        yield LLMStreamChunk(
                            delta_content=f"Erreur Google streaming : HTTP {response.status_code} — {error_body[:200]}",
                            finish_reason="error",
                            model=model,
                            provider=self.provider_name,
                        )
                        return

                    has_tool_calls = False

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            yield LLMStreamChunk(
                                finish_reason="tool_calls" if has_tool_calls else "stop",
                                model=model,
                                provider=self.provider_name,
                            )
                            return

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Parser le chunk Google
                        candidates = data.get("candidates", [])
                        if not candidates:
                            continue

                        candidate = candidates[0]
                        parts = candidate.get("content", {}).get("parts", [])
                        finish = candidate.get("finishReason")

                        delta_content = None
                        delta_tool_calls = None

                        for part in parts:
                            if "text" in part:
                                delta_content = part["text"]
                            elif "functionCall" in part:
                                # Gemini envoie les functionCall complets (pas incrémentaux).
                                # On les traduit en format OpenAI delta indexé pour que
                                # llm_service.py puisse les accumuler uniformément.
                                fc = part["functionCall"]
                                has_tool_calls = True
                                tc = {
                                    "index": tool_call_index,
                                    "id": f"call_{uuid.uuid4().hex[:8]}",
                                    "type": "function",
                                    "function": {
                                        "name": fc.get("name", ""),
                                        "arguments": json.dumps(fc.get("args", {})),
                                    },
                                    # Préserver le part Google brut (avec thought_signature)
                                    # pour la re-entrance dans _openai_messages_to_google
                                    "_google_raw_part": part,
                                }
                                delta_tool_calls = [tc]
                                tool_call_index += 1

                        # Mapping finish_reason
                        openai_finish = None
                        if finish and finish != "STOP":
                            finish_map = {
                                "MAX_TOKENS": "length",
                                "SAFETY": "content_filter",
                            }
                            openai_finish = finish_map.get(finish, "stop")
                        elif finish == "STOP":
                            openai_finish = "tool_calls" if has_tool_calls else "stop"

                        yield LLMStreamChunk(
                            delta_content=delta_content,
                            delta_tool_calls=delta_tool_calls,
                            finish_reason=openai_finish,
                            model=model,
                            provider=self.provider_name,
                        )

                        if openai_finish:
                            return

        except httpx.HTTPStatusError as e:
            logger.error(f"✗ Google stream HTTP {e.response.status_code}")
            yield LLMStreamChunk(
                delta_content=f"Erreur Google streaming : HTTP {e.response.status_code}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )
        except Exception as e:
            logger.error(f"✗ Google stream erreur : {e}")
            yield LLMStreamChunk(
                delta_content=f"Erreur Google streaming : {str(e)}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )

    # ─── Connectivité ───────────────────────────────────────

    async def test_connectivity(self) -> Dict[str, Any]:
        """Teste la connectivité à Google Gemini."""
        if not self.api_key:
            return {"status": "disabled", "details": "GEMINI_API_KEY non configurée"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{_GOOGLE_API_BASE}/models?key={self.api_key}",
                )
                response.raise_for_status()
                data = response.json()
                models = [m.get("name", "?") for m in data.get("models", [])]
                return {"status": "ok", "models_count": len(models)}
        except Exception as e:
            return {"status": "error", "details": str(e)}

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "tools": True,
            "vision": True,
            "streaming": True,
        }

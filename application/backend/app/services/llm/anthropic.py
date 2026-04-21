"""
Anthropic Provider — Adapter pour l'API Claude.

Traduit entre le format interne OpenAI et le format natif Anthropic.
L'API Claude diffère d'OpenAI sur plusieurs points :
- Le system prompt est un paramètre séparé (pas un message)
- Les tool calls utilisent "tool_use" / "tool_result" content blocks
- Le streaming utilise des event types différents

Modèles supportés :
- claude-opus-4.6 (chat principal, tool calling)

Ref: DESIGN/architecture.md §5
"""
import json
import logging
import os
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from .base import BaseLLMProvider, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)

__all__ = ["AnthropicProvider"]

_ANTHROPIC_API_BASE = "https://api.anthropic.com"
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(BaseLLMProvider):
    """
    Adapter Anthropic Claude API.

    Traduction bidirectionnelle entre le format OpenAI (interne)
    et le format Anthropic natif :
    - Messages : system extrait → paramètre séparé
    - Tools : function calling → tool_use content blocks
    - Réponses : content blocks → LLMResponse normalisée
    """

    provider_name = "anthropic"

    def __init__(self) -> None:
        """Initialise le provider avec les env vars."""
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.base_url = os.getenv(
            "ANTHROPIC_API_URL", _ANTHROPIC_API_BASE
        ).rstrip("/")
        self.default_model = os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-opus-4.6")
        self._default_max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "64000"))

    def _headers(self) -> Dict[str, str]:
        """Headers d'authentification Anthropic."""
        return {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    # ============================================================
    # Traduction OpenAI → Anthropic
    # ============================================================

    @staticmethod
    def _openai_messages_to_anthropic(
        messages: List[Dict[str, Any]],
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """
        Traduit les messages OpenAI en format Anthropic.

        Returns:
            (system_prompt, messages[]) — system extrait séparément.

        Mapping :
        - role "system"    → system_prompt (paramètre séparé)
        - role "user"      → role "user"
        - role "assistant" → role "assistant"
        - role "tool"      → role "user" avec tool_result content block

        IMPORTANT : L'API Anthropic exige une alternance stricte user/assistant.
        Les messages consécutifs de même rôle sont fusionnés automatiquement.
        C'est critique pour les tool results (role "tool" → "user") qui suivent
        d'autres messages "user" ou d'autres "tool" results.
        """
        system_text = None
        raw_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                # System → paramètre séparé (pas dans les messages)
                system_text = content
                continue

            if role == "user":
                raw_messages.append({"role": "user", "content": content})

            elif role == "assistant":
                # Assistant avec tool_calls → content blocks
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})

                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:8]}"),
                        "name": fn.get("name", ""),
                        "input": args,
                    })

                if not blocks:
                    blocks.append({"type": "text", "text": ""})
                raw_messages.append({"role": "assistant", "content": blocks})

            elif role == "tool":
                # Tool result → user message avec tool_result block
                raw_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content,
                    }],
                })

        # ────────────────────────────────────────────────────────────
        # Fusion des messages consécutifs de même rôle
        # L'API Anthropic EXIGE une alternance stricte user/assistant.
        # Sans cette fusion, les tool results (convertis en "user")
        # créent des messages user consécutifs → Opus retourne content=[].
        # ────────────────────────────────────────────────────────────
        anthropic_messages = []
        for msg in raw_messages:
            if anthropic_messages and anthropic_messages[-1]["role"] == msg["role"]:
                # Fusionner avec le message précédent de même rôle
                prev = anthropic_messages[-1]
                prev_content = prev["content"]
                curr_content = msg["content"]

                # Normaliser en liste de content blocks pour la fusion
                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{"type": "text", "text": curr_content}]

                prev["content"] = prev_content + curr_content
            else:
                anthropic_messages.append(msg)

        return system_text, anthropic_messages

    @staticmethod
    def _openai_tools_to_anthropic(
        tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Traduit les tool definitions OpenAI en format Anthropic.

        OpenAI : [{"type": "function", "function": {"name", "description", "parameters"}}]
        Anthropic : [{"name", "description", "input_schema"}]
        """
        result = []
        for tool in tools:
            if tool.get("type") != "function":
                continue
            fn = tool.get("function", {})
            result.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    # ============================================================
    # Traduction Anthropic → OpenAI
    # ============================================================

    @staticmethod
    def _anthropic_response_to_openai(
        data: Dict[str, Any], model: str
    ) -> LLMResponse:
        """
        Traduit une réponse Anthropic en LLMResponse normalisée.

        Anthropic response :
          content[] → peut contenir text et/ou tool_use blocks
          stop_reason → end_turn, tool_use, max_tokens
          usage → {input_tokens, output_tokens}
        """
        content_blocks = data.get("content", [])
        stop_reason = data.get("stop_reason", "end_turn")

        text_parts = []
        tool_calls = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "thinking":
                # Claude extended thinking — inclure le contenu pensé
                thinking_text = block.get("thinking", "")
                if thinking_text:
                    text_parts.append(thinking_text)
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        # Mapping stop_reason Anthropic → finish_reason OpenAI
        finish_map = {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
            "stop_sequence": "stop",
        }
        finish_reason = finish_map.get(stop_reason, "stop")
        if tool_calls:
            finish_reason = "tool_calls"

        # Usage
        usage_data = data.get("usage", {})
        usage = {
            "prompt_tokens": usage_data.get("input_tokens", 0),
            "completion_tokens": usage_data.get("output_tokens", 0),
            "total_tokens": (
                usage_data.get("input_tokens", 0)
                + usage_data.get("output_tokens", 0)
            ),
        }

        # Diagnostic : si aucun texte extrait malgré des tokens → log les block types
        if not text_parts and not tool_calls:
            block_types = [b.get("type", "?") for b in content_blocks]
            logger.warning(
                f"⚠ Anthropic réponse sans texte ni tools — "
                f"stop_reason={stop_reason}, "
                f"block_types={block_types}, "
                f"usage={usage}, "
                f"content_blocks_count={len(content_blocks)}"
            )

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=finish_reason,
            model=data.get("model", model),
            provider="anthropic",
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
        """Chat completion non-streaming via Anthropic Claude."""
        model = model_override or self.default_model

        # Traduire messages
        system_text, anthropic_msgs = self._openai_messages_to_anthropic(messages)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature,
        }

        if system_text:
            payload["system"] = system_text

        if tools:
            payload["tools"] = self._openai_tools_to_anthropic(tools)

        try:
            # DEBUG OPUS: log payload envoyé (print pour éviter troncature Rich)
            _dbg_roles = [m.get('role','?') for m in payload.get('messages',[])]
            _dbg_msg_lens = [len(json.dumps(m.get('content',''))) for m in payload.get('messages',[])]
            print(f"\n{'='*80}")
            print(f"🔍 OPUS DEBUG SEND")
            print(f"  model        = {payload.get('model')}")
            print(f"  max_tokens   = {payload.get('max_tokens')}")
            print(f"  temperature  = {payload.get('temperature')}")
            print(f"  system_len   = {len(payload.get('system',''))} chars")
            print(f"  messages     = {len(payload.get('messages',[]))} msgs")
            print(f"  has_tools    = {'tools' in payload}")
            print(f"  msg_roles    = {_dbg_roles}")
            print(f"  msg_sizes    = {_dbg_msg_lens}")
            print(f"  total_payload= {len(json.dumps(payload))} chars")
            print(f"{'='*80}\n", flush=True)

            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            # DEBUG OPUS: log réponse reçue (print pour éviter troncature Rich)
            content_blocks = data.get("content", [])
            usage_data = data.get("usage", {})
            _block_types = [b.get('type','?') for b in content_blocks]
            _has_text = any(b.get('text','').strip() for b in content_blocks if b.get('type')=='text')
            _text_preview = ""
            for b in content_blocks:
                if b.get('type') == 'text' and b.get('text','').strip():
                    _text_preview = b['text'][:200]
                    break
            print(f"\n{'='*80}")
            print(f"🔍 OPUS DEBUG RECV")
            print(f"  id           = {data.get('id','?')}")
            print(f"  model        = {data.get('model','?')}")
            print(f"  stop_reason  = {data.get('stop_reason','?')}")
            print(f"  blocks       = {len(content_blocks)} ({_block_types})")
            print(f"  input_tok    = {usage_data.get('input_tokens',0)}")
            print(f"  output_tok   = {usage_data.get('output_tokens',0)}")
            print(f"  has_text     = {_has_text}")
            print(f"  text_preview = {_text_preview[:200] if _text_preview else '(VIDE)'}")
            if not _has_text:
                print(f"  ⚠️ FULL CONTENT = {json.dumps(content_blocks, ensure_ascii=False)[:2000]}")
            print(f"{'='*80}\n", flush=True)

            has_text = _has_text
            _has_tool_use = any(b.get('type') == 'tool_use' for b in content_blocks)

            # Ne retry que si la réponse est VRAIMENT vide (ni texte, ni tool_use)
            # Les tool_use blocks sont une réponse valide — le modèle veut utiliser ses outils !
            if not has_text and not _has_tool_use:
                logger.warning(f"⚠ Anthropic content vide (pas de texte ni tool_use) — retry avec thinking")
                # Retry avec extended thinking activé (force Opus à produire du contenu)
                logger.info(f"🔄 Retry Anthropic avec thinking activé pour {model}")
                thinking_payload = {
                    "model": model,
                    "messages": anthropic_msgs,
                    "max_tokens": max_tokens or self._default_max_tokens,
                    "temperature": 1.0,  # Requis quand thinking est activé
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": 8000,
                    },
                }
                if system_text:
                    thinking_payload["system"] = system_text

                async with httpx.AsyncClient(timeout=180.0) as client2:
                    response2 = await client2.post(
                        f"{self.base_url}/v1/messages",
                        headers=self._headers(),
                        json=thinking_payload,
                    )
                    response2.raise_for_status()
                    data = response2.json()
                    content_blocks2 = data.get("content", [])
                    logger.info(
                        f"✓ Anthropic thinking retry — "
                        f"blocks={len(content_blocks2)}, "
                        f"types={[b.get('type','?') for b in content_blocks2]}"
                    )

            return self._anthropic_response_to_openai(data, model)

        except httpx.HTTPStatusError as e:
            logger.error(
                f"✗ Anthropic HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            )
            return LLMResponse(
                content=f"Erreur Anthropic : HTTP {e.response.status_code}",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )
        except Exception as e:
            logger.error(f"✗ Anthropic erreur : {e}")
            return LLMResponse(
                content="Erreur temporaire du provider Anthropic",
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
        Chat completion streaming via Anthropic Claude.

        Anthropic streaming events :
        - message_start, content_block_start, content_block_delta,
          content_block_stop, message_delta, message_stop
        """
        model = model_override or self.default_model

        system_text, anthropic_msgs = self._openai_messages_to_anthropic(messages)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        if system_text:
            payload["system"] = system_text

        if tools:
            payload["tools"] = self._openai_tools_to_anthropic(tools)

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/messages",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode()[:500]
                        yield LLMStreamChunk(
                            delta_content=f"Erreur Anthropic : HTTP {response.status_code}",
                            finish_reason="error",
                            model=model,
                            provider=self.provider_name,
                        )
                        return

                    # Accumulateur pour les tool_use blocks en cours
                    current_tool_id = None
                    current_tool_name = None
                    current_tool_input = ""

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        try:
                            data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        event_type = data.get("type", "")

                        if event_type == "content_block_delta":
                            delta = data.get("delta", {})
                            delta_type = delta.get("type", "")

                            if delta_type == "text_delta":
                                yield LLMStreamChunk(
                                    delta_content=delta.get("text", ""),
                                    model=model,
                                    provider=self.provider_name,
                                )
                            elif delta_type == "input_json_delta":
                                # Accumule le JSON du tool input
                                current_tool_input += delta.get(
                                    "partial_json", ""
                                )

                        elif event_type == "content_block_start":
                            block = data.get("content_block", {})
                            if block.get("type") == "tool_use":
                                current_tool_id = block.get("id", "")
                                current_tool_name = block.get("name", "")
                                current_tool_input = ""

                        elif event_type == "content_block_stop":
                            # Si on était dans un tool_use, émettre le chunk
                            if current_tool_id:
                                yield LLMStreamChunk(
                                    delta_tool_calls=[{
                                        "index": 0,
                                        "id": current_tool_id,
                                        "type": "function",
                                        "function": {
                                            "name": current_tool_name,
                                            "arguments": current_tool_input,
                                        },
                                    }],
                                    model=model,
                                    provider=self.provider_name,
                                )
                                current_tool_id = None

                        elif event_type == "message_stop":
                            yield LLMStreamChunk(
                                finish_reason="stop",
                                model=model,
                                provider=self.provider_name,
                            )
                            return

                        elif event_type == "message_delta":
                            stop = data.get("delta", {}).get("stop_reason")
                            if stop:
                                finish = "tool_calls" if stop == "tool_use" else "stop"
                                yield LLMStreamChunk(
                                    finish_reason=finish,
                                    model=model,
                                    provider=self.provider_name,
                                )
                                return

        except Exception as e:
            logger.error(f"✗ Anthropic stream erreur : {e}")
            yield LLMStreamChunk(
                delta_content="Erreur temporaire du provider Anthropic (streaming)",
                finish_reason="error",
                model=model,
                provider=self.provider_name,
            )

    # ─── Connectivité ────────────────────────────────────────

    async def test_connectivity(self) -> Dict[str, Any]:
        """Teste la connectivité à Anthropic."""
        if not self.api_key:
            return {
                "status": "disabled",
                "details": "ANTHROPIC_API_KEY non configurée",
            }

        try:
            # Anthropic n'a pas de /models endpoint public.
            # On fait un appel minimal pour tester l'auth.
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers=self._headers(),
                    json={
                        "model": self.default_model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                if response.status_code == 200:
                    return {"status": "ok"}
                elif response.status_code == 401:
                    return {"status": "error", "details": "Clé API invalide"}
                else:
                    return {"status": "ok", "details": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "error", "details": str(e)}

    def get_capabilities(self) -> Dict[str, bool]:
        """Capabilities du provider Anthropic."""
        return {
            "tools": True,
            "vision": True,
            "streaming": True,
        }

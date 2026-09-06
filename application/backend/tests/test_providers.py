"""
Tests Providers — OpenAI et Anthropic (traduction de format).

Couvre :
- OpenAI : format natif pass-through, headers, error handling
- Anthropic : traduction OpenAI→Anthropic et retour
  - System prompt extrait séparément
  - Tool calls → tool_use content blocks
  - Tool results → tool_result content blocks
  - Réponse content blocks → LLMResponse normalisée
- Résolution de la température par modèle (issue #2 : claude-opus-5 et
  gpt-5.6-terra rejettent le paramètre "temperature") + non-régression
  des modèles historiques + non-fuite de contenu dans les logs.

Ref: DESIGN/architecture.md §5
"""
import json
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.llm.openai import OpenAIProvider
from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.llmaas import LLMaaSProvider
from app.services.llm.google import GoogleProvider
from app.services.llm.base import LLMResponse, ModelConfig


# ============================================================
# Tests OpenAI
# ============================================================

class TestOpenAIProvider:
    """Tests de l'OpenAIProvider."""

    def test_provider_name(self):
        """Le provider_name est 'openai'."""
        provider = OpenAIProvider()
        assert provider.provider_name == "openai"

    def test_headers_format(self, monkeypatch):
        """
        Les headers contiennent Authorization Bearer.

        monkeypatch (et non os.environ + del) : un `del` supprimerait
        définitivement une vraie clé présente dans l'environnement et ferait
        échouer les tests d'intégration réelle exécutés ensuite.
        """
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        provider = OpenAIProvider()
        headers = provider._headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-key"

    def test_capabilities(self):
        """OpenAI supporte tools, vision et streaming."""
        provider = OpenAIProvider()
        caps = provider.get_capabilities()
        assert caps["tools"] is True
        assert caps["streaming"] is True


# ============================================================
# Tests Anthropic — Traduction de messages
# ============================================================

class TestAnthropicMessageTranslation:
    """Tests de la traduction des messages OpenAI → Anthropic."""

    def test_system_extracted(self):
        """Le message system est extrait comme paramètre séparé."""
        messages = [
            {"role": "system", "content": "Tu es un expert."},
            {"role": "user", "content": "Bonjour"},
        ]
        system, msgs = AnthropicProvider._openai_messages_to_anthropic(messages)
        assert system == "Tu es un expert."
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_no_system(self):
        """Sans message system → system = None."""
        messages = [
            {"role": "user", "content": "Bonjour"},
        ]
        system, msgs = AnthropicProvider._openai_messages_to_anthropic(messages)
        assert system is None
        assert len(msgs) == 1

    def test_assistant_with_tool_calls(self):
        """Message assistant avec tool_calls → content blocks."""
        messages = [
            {"role": "user", "content": "Calcule 2+2"},
            {
                "role": "assistant",
                "content": "Je vais calculer.",
                "tool_calls": [{
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "arguments": '{"expr": "2+2"}',
                    },
                }],
            },
        ]
        system, msgs = AnthropicProvider._openai_messages_to_anthropic(messages)
        assert len(msgs) == 2
        # Le message assistant doit avoir des content blocks
        assistant_msg = msgs[1]
        assert assistant_msg["role"] == "assistant"
        blocks = assistant_msg["content"]
        assert len(blocks) == 2  # text + tool_use
        assert blocks[0]["type"] == "text"
        assert blocks[1]["type"] == "tool_use"
        assert blocks[1]["name"] == "calculator"

    def test_tool_result_message(self):
        """Message role=tool → user avec tool_result block."""
        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": '{"result": 4}',
            },
        ]
        system, msgs = AnthropicProvider._openai_messages_to_anthropic(messages)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"][0]["type"] == "tool_result"
        assert msgs[0]["content"][0]["tool_use_id"] == "call_123"


# ============================================================
# Tests Anthropic — Traduction des tools
# ============================================================

class TestAnthropicToolTranslation:
    """Tests de la traduction des tool definitions."""

    def test_tools_translation(self):
        """Tools OpenAI → format Anthropic (input_schema)."""
        tools = [{
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Recherche internet",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        }]
        result = AnthropicProvider._openai_tools_to_anthropic(tools)
        assert len(result) == 1
        assert result[0]["name"] == "web_search"
        assert "input_schema" in result[0]
        assert result[0]["input_schema"]["type"] == "object"

    def test_empty_tools(self):
        """Liste vide → liste vide."""
        assert AnthropicProvider._openai_tools_to_anthropic([]) == []


# ============================================================
# Tests Anthropic — Traduction de la réponse
# ============================================================

class TestAnthropicResponseTranslation:
    """Tests de la traduction Anthropic → OpenAI."""

    def test_text_response(self):
        """Réponse texte simple → LLMResponse avec content."""
        data = {
            "content": [{"type": "text", "text": "La réponse est 4."}],
            "stop_reason": "end_turn",
            "model": "claude-opus-4.6",
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
        result = AnthropicProvider._anthropic_response_to_openai(data, "claude-opus-4.6")
        assert isinstance(result, LLMResponse)
        assert result.content == "La réponse est 4."
        assert result.finish_reason == "stop"
        assert result.tool_calls is None
        assert result.usage["total_tokens"] == 120

    def test_tool_use_response(self):
        """Réponse avec tool_use → LLMResponse avec tool_calls."""
        data = {
            "content": [
                {"type": "text", "text": "Je vais chercher."},
                {
                    "type": "tool_use",
                    "id": "toolu_123",
                    "name": "web_search",
                    "input": {"query": "K8s TCO"},
                },
            ],
            "stop_reason": "tool_use",
            "model": "claude-opus-4.6",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        result = AnthropicProvider._anthropic_response_to_openai(data, "claude-opus-4.6")
        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "web_search"
        assert result.content == "Je vais chercher."

    def test_max_tokens_response(self):
        """stop_reason=max_tokens → finish_reason=length."""
        data = {
            "content": [{"type": "text", "text": "Tronqué..."}],
            "stop_reason": "max_tokens",
            "model": "claude-opus-4.6",
            "usage": {"input_tokens": 100, "output_tokens": 4096},
        }
        result = AnthropicProvider._anthropic_response_to_openai(data, "claude-opus-4.6")
        assert result.finish_reason == "length"


# ============================================================
# Tests provider properties
# ============================================================

class TestAnthropicProviderProperties:
    """Tests des propriétés du provider Anthropic."""

    def test_provider_name(self):
        """Le provider_name est 'anthropic'."""
        provider = AnthropicProvider()
        assert provider.provider_name == "anthropic"

    def test_headers_format(self, monkeypatch):
        """
        Les headers contiennent x-api-key et anthropic-version.

        monkeypatch (et non os.environ + del) : un `del` supprimerait
        définitivement une vraie clé présente dans l'environnement et ferait
        échouer les tests d'intégration réelle exécutés ensuite.
        """
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        provider = AnthropicProvider()
        headers = provider._headers()
        assert "x-api-key" in headers
        assert headers["x-api-key"] == "test-key"
        assert "anthropic-version" in headers

    def test_capabilities(self):
        """Anthropic supporte tools, vision et streaming."""
        provider = AnthropicProvider()
        caps = provider.get_capabilities()
        assert caps["tools"] is True
        assert caps["streaming"] is True


# ============================================================
# ModelConfig.resolve_temperature — issue #2
# ============================================================

def _make_model_config(**overrides) -> ModelConfig:
    base = dict(
        id="test-model",
        display_name="Test Model",
        provider="openai",
        category="openai",
        api_model_id="test-model",
    )
    base.update(overrides)
    return ModelConfig(**base)


class TestModelConfigTemperature:
    """ModelConfig porte la capacité 'supports_temperature' (pas de hack sur le nom du modèle)."""

    def test_defaults(self):
        cfg = _make_model_config()
        assert cfg.supports_temperature is True
        assert cfg.extra_params == {}

    def test_resolve_temperature_when_supported(self):
        cfg = _make_model_config(supports_temperature=True)
        assert cfg.resolve_temperature(0.7) == 0.7

    def test_resolve_temperature_when_unsupported(self):
        cfg = _make_model_config(supports_temperature=False)
        assert cfg.resolve_temperature(0.7) is None


# ============================================================
# Mocks HTTP réutilisables (pas de dépendance externe type respx) —
# on patch httpx.AsyncClient au niveau du module provider et on
# inspecte les kwargs reçus par .post()/.stream() pour vérifier le
# payload EFFECTIVEMENT envoyé, pas juste le code qui le construit.
# ============================================================

class _FakeResponse:
    """Stand-in minimal pour httpx.Response (non-streaming)."""

    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
        self.text = json.dumps(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://test.invalid")
            raise httpx.HTTPStatusError(
                "error", request=request,
                response=httpx.Response(self.status_code, request=request, text=self.text),
            )

    def json(self):
        return self._json_data


def _mock_async_client_post(response_json):
    """Retourne (client_cls_mock, post_mock) — post_mock.call_args donne le payload envoyé."""
    post_mock = AsyncMock(return_value=_FakeResponse(response_json))

    client_instance = AsyncMock()
    client_instance.post = post_mock

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client_instance)
    client_cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=client_cm), post_mock


class _FakeStreamResponse:
    """Stand-in minimal pour httpx.Response en streaming (SSE)."""

    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code

    def raise_for_status(self):
        pass  # OpenAIProvider appelle raise_for_status() inconditionnellement en streaming

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


def _mock_async_client_stream(lines, status_code=200):
    """Retourne (client_cls_mock, stream_mock) — stream_mock.call_args donne le payload envoyé."""
    fake_response = _FakeStreamResponse(lines, status_code=status_code)

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=fake_response)
    stream_cm.__aexit__ = AsyncMock(return_value=False)

    stream_mock = MagicMock(return_value=stream_cm)

    client_instance = AsyncMock()
    client_instance.stream = stream_mock

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client_instance)
    client_cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=client_cm), stream_mock


# ============================================================
# Anthropic — payload effectif : temperature conditionnelle
# ============================================================

class TestAnthropicTemperaturePayload:
    """claude-opus-5 rejette 'temperature' (HTTP 400) — doit être omis, pas envoyé à 1.0 ou autre."""

    OK_RESPONSE = {
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "model": "claude-opus-5",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    @pytest.mark.asyncio
    async def test_temperature_sent_for_legacy_model(self):
        """Non-régression : claude-opus-4-6 continue de recevoir 'temperature'."""
        provider = AnthropicProvider()
        client_cls, post_mock = _mock_async_client_post(self.OK_RESPONSE)
        with patch("app.services.llm.anthropic.httpx.AsyncClient", client_cls):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "salut"}],
                temperature=0.7,
                model_override="claude-opus-4-6",
            )
        payload = post_mock.call_args.kwargs["json"]
        assert payload["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_temperature_omitted_for_claude_opus_5(self):
        provider = AnthropicProvider()
        client_cls, post_mock = _mock_async_client_post(self.OK_RESPONSE)
        with patch("app.services.llm.anthropic.httpx.AsyncClient", client_cls):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "salut"}],
                temperature=None,  # résolu par ModelConfig.resolve_temperature() en amont
                model_override="claude-opus-5",
            )
        payload = post_mock.call_args.kwargs["json"]
        assert "temperature" not in payload

    @pytest.mark.asyncio
    async def test_temperature_omitted_streaming_for_claude_opus_5(self):
        provider = AnthropicProvider()
        client_cls, stream_mock = _mock_async_client_stream(
            ['data: {"type": "message_stop"}']
        )
        with patch("app.services.llm.anthropic.httpx.AsyncClient", client_cls):
            chunks = [
                chunk
                async for chunk in provider.chat_completion_stream(
                    messages=[{"role": "user", "content": "salut"}],
                    temperature=None,
                    model_override="claude-opus-5",
                )
            ]
        payload = stream_mock.call_args.kwargs["json"]
        assert "temperature" not in payload
        assert chunks[-1].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_temperature_omitted_in_thinking_retry_payload(self):
        """Le retry 'thinking' sur réponse vide doit aussi omettre temperature si le modèle ne le supporte pas."""
        provider = AnthropicProvider()
        empty_response = {
            "content": [],
            "stop_reason": "end_turn",
            "model": "claude-opus-5",
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }
        thinking_response = {
            "content": [{"type": "text", "text": "réponse après thinking"}],
            "stop_reason": "end_turn",
            "model": "claude-opus-5",
            "usage": {"input_tokens": 1, "output_tokens": 5},
        }
        post_mock = AsyncMock(side_effect=[_FakeResponse(empty_response), _FakeResponse(thinking_response)])
        client_instance = AsyncMock()
        client_instance.post = post_mock
        client_cm = MagicMock()
        client_cm.__aenter__ = AsyncMock(return_value=client_instance)
        client_cm.__aexit__ = AsyncMock(return_value=False)
        client_cls = MagicMock(return_value=client_cm)

        with patch("app.services.llm.anthropic.httpx.AsyncClient", client_cls):
            result = await provider.chat_completion(
                messages=[{"role": "user", "content": "salut"}],
                temperature=None,
                model_override="claude-opus-5",
            )

        assert post_mock.call_count == 2
        retry_payload = post_mock.call_args_list[1].kwargs["json"]
        assert "temperature" not in retry_payload
        assert retry_payload["thinking"]["type"] == "enabled"
        assert result.content == "réponse après thinking"


# ============================================================
# Anthropic — aucune fuite de contenu dans les logs (issue #2, point 6)
# ============================================================

class TestAnthropicNoPlaintextLogging:

    @pytest.mark.asyncio
    async def test_no_prompt_or_response_leaked(self, capsys, caplog):
        secret_prompt = "SECRET_CANARY_PROMPT_1234"
        secret_response_text = "SECRET_CANARY_RESPONSE_5678"

        response_json = {
            "content": [{"type": "text", "text": secret_response_text}],
            "stop_reason": "end_turn",
            "model": "claude-opus-5",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        provider = AnthropicProvider()
        client_cls, _ = _mock_async_client_post(response_json)

        with caplog.at_level(logging.DEBUG):
            with patch("app.services.llm.anthropic.httpx.AsyncClient", client_cls):
                await provider.chat_completion(
                    messages=[{"role": "user", "content": secret_prompt}],
                    temperature=None,
                    model_override="claude-opus-5",
                )

        captured = capsys.readouterr()
        assert secret_prompt not in captured.out
        assert secret_response_text not in captured.out
        assert secret_prompt not in captured.err
        assert secret_response_text not in captured.err
        assert secret_prompt not in caplog.text
        assert secret_response_text not in caplog.text


# ============================================================
# OpenAI — payload effectif : temperature conditionnelle + extra_params
# ============================================================

class TestOpenAITemperaturePayload:
    """gpt-5.6-terra rejette temperature=0 — doit être omis, pas forcé à 1. reasoning_effort en config."""

    OK_RESPONSE = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "model": "gpt-5.6-terra",
        "usage": {"total_tokens": 2},
    }

    @pytest.mark.asyncio
    async def test_temperature_sent_for_legacy_model(self):
        """Non-régression : gpt-5.4 continue de recevoir 'temperature'."""
        provider = OpenAIProvider()
        client_cls, post_mock = _mock_async_client_post(self.OK_RESPONSE)
        with patch("app.services.llm.openai.httpx.AsyncClient", client_cls):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "salut"}],
                temperature=0.7,
                model_override="gpt-5.4",
            )
        payload = post_mock.call_args.kwargs["json"]
        assert payload["temperature"] == 0.7
        assert "reasoning_effort" not in payload

    @pytest.mark.asyncio
    async def test_temperature_omitted_and_reasoning_effort_for_gpt56_terra(self):
        provider = OpenAIProvider()
        client_cls, post_mock = _mock_async_client_post(self.OK_RESPONSE)
        with patch("app.services.llm.openai.httpx.AsyncClient", client_cls):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "salut"}],
                temperature=None,
                model_override="gpt-5.6-terra",
                extra_params={"reasoning_effort": "none"},
            )
        payload = post_mock.call_args.kwargs["json"]
        assert "temperature" not in payload
        assert payload["reasoning_effort"] == "none"

    @pytest.mark.asyncio
    async def test_temperature_omitted_streaming_for_gpt56_terra(self):
        provider = OpenAIProvider()
        client_cls, stream_mock = _mock_async_client_stream(["data: [DONE]"])
        with patch("app.services.llm.openai.httpx.AsyncClient", client_cls):
            chunks = [
                chunk
                async for chunk in provider.chat_completion_stream(
                    messages=[{"role": "user", "content": "salut"}],
                    temperature=None,
                    model_override="gpt-5.6-terra",
                    extra_params={"reasoning_effort": "none"},
                )
            ]
        payload = stream_mock.call_args.kwargs["json"]
        assert "temperature" not in payload
        assert payload["reasoning_effort"] == "none"
        assert chunks[-1].finish_reason == "stop"


# ============================================================
# OpenAI — round-trip complet d'appel d'outil (issue #2, point 4)
# ============================================================

class TestOpenAIToolRoundTrip:
    """
    Vérifie le cycle complet demande -> tool_call -> résultat d'outil -> réponse
    finale pour gpt-5.6-terra, pas seulement un payload isolé : les DEUX appels
    doivent rester sans 'temperature' et porter 'reasoning_effort'.
    """

    TOOLS = [{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Recherche web",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }]

    TOOL_CALL_RESPONSE = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query": "K8s TCO"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "model": "gpt-5.6-terra",
        "usage": {"total_tokens": 10},
    }

    FINAL_RESPONSE = {
        "choices": [{"message": {"content": "Réponse finale."}, "finish_reason": "stop"}],
        "model": "gpt-5.6-terra",
        "usage": {"total_tokens": 20},
    }

    @pytest.mark.asyncio
    async def test_full_tool_round_trip_without_temperature(self):
        provider = OpenAIProvider()
        extra_params = {"reasoning_effort": "none"}
        messages = [{"role": "user", "content": "Quel est le TCO de K8s ?"}]

        # --- Tour 1 : le modèle demande un tool call ---
        client_cls_1, post_mock_1 = _mock_async_client_post(self.TOOL_CALL_RESPONSE)
        with patch("app.services.llm.openai.httpx.AsyncClient", client_cls_1):
            response1 = await provider.chat_completion(
                messages=messages,
                tools=self.TOOLS,
                temperature=None,
                model_override="gpt-5.6-terra",
                extra_params=extra_params,
            )

        payload1 = post_mock_1.call_args.kwargs["json"]
        assert "temperature" not in payload1
        assert payload1["reasoning_effort"] == "none"
        assert payload1["tools"] == self.TOOLS
        assert response1.has_tool_calls
        assert response1.tool_calls[0]["function"]["name"] == "web_search"

        # --- Threading du résultat d'outil dans l'historique ---
        messages.append({
            "role": "assistant",
            "content": response1.content or "",
            "tool_calls": response1.tool_calls,
        })
        messages.append({
            "role": "tool",
            "tool_call_id": response1.tool_calls[0]["id"],
            "content": '{"result": "TCO K8s ~30% moins cher"}',
        })

        # --- Tour 2 : réponse finale après résultat d'outil ---
        client_cls_2, post_mock_2 = _mock_async_client_post(self.FINAL_RESPONSE)
        with patch("app.services.llm.openai.httpx.AsyncClient", client_cls_2):
            response2 = await provider.chat_completion(
                messages=messages,
                tools=self.TOOLS,
                temperature=None,
                model_override="gpt-5.6-terra",
                extra_params=extra_params,
            )

        payload2 = post_mock_2.call_args.kwargs["json"]
        assert "temperature" not in payload2
        assert payload2["reasoning_effort"] == "none"
        assert payload2["messages"][-1]["role"] == "tool"
        assert payload2["messages"][-1]["tool_call_id"] == "call_1"
        assert response2.content == "Réponse finale."
        assert response2.finish_reason == "stop"


# ============================================================
# LLMaaS / Google — extra_params est un no-op sans configuration (régression)
# ============================================================

class TestLLMaaSAndGoogleUnaffected:
    """Les modèles llmaas/google ne définissent pas extra_params — comportement inchangé."""

    @pytest.mark.asyncio
    async def test_llmaas_temperature_and_extra_params_merge(self):
        provider = LLMaaSProvider()
        response_json = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "model": "gpt-oss:120b",
            "usage": {"total_tokens": 2},
        }
        client_cls, post_mock = _mock_async_client_post(response_json)
        with patch("app.services.llm.llmaas.httpx.AsyncClient", client_cls):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "salut"}],
                temperature=0.7,
                model_override="gpt-oss:120b",
                extra_params={"top_p": 0.9},
            )
        payload = post_mock.call_args.kwargs["json"]
        assert payload["temperature"] == 0.7
        assert payload["top_p"] == 0.9

    @pytest.mark.asyncio
    async def test_google_temperature_nested_and_extra_params_top_level(self):
        provider = GoogleProvider()
        response_json = {
            "candidates": [{
                "content": {"parts": [{"text": "ok"}]},
                "finishReason": "STOP",
            }],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
        }
        client_cls, post_mock = _mock_async_client_post(response_json)
        with patch("app.services.llm.google.httpx.AsyncClient", client_cls):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "salut"}],
                temperature=0.7,
                model_override="gemini-3.1-pro-preview",
                extra_params={"safetySettings": []},
            )
        payload = post_mock.call_args.kwargs["json"]
        assert payload["generationConfig"]["temperature"] == 0.7
        assert payload["safetySettings"] == []

    @pytest.mark.asyncio
    async def test_google_temperature_none_omits_generation_config_key(self):
        provider = GoogleProvider()
        response_json = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
        }
        client_cls, post_mock = _mock_async_client_post(response_json)
        with patch("app.services.llm.google.httpx.AsyncClient", client_cls):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "salut"}],
                temperature=None,
                model_override="gemini-3.1-pro-preview",
            )
        payload = post_mock.call_args.kwargs["json"]
        assert "generationConfig" not in payload or "temperature" not in payload.get("generationConfig", {})


# ============================================================
# Intégration réelle — OPT-IN uniquement (issue #2, critère d'acceptation)
# ============================================================
#
# Ces tests ne lisent PAS le .env : ils ne s'exécutent que si la clé API
# correspondante est déjà présente dans l'environnement du process au
# moment du run. Un `pytest` classique (CI ou poste dev sans export
# explicite) les SKIP automatiquement — aucun appel réseau ni coût
# accidentel. Pour les activer :
#   ANTHROPIC_API_KEY=... OPENAI_API_KEY=... pytest tests/test_providers.py -k Live
# ============================================================

# Schéma calqué sur DEBATE_TOOLS_OPENAI (services/tools/executor.py), réduit au
# strict nécessaire : un outil sans argument, donc sans ambiguïté de parsing.
_LIVE_TOOLS = [{
    "type": "function",
    "function": {
        "name": "datetime_info",
        "description": "Retourne la date et l'heure courantes au format ISO 8601.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}]

_LIVE_TOOL_QUESTION = (
    "Quelle heure est-il exactement ? Tu DOIS utiliser l'outil datetime_info "
    "pour le savoir, ne devine pas."
)

# Horloge figée : on mesure le protocole d'outils, pas l'outil lui-même.
_LIVE_TOOL_RESULT = '{"datetime": "2026-09-06T09:15:00+02:00", "tz": "Europe/Paris"}'


async def _assert_live_tool_round_trip(provider, model, *, temperature, extra_params):
    """
    Vérifie les 4 étapes réelles : demande → tool_call → tool_result → réponse
    finale exploitant le résultat (critère d'acceptation #3 de l'issue #2).

    Volontairement plus strict qu'un simple "pas d'erreur" : on exige que le
    modèle DEMANDE l'outil, puis que sa réponse finale reprenne la valeur
    injectée. Un test qui se contenterait d'un HTTP 200 ne prouverait pas que le
    chemin d'outils fonctionne.
    """
    first = await provider.chat_completion(
        messages=[{"role": "user", "content": _LIVE_TOOL_QUESTION}],
        tools=_LIVE_TOOLS,
        temperature=temperature,
        max_tokens=512,
        model_override=model,
        extra_params=extra_params,
    )
    assert first.finish_reason != "error", f"{model} étape 1 : {first.content}"
    assert first.tool_calls, (
        f"{model} n'a demandé aucun outil (finish={first.finish_reason}). "
        f"Réponse : {(first.content or '')[:200]}"
    )

    call = first.tool_calls[0]
    assert call["function"]["name"] == "datetime_info"

    final = await provider.chat_completion(
        messages=[
            {"role": "user", "content": _LIVE_TOOL_QUESTION},
            {
                "role": "assistant",
                "content": first.content or "",
                "tool_calls": first.tool_calls,
            },
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": _LIVE_TOOL_RESULT,
            },
        ],
        tools=_LIVE_TOOLS,
        temperature=temperature,
        max_tokens=512,
        model_override=model,
        extra_params=extra_params,
    )
    assert final.finish_reason != "error", f"{model} étape 4 : {final.content}"

    text = (final.content or "")
    # Le modèle doit avoir exploité l'heure injectée. On accepte les variantes
    # de formatage (09:15, 9h15, 09h15...) mais pas l'absence de la valeur.
    normalized = text.replace("h", ":").replace(" ", "")
    assert "9:15" in normalized, (
        f"{model} n'a pas exploité le résultat d'outil. Réponse : {text[:200]}"
    )


class TestLiveIntegration:

    @pytest.mark.asyncio
    @pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY absente de l'environnement")
    async def test_claude_opus_5_real_call_without_temperature(self):
        provider = AnthropicProvider()
        response = await provider.chat_completion(
            messages=[{"role": "user", "content": "Réponds uniquement par le mot 'ok'."}],
            temperature=None,
            max_tokens=16,
            model_override="claude-opus-5",
        )
        assert response.finish_reason != "error", response.content

    @pytest.mark.asyncio
    @pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY absente de l'environnement")
    async def test_gpt_56_terra_real_call_with_reasoning_effort_none(self):
        """
        Config réelle de la registry : reasoning_effort="none" + temperature
        conservée. C'est "none" qui rend les deux acceptables (cf. llm_models.yaml).
        """
        provider = OpenAIProvider()
        response = await provider.chat_completion(
            messages=[{"role": "user", "content": "Réponds uniquement par le mot 'ok'."}],
            temperature=0.7,
            max_tokens=16,
            model_override="gpt-5.6-terra",
            extra_params={"reasoning_effort": "none"},
        )
        assert response.finish_reason != "error", response.content

    @pytest.mark.asyncio
    @pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY absente de l'environnement")
    async def test_gpt_56_terra_rejects_active_reasoning_effort_with_tools(self):
        """
        Test de garde : prouve que la contrainte de la registry est RÉELLE.

        Sans ce test, rien ne démontre qu'un reasoning_effort actif casse
        vraiment les appels — et une régression vers "high" passerait pour une
        simple préférence de configuration.
        """
        provider = OpenAIProvider()
        response = await provider.chat_completion(
            messages=[{"role": "user", "content": "Quelle heure est-il ?"}],
            tools=_LIVE_TOOLS,
            temperature=0.7,
            max_tokens=64,
            model_override="gpt-5.6-terra",
            extra_params={"reasoning_effort": "high"},
        )
        assert response.finish_reason == "error", (
            "gpt-5.6-terra devrait rejeter reasoning_effort actif + function tools. "
            "Si ce test échoue, l'API a changé : réévaluer la contrainte de la registry."
        )

    @pytest.mark.asyncio
    @pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY absente de l'environnement")
    async def test_claude_opus_5_real_tool_round_trip(self):
        """Critère d'acceptation #3 : round-trip d'outils réel, sans mock."""
        await _assert_live_tool_round_trip(
            AnthropicProvider(), "claude-opus-5", temperature=None, extra_params=None
        )

    @pytest.mark.asyncio
    @pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY absente de l'environnement")
    async def test_gpt_56_terra_real_tool_round_trip(self):
        """
        Critère d'acceptation #3 : round-trip d'outils réel, sans mock.

        Enjeu spécifique : reasoning_effort="none" désactive le raisonnement du
        modèle. Ce test vérifie que le tool calling y survit — sans quoi le
        modèle par défaut serait inutilisable pour un débat AdviceRoom, qui
        repose sur web_search / calculator / datetime_info.
        """
        await _assert_live_tool_round_trip(
            OpenAIProvider(), "gpt-5.6-terra",
            temperature=0.7, extra_params={"reasoning_effort": "none"},
        )

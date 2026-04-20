"""
Tests Providers — OpenAI et Anthropic (traduction de format).

Couvre :
- OpenAI : format natif pass-through, headers, error handling
- Anthropic : traduction OpenAI→Anthropic et retour
  - System prompt extrait séparément
  - Tool calls → tool_use content blocks
  - Tool results → tool_result content blocks
  - Réponse content blocks → LLMResponse normalisée

Ref: DESIGN/architecture.md §5
"""
import pytest

from app.services.llm.openai import OpenAIProvider
from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.base import LLMResponse


# ============================================================
# Tests OpenAI
# ============================================================

class TestOpenAIProvider:
    """Tests de l'OpenAIProvider."""

    def test_provider_name(self):
        """Le provider_name est 'openai'."""
        provider = OpenAIProvider()
        assert provider.provider_name == "openai"

    def test_headers_format(self):
        """Les headers contiennent Authorization Bearer."""
        import os
        os.environ["OPENAI_API_KEY"] = "test-key"
        provider = OpenAIProvider()
        headers = provider._headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-key"
        del os.environ["OPENAI_API_KEY"]

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

    def test_headers_format(self):
        """Les headers contiennent x-api-key et anthropic-version."""
        import os
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        provider = AnthropicProvider()
        headers = provider._headers()
        assert "x-api-key" in headers
        assert headers["x-api-key"] == "test-key"
        assert "anthropic-version" in headers
        del os.environ["ANTHROPIC_API_KEY"]

    def test_capabilities(self):
        """Anthropic supporte tools, vision et streaming."""
        provider = AnthropicProvider()
        caps = provider.get_capabilities()
        assert caps["tools"] is True
        assert caps["streaming"] is True

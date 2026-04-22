"""
ToolExecutor — Bridge vers le serveur MCP Tools externe.

Permet aux LLMs du débat d'utiliser des outils (web search, calculatrice,
date/heure) via le serveur MCP Tools de Cloud Temple.

Pipeline :
1. Au démarrage, se connecte au MCP Tools et récupère la liste d'outils
2. Convertit les outils en format OpenAI function calling
3. Pendant le débat, exécute les tool_calls et retourne les résultats

Mapping tools.yaml → MCP Tools :
- web_search    → perplexity_search (query)
- calculator    → calc (expr)
- datetime      → date (operation, date, tz)

Ref: DESIGN/architecture.md §9 (Tool-MAD)
"""
import json
import logging
from typing import Any, Dict, List, Optional

from ...config.settings import get_settings

logger = logging.getLogger(__name__)

__all__ = ["ToolExecutor", "get_tool_executor"]


# ============================================================
# Définitions des outils au format OpenAI function calling
# ============================================================

# Outils exposés aux LLMs pendant le débat
DEBATE_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Recherche sur internet pour vérifier des faits, "
                "trouver des données récentes ou des sources académiques. "
                "Utilisez cet outil quand vous avez besoin de preuves factuelles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La requête de recherche (en français ou anglais)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "Évalue une expression mathématique Python. "
                "Modules math et statistics pré-importés. "
                "Ex: '(3+5)*2', 'math.sqrt(144)', 'statistics.mean([10,20,30])'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {
                        "type": "string",
                        "description": "Expression mathématique Python à évaluer",
                    },
                },
                "required": ["expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "datetime_info",
            "description": (
                "Récupère la date/heure actuelle ou effectue des calculs de dates. "
                "Opérations : now, today, diff, add, format, week_number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["now", "today", "diff", "add", "format",
                                 "week_number", "day_of_week"],
                        "description": "Opération de date à effectuer",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date ISO 8601 (optionnel, pour diff/add/format)",
                    },
                },
                "required": ["operation"],
            },
        },
    },
]

# Mapping AdviceRoom tool name → MCP tool name + arguments transform
TOOL_MAPPING = {
    "web_search": {
        "mcp_tool": "perplexity_search",
        "transform": lambda args: {
            "query": args.get("query", ""),
            "detail_level": "normal",
        },
    },
    "calculator": {
        "mcp_tool": "calc",
        "transform": lambda args: {
            "expr": args.get("expr", ""),
        },
    },
    "datetime_info": {
        "mcp_tool": "date",
        "transform": lambda args: {
            "operation": args.get("operation", "now"),
            "date": args.get("date"),
            "tz": "Europe/Paris",
        },
    },
}


class ToolExecutor:
    """
    Exécuteur d'outils pour le débat.

    Se connecte au serveur MCP Tools externe pour exécuter
    les tool calls des LLMs participants.
    """

    def __init__(self) -> None:
        """Initialise le tool executor depuis les settings."""
        settings = get_settings()
        self._url = settings.mcp_tools_url.rstrip("/") if settings.mcp_tools_url else ""
        self._token = settings.mcp_tools_token
        self._available = bool(self._url and self._token)

        if self._available:
            logger.info(f"✓ ToolExecutor configuré : {self._url}")
        else:
            logger.warning("⚠ ToolExecutor désactivé (MCP_TOOLS_URL/TOKEN non configurés)")

    @property
    def available(self) -> bool:
        """True si le serveur MCP Tools est configuré."""
        return self._available

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Retourne les définitions d'outils au format OpenAI function calling.

        Ces définitions sont passées aux LLMs dans le paramètre 'tools'
        de chat_completion.

        Returns:
            Liste de tool definitions OpenAI, ou [] si désactivé.
        """
        if not self._available:
            return []
        return DEBATE_TOOLS_OPENAI

    async def execute_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Exécute un tool call via le serveur MCP Tools.

        Args:
            tool_name: Nom de l'outil (web_search, calculator, datetime_info)
            arguments: Arguments de l'outil (déjà parsés depuis le JSON du LLM)

        Returns:
            Résultat de l'outil {status, result/error}
        """
        if not self._available:
            return {"status": "error", "error": "Outils non disponibles"}

        mapping = TOOL_MAPPING.get(tool_name)
        if not mapping:
            return {"status": "error", "error": f"Outil inconnu : {tool_name}"}

        mcp_tool = mapping["mcp_tool"]
        mcp_args = mapping["transform"](arguments)

        # Nettoyer les None des arguments
        mcp_args = {k: v for k, v in mcp_args.items() if v is not None}

        logger.info(f"🔧 Tool call : {tool_name} → {mcp_tool}({mcp_args})")

        try:
            result = await self._call_mcp_tool(mcp_tool, mcp_args)
            logger.info(f"  ✓ Résultat : {str(result)[:200]}")
            return {"status": "ok", "result": result}
        except Exception as e:
            logger.error(f"  ✗ Erreur tool {tool_name}: {e}")
            return {"status": "error", "error": "Erreur temporaire lors de l'exécution de l'outil"}

    async def _call_mcp_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        """
        Appelle un outil sur le serveur MCP Tools via Streamable HTTP.

        Utilise le SDK MCP officiel pour la communication.

        Args:
            tool_name: Nom de l'outil MCP (ex: perplexity_search)
            arguments: Arguments de l'outil

        Returns:
            Résultat de l'outil (texte ou dict)
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        async with streamablehttp_client(
            f"{self._url}/mcp",
            headers=headers,
            timeout=30,
            sse_read_timeout=60,
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(tool_name, arguments)

                # Extraire le texte de la réponse MCP
                if getattr(result, "isError", False):
                    error_msg = "Erreur MCP"
                    if result.content:
                        error_msg = getattr(result.content[0], "text", "") or error_msg
                    raise RuntimeError(error_msg)

                text = ""
                if result.content:
                    text = getattr(result.content[0], "text", "") or ""

                # Tenter de parser comme JSON
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text

    async def test_connectivity(self) -> Dict[str, Any]:
        """
        Teste la connectivité avec le serveur MCP Tools.

        Returns:
            {status: ok/error, tools_count, tools: [...]}
        """
        if not self._available:
            return {"status": "disabled", "message": "MCP Tools non configuré"}

        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            headers = {}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"

            async with streamablehttp_client(
                f"{self._url}/mcp",
                headers=headers,
                timeout=10,
                sse_read_timeout=10,
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()

                    tool_names = [t.name for t in tools.tools]
                    return {
                        "status": "ok",
                        "tools_count": len(tool_names),
                        "tools": tool_names,
                    }
        except Exception as e:
            logger.error(f"✗ Erreur test connectivité MCP Tools: {e}")
            return {"status": "error", "error": "Erreur de connectivité MCP Tools"}


# ============================================================
# Singleton
# ============================================================

_executor_instance: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Récupère l'instance singleton du ToolExecutor."""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = ToolExecutor()
    return _executor_instance

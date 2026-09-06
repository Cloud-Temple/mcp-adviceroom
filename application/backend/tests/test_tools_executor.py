"""
Tests ToolExecutor — non-fuite du contenu utilisateur dans les logs.

Issue #2, critère d'acceptation #5 : « Aucun prompt, aperçu de réponse ou
résultat d'outil n'est journalisé en clair en production. »

Les arguments d'outil dérivent de la question de débat et des réponses des LLMs,
et le résultat d'outil peut contenir n'importe quel contenu récupéré sur le web.
Ni l'un ni l'autre ne doit atteindre les logs, qui tournent en INFO en production.

Ces tests utilisent des marqueurs uniques improbables : si l'un d'eux apparaît
quelque part dans les logs ou sur stdout/stderr, la fuite est prouvée.
"""
import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tools.executor import ToolExecutor


# Marqueurs improbables — leur présence dans un log prouve la fuite.
SECRET_QUERY = "MARQUEUR-QUERY-c3f9a1e7-CONFIDENTIEL"
SECRET_RESULT = "MARQUEUR-RESULTAT-8b2d4f6a-CONFIDENTIEL"


@pytest.fixture
def executor():
    """ToolExecutor forcé disponible, sans dépendance réseau."""
    exe = ToolExecutor()
    exe._url = "https://tools.invalid"
    exe._token = "test-token"
    exe._available = True
    return exe


class TestToolExecutorNoContentLogging:

    @pytest.mark.asyncio
    async def test_tool_arguments_are_not_logged(self, executor, caplog, capsys):
        """Les ARGUMENTS d'outil (contenu utilisateur) ne fuient pas."""
        with patch.object(
            executor, "_call_mcp_tool", new=AsyncMock(return_value="ok")
        ):
            with caplog.at_level(logging.DEBUG):
                result = await executor.execute_tool_call(
                    "web_search", {"query": SECRET_QUERY}
                )

        assert result["status"] == "ok"

        captured = capsys.readouterr()
        haystack = caplog.text + captured.out + captured.err
        assert SECRET_QUERY not in haystack, (
            "La query utilisateur a fuité dans les logs."
        )

    @pytest.mark.asyncio
    async def test_tool_result_is_not_logged(self, executor, caplog, capsys):
        """Le RÉSULTAT d'outil ne fuite pas, même tronqué."""
        with patch.object(
            executor, "_call_mcp_tool", new=AsyncMock(return_value=SECRET_RESULT)
        ):
            with caplog.at_level(logging.DEBUG):
                result = await executor.execute_tool_call(
                    "calculator", {"expr": "2+2"}
                )

        assert result["status"] == "ok"
        # Le résultat doit bien être RETOURNÉ à l'appelant...
        assert result["result"] == SECRET_RESULT

        captured = capsys.readouterr()
        haystack = caplog.text + captured.out + captured.err
        # ... mais jamais journalisé.
        assert SECRET_RESULT not in haystack, (
            "Le résultat d'outil a fuité dans les logs."
        )

    @pytest.mark.asyncio
    async def test_diagnostic_remains_useful(self, executor, caplog):
        """
        Contre-test : la suppression du contenu ne doit pas rendre les logs
        inutiles. Le nom de l'outil et les CLÉS d'arguments restent tracés,
        ce qui suffit à diagnostiquer un incident sans exposer de données.
        """
        with patch.object(
            executor, "_call_mcp_tool", new=AsyncMock(return_value="ok")
        ):
            with caplog.at_level(logging.INFO):
                await executor.execute_tool_call(
                    "web_search", {"query": SECRET_QUERY}
                )

        assert "web_search" in caplog.text
        assert "perplexity_search" in caplog.text
        # La CLÉ de l'argument est tracée, pas sa VALEUR.
        assert "query" in caplog.text
        assert SECRET_QUERY not in caplog.text

class TestToolExecutorConnectionClosed:
    """
    Issue #5 — traitement de CONNECTION_CLOSED apporté par le SDK MCP v2.

    En v1, un flux SSE qui se fermait sur HTTP 200 sans réponse JSON-RPC
    terminale laissait l'appel bloqué jusqu'au watchdog. La v2 synthétise une
    MCPError(code=CONNECTION_CLOSED). Ces tests couvrent NOTRE traitement de
    cette erreur, pas le transport du SDK.
    """

    @pytest.mark.asyncio
    async def test_connection_closed_returns_bounded_error(self, executor, caplog):
        """Un CONNECTION_CLOSED produit une erreur explicite, pas une attente."""
        from mcp import MCPError
        from mcp.client.streamable_http import CONNECTION_CLOSED

        with patch.object(
            executor,
            "_call_mcp_tool",
            new=AsyncMock(side_effect=MCPError(
                code=CONNECTION_CLOSED,
                message="SSE stream ended without a response",
            )),
        ):
            with caplog.at_level(logging.WARNING):
                result = await executor.execute_tool_call(
                    "web_search", {"query": SECRET_QUERY}
                )

        assert result["status"] == "error"
        # Message distinct d'une erreur générique : l'appelant peut différencier
        # une connexion interrompue d'un échec d'exécution.
        assert "interrompue" in result["error"]
        # Le code est tracé pour le diagnostic...
        assert str(CONNECTION_CLOSED) in caplog.text
        # ... mais ni la query ni le message du serveur distant.
        assert SECRET_QUERY not in caplog.text
        assert "SSE stream ended" not in caplog.text

    @pytest.mark.asyncio
    async def test_other_mcp_error_is_distinguished(self, executor, caplog):
        """Une MCPError qui n'est pas CONNECTION_CLOSED reste une erreur générique."""
        from mcp import MCPError

        with patch.object(
            executor,
            "_call_mcp_tool",
            new=AsyncMock(side_effect=MCPError(code=-32601, message="Method not found")),
        ):
            with caplog.at_level(logging.ERROR):
                result = await executor.execute_tool_call("calculator", {"expr": "1+1"})

        assert result["status"] == "error"
        assert "interrompue" not in result["error"]
        assert "-32601" in caplog.text
        assert "Method not found" not in caplog.text


class TestToolExecutorErrorPaths:

    @pytest.mark.asyncio
    async def test_tool_error_does_not_leak_arguments(self, executor, caplog, capsys):
        """Le chemin d'erreur ne doit pas non plus exposer les arguments."""
        with patch.object(
            executor,
            "_call_mcp_tool",
            new=AsyncMock(side_effect=RuntimeError(f"echec sur {SECRET_QUERY}")),
        ):
            with caplog.at_level(logging.DEBUG):
                result = await executor.execute_tool_call(
                    "web_search", {"query": SECRET_QUERY}
                )

        assert result["status"] == "error"
        # Le message rendu à l'appelant reste générique (pas de fuite via l'API).
        assert SECRET_QUERY not in result["error"]

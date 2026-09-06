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

"""
Tests du rate limiting — findings HIGH #2 et #5 de l'audit du 24/08/2026.

Aucun contrôle de débit n'existait sur la création de débats, ouverte par TROIS
voies (REST, admin, outil MCP). Chaque débat mobilise jusqu'à 5 LLMs plus un
synthétiseur : un porteur de token valide pouvait épuiser le budget LLM en
boucle. La création de tokens admin n'était pas limitée non plus.

Ces tests couvrent les deux gardes — le débit et le quota simultané — et
vérifient surtout que les TROIS voies l'appliquent. Une seule voie oubliée
annulerait la protection des deux autres, et la bank identifie l'incohérence
inter-fonctions comme la première source de bugs du projet.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Fixtures réutilisées de test_api : importées (et non dupliquées) pour que
# le test d'intégration s'appuie sur le même montage d'application.
from tests.test_api import client, mock_all  # noqa: F401
from app.services.rate_limit import (
    RateLimitExceeded,
    SlidingWindowLimiter,
    count_active_debates,
    enforce_active_debate_quota,
    reset_rate_limiters,
)


def _find_app_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "app"


@pytest.fixture(autouse=True)
def _clean_limiters():
    """Chaque test part de limiteurs vierges."""
    reset_rate_limiters()
    yield
    reset_rate_limiters()


def _debate(owner: str, status: str = "running"):
    """Débat minimal : seuls owner et status sont lus par le quota."""
    return SimpleNamespace(owner=owner, status=status)


# ============================================================
# Fenêtre glissante
# ============================================================

class TestSlidingWindow:

    def test_allows_up_to_the_limit(self):
        limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
        for _ in range(3):
            limiter.check("client-a")  # ne doit pas lever

    def test_blocks_beyond_the_limit(self):
        limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
        for _ in range(3):
            limiter.check("client-a")

        with pytest.raises(RateLimitExceeded) as exc:
            limiter.check("client-a")

        assert exc.value.retry_after is not None
        assert exc.value.retry_after > 0

    def test_keys_are_isolated(self):
        """Un client abusif ne doit pas bloquer les autres."""
        limiter = SlidingWindowLimiter(max_events=1, window_seconds=60)
        limiter.check("client-a")

        with pytest.raises(RateLimitExceeded):
            limiter.check("client-a")

        limiter.check("client-b")  # non affecté

    def test_window_slides(self):
        """Les événements sortis de la fenêtre libèrent des places."""
        limiter = SlidingWindowLimiter(max_events=2, window_seconds=10)
        limiter.check("k", now=100.0)
        limiter.check("k", now=101.0)

        with pytest.raises(RateLimitExceeded):
            limiter.check("k", now=102.0)

        # 111 > 101 + 10 : les deux premiers sont hors fenêtre.
        limiter.check("k", now=111.5)

    def test_rejected_attempt_is_not_recorded(self):
        """
        Une tentative refusée ne doit pas repousser la fenêtre.

        Sinon un client qui martèle l'endpoint resterait bloqué bien après
        avoir cessé — la fenêtre étant sans cesse réalimentée par ses propres
        échecs. C'est un piège classique des implémentations naïves.
        """
        limiter = SlidingWindowLimiter(max_events=1, window_seconds=10)
        limiter.check("k", now=100.0)

        # Rafale de refus pendant toute la fenêtre.
        for t in (101.0, 102.0, 103.0, 109.0):
            with pytest.raises(RateLimitExceeded):
                limiter.check("k", now=t)

        # À 110.5, seul l'événement de 100.0 comptait : la place est libérée.
        limiter.check("k", now=110.5)

    def test_zero_disables_the_limit(self):
        limiter = SlidingWindowLimiter(max_events=0, window_seconds=60)
        for _ in range(50):
            limiter.check("k")


# ============================================================
# Quota de débats simultanés
# ============================================================

class TestActiveDebateQuota:

    def test_counts_only_this_client(self):
        debates = [_debate("alice"), _debate("bob"), _debate("alice")]
        assert count_active_debates(debates, "alice") == 2
        assert count_active_debates(debates, "bob") == 1
        assert count_active_debates(debates, "carol") == 0

    def test_counts_only_unfinished_debates(self):
        """Un débat terminé ne consomme plus de ressources LLM."""
        debates = [
            _debate("alice", "created"),
            _debate("alice", "running"),
            _debate("alice", "paused"),
            _debate("alice", "completed"),
            _debate("alice", "error"),
        ]
        assert count_active_debates(debates, "alice") == 3

    def test_quota_blocks_when_reached(self, monkeypatch):
        from app.config import settings as settings_mod

        monkeypatch.setattr(
            settings_mod.get_settings(), "rate_limit_max_active_debates", 2,
            raising=False,
        )
        debates = [_debate("alice"), _debate("alice")]

        with pytest.raises(RateLimitExceeded) as exc:
            enforce_active_debate_quota(debates, "alice")

        # Pas de retry_after : l'attente dépend de la fin d'un débat, pas du
        # temps qui passe. Annoncer un délai serait mensonger.
        assert exc.value.retry_after is None

    def test_quota_allows_other_clients(self, monkeypatch):
        from app.config import settings as settings_mod

        monkeypatch.setattr(
            settings_mod.get_settings(), "rate_limit_max_active_debates", 2,
            raising=False,
        )
        debates = [_debate("alice"), _debate("alice")]

        enforce_active_debate_quota(debates, "bob")  # ne doit pas lever


# ============================================================
# Cohérence des trois voies d'entrée
# ============================================================

class TestAllEntryPointsAreGuarded:
    """
    Les trois voies de création de débats doivent appliquer les MÊMES gardes.

    Test structurel plutôt que comportemental : il attrape l'ajout d'une
    quatrième voie non protégée, ou la suppression d'une garde existante — ce
    qu'aucun test fonctionnel des voies actuelles ne verrait.
    """

    ENTRY_POINTS = (
        "routers/debates.py",
        "admin/api.py",
        "mcp/tools.py",
    )

    @pytest.mark.parametrize("relative", ENTRY_POINTS)
    def test_entry_point_checks_rate_limit(self, relative):
        source = (_find_app_dir() / relative).read_text()

        assert "get_debate_creation_limiter" in source, (
            f"{relative} ne vérifie pas le débit de création de débats"
        )
        assert "enforce_active_debate_quota" in source, (
            f"{relative} ne vérifie pas le quota de débats simultanés"
        )
        assert "RateLimitExceeded" in source, (
            f"{relative} ne traite pas le refus"
        )

    # Le moteur lui-même n'est pas une porte d'entrée : la garde appartient aux
    # points d'entrée authentifiés, qui seuls connaissent l'identité appelante.
    # L'y placer rendrait le contrôle implicite et dépendant d'un ContextVar.
    ENGINE_FILES = {"services/debate/orchestrator.py"}

    def test_no_unguarded_create_debate_call(self):
        """
        Toute porte d'entrée appelant create_debate doit appliquer les gardes.

        Attrape l'ajout d'un quatrième point d'entrée non protégé — ce qu'aucun
        test des trois voies actuelles ne verrait.
        """
        app_dir = _find_app_dir()
        offenders = []
        for py in app_dir.rglob("*.py"):
            relative = py.relative_to(app_dir).as_posix()
            if relative in self.ENGINE_FILES:
                continue
            text = py.read_text()
            if ".create_debate(" not in text:
                continue
            if "get_debate_creation_limiter" not in text:
                offenders.append(relative)

        assert offenders == [], (
            f"Création de débat sans garde de débit : {offenders}"
        )

    def test_token_creation_is_guarded(self):
        """HIGH #5 — la création de tokens admin doit être limitée."""
        source = (_find_app_dir() / "admin" / "api.py").read_text()
        assert "get_token_creation_limiter" in source


# ============================================================
# Intégration REST — code HTTP et en-tête
# ============================================================

class TestRestReturns429:

    def test_debate_creation_returns_429_with_retry_after(self, client, monkeypatch):
        """
        Au-delà de la limite, la route REST doit répondre 429 et indiquer
        Retry-After — sans quoi le client réessaie à l'aveugle.
        """
        from app.services import rate_limit as rl

        # Limite à 1 pour éviter d'enchaîner des créations coûteuses.
        monkeypatch.setattr(
            rl, "_debate_limiter",
            rl.SlidingWindowLimiter(max_events=1, window_seconds=60),
        )

        payload = {
            "question": "Faut-il préférer Kubernetes à des VM ?",
            "participants": [
                {"provider": "llmaas", "model": "model-a"},
                {"provider": "llmaas", "model": "model-b"},
            ],
        }
        from tests.conftest import TEST_AUTH_HEADERS

        # Orchestrateur mocké (même approche que test_api) : on mesure le
        # contrôle de débit de la route, pas l'exécution d'un vrai débat — qui
        # déclencherait de véritables appels LLM.
        from app.services.debate.models import Debate, Participant

        mock_orch = MagicMock()
        debate = Debate(question="Faut-il préférer Kubernetes à des VM ?")
        debate.participants = [
            Participant(id="a", model_id="model-a", provider="llmaas", display_name="A"),
            Participant(id="b", model_id="model-b", provider="llmaas", display_name="B"),
        ]
        mock_orch.create_debate.return_value = debate

        with patch("app.routers.debates.get_orchestrator", return_value=mock_orch), \
             patch("app.routers.debates._run_debate_task", new=AsyncMock()):
            first = client.post("/api/v1/debates", json=payload, headers=TEST_AUTH_HEADERS)
            assert first.status_code in (200, 201), first.text

            second = client.post("/api/v1/debates", json=payload, headers=TEST_AUTH_HEADERS)

        assert second.status_code == 429, second.text
        assert "Retry-After" in second.headers
        assert int(second.headers["Retry-After"]) > 0

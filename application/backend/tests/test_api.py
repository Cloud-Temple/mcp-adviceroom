"""
Tests API — Endpoints REST (debates + providers).

Couvre :
- POST /api/v1/debates → création de débat (write)
- GET  /api/v1/debates → listing (read)
- GET  /api/v1/debates/:id → statut (read)
- GET  /api/v1/providers → listing des modèles (read)
- GET  /health → health check (public)

Tous les tests utilisent le TestClient FastAPI avec mocks.
Les routes authentifiées utilisent le bootstrap key par défaut (V1-01).

Ref: DESIGN/architecture.md §4.2.1
Sécurité: DESIGN/SECURITY_AUDIT_V1.md V1-01
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.services.llm.base import ModelConfig
from tests.conftest import TEST_AUTH_HEADERS


# ============================================================
# Mock configs complets pour tous les sous-modules
# ============================================================

MOCK_DEBATE_CONFIG = {
    "limits": {"max_participants": 5, "max_rounds": 3, "min_rounds": 2},
    "stability": {
        "threshold": 0.85,
        "weights": {"position_delta": 0.5, "confidence_delta": 0.3, "argument_novelty": 0.2},
        "confidence_instability_threshold": 30,
    },
    "anti_conformity": {"challenge_min_length": 20, "max_retries": 1},
    "error_handling": {
        "provider_timeout_seconds": 10, "skip_threshold": 3,
        "min_active_participants": 2,
    },
    "synthesizer": {"default_model": "claude-opus-46", "fallback_model": "gpt-52"},
    "context": {"sliding_window_rounds": 2, "summary_tokens_per_participant": 200},
    "streaming": {"chunk_flush_interval_ms": 50},
}

MOCK_PERSONAS_CONFIG = {
    "definitions": {
        "pragmatique": {"name": "Pragmatique", "description": "Analyse coût-bénéfice", "icon": "💼", "color": "#4CAF50"},
        "avocat_du_diable": {"name": "Avocat du diable", "description": "Conteste", "icon": "😈", "color": "#F44336"},
    },
    "auto_assignment": {2: ["pragmatique", "avocat_du_diable"]},
}

MOCK_PROMPTS = {
    "opening": {"system": "{persona_name} {persona_description} {n_participants}"},
    "debate": {"system": "{persona_name} {persona_description} {question} {user_answers_if_any} {formatted_previous_positions} {round_number} {user_question_instruction}"},
    "verdict": {"system": "{question} {user_answers} {formatted_opening_positions} {formatted_rounds}"},
    "challenge_retry": "{other_positions}",
}

MODEL_A = ModelConfig(id="model-a", display_name="Model A", provider="llmaas",
                      category="snc", api_model_id="model-a-api", active=True)
MODEL_B = ModelConfig(id="model-b", display_name="Model B", provider="llmaas",
                      category="snc", api_model_id="model-b-api", active=True)


@pytest.fixture
def mock_all():
    """Mock toutes les dépendances pour les tests API."""
    mock_router = MagicMock()
    mock_router.loaded = True
    mock_router.get_model_by_id.side_effect = lambda mid: {
        "model-a": MODEL_A, "model-b": MODEL_B
    }.get(mid)
    mock_router.get_provider.return_value = AsyncMock()
    mock_router.get_models_by_category.return_value = {
        "categories": {"snc": {"models": []}},
        "default_category": "snc",
    }
    mock_router.get_status.return_value = {"loaded": True}
    mock_router.models = {"model-a": MODEL_A, "model-b": MODEL_B}
    mock_router._providers = {"llmaas": MagicMock()}

    patches = [
        patch("app.services.llm.router.get_llm_router", return_value=mock_router),
        patch("app.services.llm.router.init_llm_router", return_value=mock_router),
        patch("app.routers.debates.get_orchestrator"),
        patch("app.services.debate.orchestrator.get_debate_config", return_value=MOCK_DEBATE_CONFIG),
        patch("app.services.debate.orchestrator.get_llm_router", return_value=mock_router),
        patch("app.services.debate.personas.get_personas", return_value=MOCK_PERSONAS_CONFIG),
        patch("app.services.debate.context_builder.get_prompts", return_value=MOCK_PROMPTS),
        patch("app.services.debate.context_builder.get_debate_config", return_value=MOCK_DEBATE_CONFIG),
        patch("app.services.debate.stability.get_debate_config", return_value=MOCK_DEBATE_CONFIG),
        patch("app.services.debate.verdict.get_debate_config", return_value=MOCK_DEBATE_CONFIG),
        # Skip MCP mounting during tests
        patch("app.mcp.tools.register_tools"),
    ]

    for p in patches:
        p.start()

    yield mock_router

    for p in patches:
        p.stop()


@pytest.fixture
def client(mock_all):
    """TestClient FastAPI avec toutes les dépendances mockées."""
    from app.main import app
    with TestClient(app) as c:
        yield c


# ============================================================
# Tests Health Check (public — pas d'auth requise)
# ============================================================

class TestHealthCheck:
    """Tests du health check endpoint."""

    def test_health_returns_ok(self, client):
        """GET /health → 200 OK (public, sans auth)."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "adviceroom"

    def test_health_includes_version(self, client):
        """Le health check inclut la version."""
        response = client.get("/health")
        data = response.json()
        assert "version" in data


# ============================================================
# Tests Auth — Vérifier que les routes rejettent sans token (V1-01)
# ============================================================

class TestAuthRequired:
    """Tests que toutes les routes API exigent un token valide."""

    def test_list_debates_without_token_returns_401(self, client):
        """GET /api/v1/debates sans token → 401."""
        response = client.get("/api/v1/debates")
        assert response.status_code == 401

    def test_list_providers_without_token_returns_401(self, client):
        """GET /api/v1/providers sans token → 401."""
        response = client.get("/api/v1/providers")
        assert response.status_code == 401

    def test_create_debate_without_token_returns_401(self, client):
        """POST /api/v1/debates sans token → 401."""
        response = client.post("/api/v1/debates", json={
            "question": "Test ?",
            "participants": [
                {"provider": "llmaas", "model": "model-a"},
                {"provider": "llmaas", "model": "model-b"},
            ],
        })
        assert response.status_code == 401


# ============================================================
# Tests Providers (avec auth)
# ============================================================

class TestProvidersAPI:
    """Tests de l'API providers."""

    def test_list_providers(self, client):
        """GET /api/v1/providers avec auth → 200 avec catégories."""
        response = client.get("/api/v1/providers", headers=TEST_AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data


# ============================================================
# Tests Debates — Create (avec auth)
# ============================================================

class TestDebateCreateAPI:
    """Tests de la création de débat via l'API."""

    def test_create_debate_returns_id(self, client, mock_all):
        """POST /api/v1/debates avec auth → 200 avec debate_id."""
        from app.services.debate.models import Debate, Participant

        mock_orch = MagicMock()
        debate = Debate(question="Test K8s ?")
        debate.participants = [
            Participant(id="a", model_id="model-a", provider="llmaas", display_name="A"),
            Participant(id="b", model_id="model-b", provider="llmaas", display_name="B"),
        ]
        mock_orch.create_debate.return_value = debate

        with patch("app.routers.debates.get_orchestrator", return_value=mock_orch):
            response = client.post(
                "/api/v1/debates",
                json={
                    "question": "Faut-il migrer vers K8s ?",
                    "participants": [
                        {"provider": "llmaas", "model": "model-a"},
                        {"provider": "llmaas", "model": "model-b"},
                    ],
                },
                headers=TEST_AUTH_HEADERS,  # V1-01
            )

        assert response.status_code == 200
        data = response.json()
        assert "debate_id" in data
        assert data["question"] == "Test K8s ?"
        assert data["participants"] == 2
        assert "/stream" in data["stream_url"]

    def test_create_debate_too_few_participants(self, client, mock_all):
        """POST avec < 2 participants valides → 400."""
        mock_orch = MagicMock()
        debate = MagicMock()
        debate.participants = [MagicMock()]
        mock_orch.create_debate.return_value = debate

        with patch("app.routers.debates.get_orchestrator", return_value=mock_orch):
            response = client.post(
                "/api/v1/debates",
                json={
                    "question": "Test question minimum ?",
                    "participants": [
                        {"provider": "llmaas", "model": "model-a"},
                        {"provider": "llmaas", "model": "model-b"},
                    ],
                },
                headers=TEST_AUTH_HEADERS,  # V1-01
            )

        assert response.status_code == 400


# ============================================================
# Tests Debates — List & Status (avec auth)
# ============================================================

class TestDebateListAPI:
    """Tests du listing des débats."""

    def test_list_empty(self, client):
        """GET /api/v1/debates avec auth → liste vide au démarrage."""
        from app.routers import debates
        debates._active_debates.clear()

        response = client.get("/api/v1/debates", headers=TEST_AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["debates"] == []

    def test_get_debate_not_found(self, client):
        """GET /api/v1/debates/:id non trouvé → 400 (UUID invalide)."""
        response = client.get(
            "/api/v1/debates/nonexistent",
            headers=TEST_AUTH_HEADERS,
        )
        # V1-03 : "nonexistent" n'est pas un UUID v4 → 400
        assert response.status_code == 400

    def test_get_debate_uuid_not_found(self, client):
        """GET /api/v1/debates/:uuid non trouvé → 404."""
        response = client.get(
            "/api/v1/debates/00000000-0000-0000-0000-000000000000",
            headers=TEST_AUTH_HEADERS,
        )
        assert response.status_code == 404

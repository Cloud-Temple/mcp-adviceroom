"""
Conftest — Fixtures partagées pour les tests AdviceRoom.

Fournit des fixtures réutilisables pour :
- Le config loader (mock des fichiers YAML)
- Des participants de test
- Des positions de test
"""
import pytest
from unittest.mock import patch

from app.services.debate.models import Participant


# ============================================================
# Auth helpers pour les tests (V1-01 : toutes les routes sont authentifiées)
# ============================================================

# Le bootstrap key par défaut dans settings.py
TEST_BOOTSTRAP_KEY = "changeme-in-production"
TEST_AUTH_HEADERS = {"Authorization": f"Bearer {TEST_BOOTSTRAP_KEY}"}


# ============================================================
# Données de test : config personas.yaml (identique au vrai fichier)
# ============================================================

MOCK_PERSONAS_CONFIG = {
    "definitions": {
        "pragmatique": {
            "name": "Pragmatique",
            "description": "Analyse coût-bénéfice, faisabilité, contraintes opérationnelles. Cherche la solution la plus réaliste.",
            "icon": "💼",
            "color": "#4CAF50",
        },
        "analyste_risques": {
            "name": "Analyste risques",
            "description": "Identifie les risques, les edge cases, les scénarios d'échec. Challenge les hypothèses optimistes.",
            "icon": "⚠️",
            "color": "#FF9800",
        },
        "expert_technique": {
            "name": "Expert technique",
            "description": "Plonge dans les détails techniques, la faisabilité d'implémentation, les trade-offs architecturaux.",
            "icon": "🔧",
            "color": "#2196F3",
        },
        "avocat_du_diable": {
            "name": "Avocat du diable",
            "description": "Conteste systématiquement la position dominante. Cherche les failles, les alternatives non considérées.",
            "icon": "😈",
            "color": "#F44336",
        },
        "visionnaire": {
            "name": "Visionnaire",
            "description": "Pense long terme, innovation, tendances. Propose des approches non conventionnelles.",
            "icon": "🔮",
            "color": "#9C27B0",
        },
    },
    "auto_assignment": {
        2: ["pragmatique", "avocat_du_diable"],
        3: ["pragmatique", "analyste_risques", "expert_technique"],
        4: ["pragmatique", "analyste_risques", "expert_technique", "avocat_du_diable"],
        5: ["pragmatique", "analyste_risques", "expert_technique", "avocat_du_diable", "visionnaire"],
    },
}


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_personas_config():
    """Mock du config loader pour personas.yaml."""
    with patch("app.services.debate.personas.get_personas", return_value=MOCK_PERSONAS_CONFIG):
        yield MOCK_PERSONAS_CONFIG


def make_participant(model_id: str, provider: str = "llmaas") -> Participant:
    """Helper : crée un Participant de test avec des valeurs par défaut."""
    return Participant(
        id=model_id,
        model_id=model_id,
        provider=provider,
        display_name=model_id.upper(),
    )


@pytest.fixture
def participants_2():
    """Fixture : 2 participants de test."""
    return [
        make_participant("gpt-oss-120b", "llmaas"),
        make_participant("claude-opus-46", "anthropic"),
    ]


@pytest.fixture
def participants_3():
    """Fixture : 3 participants de test."""
    return [
        make_participant("gpt-oss-120b", "llmaas"),
        make_participant("claude-opus-46", "anthropic"),
        make_participant("gemini-31-pro", "google"),
    ]


@pytest.fixture
def participants_5():
    """Fixture : 5 participants de test (max standard)."""
    return [
        make_participant("gpt-oss-120b", "llmaas"),
        make_participant("claude-opus-46", "anthropic"),
        make_participant("gemini-31-pro", "google"),
        make_participant("gpt-52", "openai"),
        make_participant("qwen35-27b", "llmaas"),
    ]

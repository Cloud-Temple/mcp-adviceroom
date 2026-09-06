"""
Conftest — Fixtures partagées pour les tests AdviceRoom.

Fournit des fixtures réutilisables pour :
- Le config loader (mock des fichiers YAML)
- Des participants de test
- Des positions de test
"""
import os

# ============================================================
# Auth helpers pour les tests (V1-01 : toutes les routes sont authentifiées)
# ============================================================

# Clé de bootstrap propre aux tests. Elle est INJECTÉE dans l'environnement,
# et non héritée d'un défaut de settings.py : ce défaut valait auparavant
# "changeme-in-production", et les tests s'authentifiaient donc avec la valeur
# vulnérable elle-même. Supprimer ce défaut aurait fait échouer la suite.
#
# L'injection est FORCÉE (et non setdefault) pour que les tests soient
# déterministes quel que soit l'environnement : sans cela, un .env de
# déploiement portant une vraie ADMIN_BOOTSTRAP_KEY faisait échouer en 401 tous
# les tests d'API — c'était le cas en exécution Docker.
#
# Doit précéder tout import de `app.*` : get_settings() est @lru_cache, donc la
# première lecture de l'environnement est définitive.
TEST_BOOTSTRAP_KEY = "test-bootstrap-key-not-for-production"
os.environ["ADMIN_BOOTSTRAP_KEY"] = TEST_BOOTSTRAP_KEY
os.environ.pop("ADVICEROOM_BOOTSTRAP_KEY", None)  # alias legacy, sinon prioritaire

TEST_AUTH_HEADERS = {"Authorization": f"Bearer {TEST_BOOTSTRAP_KEY}"}

import pytest  # noqa: E402
from unittest.mock import patch  # noqa: E402

from app.config.settings import get_settings  # noqa: E402
from app.services.debate.models import Participant  # noqa: E402

# Le cache a pu être amorcé par un import antérieur (collecte pytest) : on le
# vide pour que la clé de test ci-dessus soit bien celle qui s'applique.
get_settings.cache_clear()


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
        make_participant("gpt-54", "openai"),
        make_participant("qwen35-27b", "llmaas"),
    ]

"""
Tests StabilityDetector — Détection de stabilité pour arrêt adaptatif.

Couvre :
- Score parfaitement stable (mêmes positions, mêmes args, mêmes confidences)
- Score instable (positions changent, confidences bougent, nouveaux args)
- Score intermédiaire (mix)
- Min rounds : stable mais trop tôt → can_stop = False
- Premier round sans historique → instable
- Sérialisation to_dict pour NDJSON
- Heuristique de similarité des thèses

Ref: DESIGN/architecture.md §13
"""
import pytest
from unittest.mock import patch

from app.services.debate.stability import StabilityDetector, StabilityResult
from app.services.debate.models import (
    Debate,
    DebatePhase,
    Position,
    Round,
    Turn,
)


# ============================================================
# Mock config debate.yaml
# ============================================================

MOCK_DEBATE_CONFIG = {
    "stability": {
        "threshold": 0.85,
        "weights": {
            "position_delta": 0.5,
            "confidence_delta": 0.3,
            "argument_novelty": 0.2,
        },
        "confidence_instability_threshold": 30,
    },
    "limits": {
        "min_rounds": 2,
        "max_rounds": 5,
    },
}


@pytest.fixture
def mock_stability_config():
    """Mock de debate.yaml pour StabilityDetector."""
    with patch(
        "app.services.debate.stability.get_debate_config",
        return_value=MOCK_DEBATE_CONFIG,
    ):
        yield


# ============================================================
# Helpers
# ============================================================

def make_round(
    number: int,
    participants: list[tuple[str, str, int, list[str]]],
) -> Round:
    """
    Helper : crée un Round avec des positions structurées.

    Args:
        number: Numéro du round.
        participants: Liste de (id, thesis, confidence, arguments).
    """
    turns = []
    for pid, thesis, confidence, arguments in participants:
        pos = Position(
            thesis=thesis,
            confidence=confidence,
            arguments=arguments,
        )
        turns.append(Turn(
            participant_id=pid,
            round_number=number,
            phase=DebatePhase.DEBATE,
            structured_position=pos,
        ))
    return Round(number=number, turns=turns)


def make_stable_debate() -> Debate:
    """
    Crée un débat parfaitement stable : mêmes thèses, mêmes args,
    mêmes confidences entre round 1 et round 2.
    """
    debate = Debate(question="Test ?")
    debate.rounds = [
        make_round(1, [
            ("llm-a", "Pour la migration", 80, ["TCO", "scalabilité"]),
            ("llm-b", "Contre la migration", 60, ["risque", "coût"]),
        ]),
        make_round(2, [
            ("llm-a", "Pour la migration", 80, ["TCO", "scalabilité"]),
            ("llm-b", "Contre la migration", 60, ["risque", "coût"]),
        ]),
    ]
    return debate


def make_unstable_debate() -> Debate:
    """
    Crée un débat très instable : thèses différentes, confidences
    qui bougent de 30+ points, arguments nouveaux.
    """
    debate = Debate(question="Test ?")
    debate.rounds = [
        make_round(1, [
            ("llm-a", "Pour la migration", 80, ["TCO", "scalabilité"]),
            ("llm-b", "Contre la migration", 60, ["risque", "coût"]),
        ]),
        make_round(2, [
            ("llm-a", "Contre la migration finalement", 30, ["sécurité", "complexité"]),
            ("llm-b", "Pour la migration finalement", 90, ["innovation", "performance"]),
        ]),
    ]
    return debate


# ============================================================
# Tests StabilityResult
# ============================================================

class TestStabilityResult:
    """Tests de la dataclass StabilityResult."""

    def test_stable_above_threshold(self):
        """Score ≥ seuil → is_stable = True."""
        result = StabilityResult(score=0.90, threshold=0.85,
                                 round_number=3, min_rounds=2)
        assert result.is_stable is True

    def test_unstable_below_threshold(self):
        """Score < seuil → is_stable = False."""
        result = StabilityResult(score=0.50, threshold=0.85,
                                 round_number=3, min_rounds=2)
        assert result.is_stable is False

    def test_can_stop_requires_min_rounds(self):
        """can_stop = True seulement si stable ET round ≥ min_rounds."""
        result = StabilityResult(score=0.90, threshold=0.85,
                                 round_number=1, min_rounds=2)
        assert result.is_stable is True
        assert result.can_stop is False  # round 1 < min_rounds 2

    def test_can_stop_true(self):
        """Stable + enough rounds → can_stop = True."""
        result = StabilityResult(score=0.90, threshold=0.85,
                                 round_number=3, min_rounds=2)
        assert result.can_stop is True

    def test_to_dict(self):
        """Sérialisation en dict pour NDJSON."""
        result = StabilityResult(
            score=0.876, threshold=0.85,
            round_number=2, min_rounds=2,
            details={"position_delta": 1.0, "confidence_delta": 0.8},
        )
        d = result.to_dict()
        assert d["score"] == 0.876
        assert d["is_stable"] is True
        assert d["can_stop"] is True
        assert d["round"] == 2
        assert "position_delta" in d["details"]

    def test_repr(self):
        """__repr__ ne crashe pas."""
        result = StabilityResult(score=0.5, threshold=0.85,
                                 round_number=1, min_rounds=2)
        assert "INSTABLE" in repr(result)


# ============================================================
# Tests du détecteur
# ============================================================

class TestStabilityDetectorEvaluation:
    """Tests de l'évaluation de stabilité."""

    def test_perfectly_stable(self, mock_stability_config):
        """Débat stable → score élevé, can_stop = True."""
        detector = StabilityDetector()
        debate = make_stable_debate()
        result = detector.evaluate(debate, round_number=2)

        assert result.score >= 0.85
        assert result.is_stable is True
        assert result.can_stop is True  # round 2 ≥ min_rounds 2

    def test_very_unstable(self, mock_stability_config):
        """Débat instable → score bas, can_stop = False."""
        detector = StabilityDetector()
        debate = make_unstable_debate()
        result = detector.evaluate(debate, round_number=2)

        assert result.score < 0.85
        assert result.is_stable is False
        assert result.can_stop is False

    def test_first_round_instable(self, mock_stability_config):
        """Premier round (pas de round précédent) → score = 0."""
        detector = StabilityDetector()
        debate = Debate(question="Test ?")
        debate.rounds = [
            make_round(1, [
                ("llm-a", "Position A", 80, ["arg1"]),
            ]),
        ]
        result = detector.evaluate(debate, round_number=1)
        assert result.score == 0.0
        assert result.can_stop is False

    def test_stable_but_too_early(self, mock_stability_config):
        """Stable dès le round 1 → can_stop = False (min_rounds = 2)."""
        detector = StabilityDetector()
        # On triche : mettre un round 0 et round 1 identiques
        debate = Debate(question="Test ?")
        debate.rounds = [
            make_round(0, [
                ("llm-a", "Même position", 80, ["arg1"]),
            ]),
            make_round(1, [
                ("llm-a", "Même position", 80, ["arg1"]),
            ]),
        ]
        result = detector.evaluate(debate, round_number=1)
        # Stable mais round 1 < min_rounds 2
        assert result.is_stable is True
        assert result.can_stop is False


# ============================================================
# Tests des métriques individuelles
# ============================================================

class TestPositionDelta:
    """Tests de la métrique position_delta."""

    def test_same_thesis_score_1(self, mock_stability_config):
        """Mêmes thèses → score = 1.0."""
        detector = StabilityDetector()
        r1 = make_round(1, [("a", "Pour K8s", 80, [])])
        r2 = make_round(2, [("a", "Pour K8s", 80, [])])
        assert detector._position_delta_score(r2, r1) == 1.0

    def test_different_thesis_score_0(self, mock_stability_config):
        """Thèses totalement différentes → score = 0.0."""
        detector = StabilityDetector()
        r1 = make_round(1, [("a", "Pour la migration cloud", 80, [])])
        r2 = make_round(2, [("a", "Contre tout changement radical", 80, [])])
        assert detector._position_delta_score(r2, r1) == 0.0

    def test_similar_thesis_score_high(self, mock_stability_config):
        """Thèses similaires (mêmes mots clés) → score élevé."""
        detector = StabilityDetector()
        r1 = make_round(1, [("a", "La migration vers Kubernetes est bénéfique", 80, [])])
        r2 = make_round(2, [("a", "La migration vers Kubernetes reste bénéfique", 80, [])])
        score = detector._position_delta_score(r2, r1)
        assert score > 0.5  # Thèses très similaires


class TestConfidenceDelta:
    """Tests de la métrique confidence_delta."""

    def test_no_change_score_1(self, mock_stability_config):
        """Même confidence → score = 1.0."""
        detector = StabilityDetector()
        r1 = make_round(1, [("a", "T", 80, [])])
        r2 = make_round(2, [("a", "T", 80, [])])
        assert detector._confidence_delta_score(r2, r1) == 1.0

    def test_huge_change_score_low(self, mock_stability_config):
        """Variation de 30+ points → score ≤ 0.0 (clampé)."""
        detector = StabilityDetector()
        r1 = make_round(1, [("a", "T", 80, [])])
        r2 = make_round(2, [("a", "T", 20, [])])  # Delta = 60
        score = detector._confidence_delta_score(r2, r1)
        assert score == 0.0  # Clampé à 0

    def test_small_change_score_high(self, mock_stability_config):
        """Petite variation (5 points) → score élevé."""
        detector = StabilityDetector()
        r1 = make_round(1, [("a", "T", 80, [])])
        r2 = make_round(2, [("a", "T", 75, [])])  # Delta = 5
        score = detector._confidence_delta_score(r2, r1)
        # 1 - 5/30 = 0.833
        assert score > 0.8


class TestArgumentNovelty:
    """Tests de la métrique argument_novelty."""

    def test_same_args_score_1(self, mock_stability_config):
        """Mêmes arguments → score = 1.0 (rien de nouveau)."""
        detector = StabilityDetector()
        r1 = make_round(1, [("a", "T", 80, ["TCO", "scalabilité"])])
        r2 = make_round(2, [("a", "T", 80, ["TCO", "scalabilité"])])
        assert detector._argument_novelty_score(r2, r1) == 1.0

    def test_all_new_args_score_0(self, mock_stability_config):
        """Tous les arguments sont nouveaux → score = 0.0."""
        detector = StabilityDetector()
        r1 = make_round(1, [("a", "T", 80, ["TCO", "scalabilité"])])
        r2 = make_round(2, [("a", "T", 80, ["sécurité", "compliance"])])
        assert detector._argument_novelty_score(r2, r1) == 0.0


# ============================================================
# Tests de l'heuristique de similarité
# ============================================================

class TestThesesSimilar:
    """Tests de _theses_similar."""

    def test_identical(self, mock_stability_config):
        """Thèses identiques → True."""
        assert StabilityDetector._theses_similar("Pour K8s", "Pour K8s") is True

    def test_empty_both(self, mock_stability_config):
        """Deux chaînes vides → True."""
        assert StabilityDetector._theses_similar("", "") is True

    def test_one_empty(self, mock_stability_config):
        """Une chaîne vide → False."""
        assert StabilityDetector._theses_similar("", "Pour K8s") is False

    def test_totally_different(self, mock_stability_config):
        """Thèses sans aucun mot commun → False."""
        assert StabilityDetector._theses_similar(
            "Migration cloud immédiate", "Rester monolithique toujours"
        ) is False

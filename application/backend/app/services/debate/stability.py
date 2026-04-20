"""
StabilityDetector — Détection de stabilité pour arrêt adaptatif du débat.

Calcule un score de stabilité après chaque round pour déterminer si les
positions ont convergé (ou divergé de manière stable). Si le score dépasse
le seuil configuré ET que le minimum de rounds est atteint, le débat
peut passer à la phase Verdict.

3 métriques pondérées (§13 architecture.md) :
1. Position delta : les thèses ont-elles changé entre les 2 derniers rounds ?
2. Confidence delta : les niveaux de confiance ont-ils bougé ?
3. Argument novelty : y a-t-il de nouveaux arguments significatifs ?

Approche simplifiée par heuristiques, inspirée du Beta-Binomial+KS
(papier [3] Stability Detection, arXiv 2510.12697).

Ref: DESIGN/architecture.md §13
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    Debate,
    Position,
    Round,
    Turn,
)
from ...config.loader import get_debate_config

logger = logging.getLogger(__name__)

__all__ = ["StabilityDetector", "StabilityResult"]


# ============================================================
# Résultat de la détection
# ============================================================

class StabilityResult:
    """
    Résultat du calcul de stabilité d'un round.

    Attributes:
        score: Score composite (0.0 = très instable, 1.0 = parfaitement stable)
        is_stable: True si le débat est considéré stable (score ≥ seuil)
        can_stop: True si stable ET minimum de rounds atteint
        details: Détails par métrique (pour le logging/debugging)
    """

    def __init__(
        self,
        score: float,
        threshold: float,
        round_number: int,
        min_rounds: int,
        details: Optional[Dict[str, float]] = None,
    ) -> None:
        self.score = score
        self.threshold = threshold
        self.round_number = round_number
        self.min_rounds = min_rounds
        self.is_stable = score >= threshold
        self.can_stop = self.is_stable and round_number >= min_rounds
        self.details = details or {}

    def __repr__(self) -> str:
        status = "STABLE ✓" if self.can_stop else "INSTABLE"
        return (
            f"StabilityResult({status}, score={self.score:.3f}, "
            f"threshold={self.threshold}, round={self.round_number})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise pour l'événement NDJSON 'stability'."""
        return {
            "score": round(self.score, 3),
            "threshold": self.threshold,
            "is_stable": self.is_stable,
            "can_stop": self.can_stop,
            "round": self.round_number,
            "details": {
                k: round(v, 3) if isinstance(v, (int, float)) else v
                for k, v in self.details.items()
            },
        }


# ============================================================
# StabilityDetector
# ============================================================

class StabilityDetector:
    """
    Détecte quand le débat est stable et peut passer au verdict.

    Le score de stabilité combine 3 métriques pondérées :
    - position_delta (poids 0.5) : changement de thèse entre rounds
    - confidence_delta (poids 0.3) : variation de confiance
    - argument_novelty (poids 0.2) : proportion de nouveaux arguments

    Chaque métrique retourne un score entre 0 (très instable) et 1 (stable).
    Le score composite est la somme pondérée.

    Usage :
        detector = StabilityDetector()
        result = detector.evaluate(debate, round_number=3)
        if result.can_stop:
            # → Phase Verdict
    """

    def __init__(self) -> None:
        """Charge les paramètres de stabilité depuis debate.yaml."""
        config = get_debate_config()
        stability_cfg = config.get("stability", {})
        limits_cfg = config.get("limits", {})

        # Seuil de stabilité
        self._threshold: float = stability_cfg.get("threshold", 0.85)

        # Poids des métriques
        weights = stability_cfg.get("weights", {})
        self._w_position: float = weights.get("position_delta", 0.5)
        self._w_confidence: float = weights.get("confidence_delta", 0.3)
        self._w_novelty: float = weights.get("argument_novelty", 0.2)

        # Seuil d'instabilité de confiance (variation > X points = instable)
        self._confidence_instability: int = stability_cfg.get(
            "confidence_instability_threshold", 30
        )

        # Minimum de rounds avant arrêt
        self._min_rounds: int = limits_cfg.get("min_rounds", 2)

        logger.info(
            f"✓ StabilityDetector chargé : seuil={self._threshold}, "
            f"poids=[pos={self._w_position}, conf={self._w_confidence}, "
            f"novelty={self._w_novelty}], min_rounds={self._min_rounds}"
        )

    # ─── Évaluation principale ───────────────────────────────

    def evaluate(self, debate: Debate, round_number: int) -> StabilityResult:
        """
        Évalue la stabilité du débat après un round.

        Compare le round courant avec le round précédent pour calculer
        les 3 métriques de stabilité.

        Args:
            debate: L'objet Debate complet.
            round_number: Numéro du round qui vient de se terminer.

        Returns:
            StabilityResult avec le score et la décision.
        """
        # Récupérer le round courant et le précédent
        current_round = self._get_round(debate, round_number)
        previous_round = self._get_round(debate, round_number - 1)

        # Pas de round précédent → instable (premier round)
        if not current_round or not previous_round:
            return StabilityResult(
                score=0.0,
                threshold=self._threshold,
                round_number=round_number,
                min_rounds=self._min_rounds,
                details={"position_delta": 0.0, "confidence_delta": 0.0,
                         "argument_novelty": 0.0, "reason": "no_previous_round"},
            )

        # Calculer les 3 métriques
        pos_score = self._position_delta_score(current_round, previous_round)
        conf_score = self._confidence_delta_score(current_round, previous_round)
        novelty_score = self._argument_novelty_score(current_round, previous_round)

        # Score composite pondéré
        composite = (
            self._w_position * pos_score
            + self._w_confidence * conf_score
            + self._w_novelty * novelty_score
        )

        result = StabilityResult(
            score=composite,
            threshold=self._threshold,
            round_number=round_number,
            min_rounds=self._min_rounds,
            details={
                "position_delta": pos_score,
                "confidence_delta": conf_score,
                "argument_novelty": novelty_score,
            },
        )

        logger.info(
            f"📊 Stabilité round {round_number} : {result.score:.3f} "
            f"(seuil={self._threshold}) — "
            f"pos={pos_score:.2f} conf={conf_score:.2f} novelty={novelty_score:.2f} — "
            f"{'STABLE ✓' if result.can_stop else 'CONTINUER'}"
        )

        return result

    # ─── Métrique 1 : Position Delta (poids 0.5) ────────────

    def _position_delta_score(
        self, current: Round, previous: Round
    ) -> float:
        """
        Mesure le changement de thèse entre deux rounds.

        Compare les thèses de chaque participant. Si toutes les thèses
        sont identiques (ou très similaires), score = 1.0 (stable).

        Heuristique simple : pourcentage de participants dont la thèse
        n'a pas changé entre les deux rounds.

        Returns:
            Score entre 0.0 (tout a changé) et 1.0 (rien n'a changé).
        """
        current_positions = self._extract_positions(current)
        previous_positions = self._extract_positions(previous)

        if not current_positions:
            return 0.0

        same_count = 0
        total = len(current_positions)

        for pid, cur_pos in current_positions.items():
            prev_pos = previous_positions.get(pid)
            if prev_pos and self._theses_similar(cur_pos.thesis, prev_pos.thesis):
                same_count += 1

        return same_count / total if total > 0 else 0.0

    # ─── Métrique 2 : Confidence Delta (poids 0.3) ──────────

    def _confidence_delta_score(
        self, current: Round, previous: Round
    ) -> float:
        """
        Mesure la variation de confiance entre deux rounds.

        Si les confidences n'ont pas bougé significativement, le débat
        est stable sur cet axe. Une variation > seuil = instable.

        Returns:
            Score entre 0.0 (très instable) et 1.0 (parfaitement stable).
        """
        current_positions = self._extract_positions(current)
        previous_positions = self._extract_positions(previous)

        if not current_positions:
            return 0.0

        deltas = []
        for pid, cur_pos in current_positions.items():
            prev_pos = previous_positions.get(pid)
            if prev_pos:
                delta = abs(cur_pos.confidence - prev_pos.confidence)
                deltas.append(delta)

        if not deltas:
            return 0.0

        # Score : 1 - (moyenne des deltas normalisée par le seuil d'instabilité)
        avg_delta = sum(deltas) / len(deltas)
        score = max(0.0, 1.0 - (avg_delta / self._confidence_instability))
        return score

    # ─── Métrique 3 : Argument Novelty (poids 0.2) ──────────

    def _argument_novelty_score(
        self, current: Round, previous: Round
    ) -> float:
        """
        Mesure la proportion de nouveaux arguments dans le round courant.

        Si les participants ne font que répéter les mêmes arguments,
        le débat est stable. Si de nouveaux arguments apparaissent, il évolue.

        Returns:
            Score entre 0.0 (tout est nouveau) et 1.0 (rien de nouveau).
        """
        current_positions = self._extract_positions(current)
        previous_positions = self._extract_positions(previous)

        if not current_positions:
            return 0.0

        # Collecter tous les arguments du round précédent
        prev_args = set()
        for pos in previous_positions.values():
            for arg in pos.arguments:
                prev_args.add(arg.lower().strip())

        if not prev_args:
            return 0.0  # Pas d'arguments précédents → tout est nouveau

        # Compter les arguments du round courant déjà vus
        total_args = 0
        seen_args = 0
        for pos in current_positions.values():
            for arg in pos.arguments:
                total_args += 1
                if arg.lower().strip() in prev_args:
                    seen_args += 1

        # Score = proportion d'arguments déjà vus
        return seen_args / total_args if total_args > 0 else 1.0

    # ─── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _get_round(debate: Debate, round_number: int) -> Optional[Round]:
        """Récupère un round par son numéro, ou None."""
        for rnd in debate.rounds:
            if rnd.number == round_number:
                return rnd
        return None

    @staticmethod
    def _extract_positions(rnd: Round) -> Dict[str, Position]:
        """Extrait les positions structurées de chaque participant d'un round."""
        positions = {}
        for turn in rnd.turns:
            if turn.structured_position:
                positions[turn.participant_id] = turn.structured_position
        return positions

    @staticmethod
    def _theses_similar(thesis_a: str, thesis_b: str) -> bool:
        """
        Heuristique simple : deux thèses sont similaires si elles
        partagent >70% de leurs mots significatifs (>3 chars).

        Pour une v2, on pourrait utiliser des embeddings ou un LLM
        pour comparer les thèses sémantiquement.
        """
        if not thesis_a or not thesis_b:
            return thesis_a == thesis_b

        words_a = {w.lower() for w in thesis_a.split() if len(w) > 3}
        words_b = {w.lower() for w in thesis_b.split() if len(w) > 3}

        if not words_a or not words_b:
            return thesis_a.lower().strip() == thesis_b.lower().strip()

        intersection = words_a & words_b
        union = words_a | words_b
        jaccard = len(intersection) / len(union)

        return jaccard > 0.7

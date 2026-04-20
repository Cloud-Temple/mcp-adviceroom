"""
Tests Parser — Parsing des réponses LLM avec marqueurs YAML.

Couvre :
- parse_position : extraction ---POSITION--- / ---END---
- parse_verdict : extraction ---VERDICT--- / ---END---
- parse_challenge : extraction ---CHALLENGE--- / ---END---
- parse_user_question : extraction ---USER_QUESTION--- / ---END---
- Fallback quand le bloc structuré est absent
- YAML invalide → fallback gracieux
- Évaluation de la qualité du challenge (substantive/superficial/absent)

Ref: DESIGN/architecture.md §12.6
"""
import pytest

from app.services.debate.parser import (
    parse_position,
    parse_verdict,
    parse_challenge,
    parse_user_question,
)
from app.services.debate.models import ChallengeQuality


# ============================================================
# Tests parse_position
# ============================================================

class TestParsePosition:
    """Tests du parsing ---POSITION---."""

    def test_valid_position(self):
        """Bloc POSITION valide → prose + Position structurée."""
        text = """
Mon analyse détaillée de la situation...

---POSITION---
thesis: La migration K8s est bénéfique
confidence: 85
arguments:
- Réduction du TCO de 30%
- Scalabilité automatique
- Standardisation des déploiements
---END---
"""
        prose, position = parse_position(text)
        assert "analyse détaillée" in prose
        assert position.thesis == "La migration K8s est bénéfique"
        assert position.confidence == 85
        assert len(position.arguments) == 3
        assert "TCO" in position.arguments[0]

    def test_position_with_challenge(self):
        """Position avec champs challenge → qualité évaluée."""
        text = """
Réponse au round 2...

---POSITION---
thesis: Pour K8s
confidence: 80
arguments:
- TCO favorable
challenged: llm-b
challenge_target: Le risque de complexité
challenge_reason: La complexité est largement gérée par les opérateurs Kubernetes modernes qui automatisent les tâches opérationnelles
---END---
"""
        prose, position = parse_position(text)
        assert position.challenged == "llm-b"
        assert position.challenge_target == "Le risque de complexité"
        assert position.challenge_quality == ChallengeQuality.SUBSTANTIVE

    def test_superficial_challenge(self):
        """Challenge court (< 50 chars mais ≥ 20) → SUPERFICIAL."""
        text = """
---POSITION---
thesis: Pour
confidence: 70
arguments: []
challenged: llm-b
challenge_reason: Argument pas convaincant
---END---
"""
        _, position = parse_position(text)
        assert position.challenge_quality == ChallengeQuality.SUPERFICIAL

    def test_no_challenge(self):
        """Pas de challenge → ABSENT."""
        text = """
---POSITION---
thesis: Pour
confidence: 70
arguments:
- Un argument
---END---
"""
        _, position = parse_position(text)
        assert position.challenge_quality == ChallengeQuality.ABSENT

    def test_no_position_block(self):
        """Pas de bloc ---POSITION--- → fallback avec thesis 'Non structuré'."""
        text = "Juste du texte libre sans structure."
        prose, position = parse_position(text)
        assert prose == text.strip()
        assert position.thesis == "Non structuré"
        assert position.confidence == 50

    def test_invalid_yaml(self):
        """YAML invalide dans le bloc → fallback."""
        text = """
---POSITION---
[ceci n'est pas du yaml valide: {{
---END---
"""
        prose, position = parse_position(text)
        assert position.thesis == "Parsing échoué"

    def test_position_with_agrees_disagrees(self):
        """Position avec accords et désaccords."""
        text = """
---POSITION---
thesis: Position nuancée
confidence: 65
arguments:
- Argument principal
agrees_with:
  llm-a: Sur le point TCO
disagrees_with:
  llm-b: Sur le risque sécurité
---END---
"""
        _, position = parse_position(text)
        assert "llm-a" in position.agrees_with
        assert "llm-b" in position.disagrees_with


# ============================================================
# Tests parse_verdict
# ============================================================

class TestParseVerdict:
    """Tests du parsing ---VERDICT---."""

    def test_valid_verdict(self):
        """Bloc VERDICT valide → prose + verdict dict."""
        text = """
Analyse de la trajectoire du débat...

---VERDICT---
verdict: consensus
confidence: 85
summary: |
  Les participants convergent.
agreement_points:
- Point 1
- Point 2
recommendation: |
  Migrer par étapes.
---END---
"""
        prose, verdict = parse_verdict(text)
        assert "trajectoire" in prose
        assert verdict["verdict"] == "consensus"
        assert verdict["confidence"] == 85
        assert len(verdict["agreement_points"]) == 2

    def test_dissensus_verdict(self):
        """Verdict dissensus avec divergence_points."""
        text = """
---VERDICT---
verdict: dissensus
confidence: 70
summary: Pas de consensus
divergence_points:
- topic: Migration
  camp_a:
    position: Pour
  camp_b:
    position: Contre
---END---
"""
        _, verdict = parse_verdict(text)
        assert verdict["verdict"] == "dissensus"
        assert len(verdict["divergence_points"]) == 1

    def test_no_verdict_block(self):
        """Pas de bloc ---VERDICT--- → verdict error."""
        text = "Juste du texte."
        prose, verdict = parse_verdict(text)
        assert verdict["verdict"] == "error"
        assert verdict["confidence"] == 0


# ============================================================
# Tests parse_challenge
# ============================================================

class TestParseChallenge:
    """Tests du parsing ---CHALLENGE--- (retry anti-conformité)."""

    def test_valid_challenge(self):
        """Bloc CHALLENGE valide → dict avec les 3 champs."""
        text = """
---CHALLENGE---
challenged: llm-b
challenge_target: L'argument sur le coût
challenge_reason: Le coût est sous-estimé car il ne prend pas en compte la formation
---END---
"""
        result = parse_challenge(text)
        assert result is not None
        assert result["challenged"] == "llm-b"
        assert "coût" in result["challenge_reason"]

    def test_no_challenge_block(self):
        """Pas de bloc ---CHALLENGE--- → None."""
        result = parse_challenge("Pas de challenge ici.")
        assert result is None

    def test_invalid_yaml_challenge(self):
        """YAML invalide dans le challenge → None."""
        text = """
---CHALLENGE---
[pas du yaml valide
---END---
"""
        result = parse_challenge(text)
        assert result is None


# ============================================================
# Tests parse_user_question
# ============================================================

class TestParseUserQuestion:
    """Tests du parsing ---USER_QUESTION---."""

    def test_valid_question(self):
        """Bloc USER_QUESTION valide → question extraite."""
        text = """
Mon analyse...

---USER_QUESTION---
Quel est le budget annuel pour l'infrastructure ?
---END---
"""
        question = parse_user_question(text)
        assert question is not None
        assert "budget" in question

    def test_no_question(self):
        """Pas de bloc USER_QUESTION → None."""
        result = parse_user_question("Pas de question ici.")
        assert result is None

    def test_question_with_markdown(self):
        """Question contenant du markdown → extraite telle quelle."""
        text = """
---USER_QUESTION---
Pouvez-vous préciser :
1. Le nombre de serveurs
2. Le budget mensuel
---END---
"""
        question = parse_user_question(text)
        assert question is not None
        assert "nombre de serveurs" in question

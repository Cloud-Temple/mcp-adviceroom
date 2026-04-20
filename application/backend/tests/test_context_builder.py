"""
Tests ContextBuilder — Construction du contexte pour chaque tour de parole.

Couvre :
- Opening : system prompt + question, injection du persona
- Debate : positions précédentes, context window (glissant/résumé)
- Verdict : trajectoire complète pour le synthétiseur
- Challenge retry : prompt de retry anti-conformité
- Formatage des positions, résumé des rounds anciens
- User answers dans le contexte

Ref: DESIGN/architecture.md §3.2-§3.4, §12, §16
"""
import pytest
from unittest.mock import patch

from app.services.debate.context_builder import ContextBuilder
from app.services.debate.models import (
    Debate,
    DebatePhase,
    DebateStatus,
    Participant,
    Position,
    Round,
    Turn,
    UserAnswer,
)
from tests.conftest import make_participant


# ============================================================
# Mock configs (prompts.yaml + debate.yaml)
# ============================================================

MOCK_PROMPTS = {
    "opening": {
        "system": (
            "Tu es {persona_name} — {persona_description}\n"
            "Débat avec {n_participants} participants."
        ),
    },
    "debate": {
        "system": (
            "Tu es {persona_name} — {persona_description}\n"
            "Question: {question}\n"
            "{user_answers_if_any}\n"
            "Positions:\n{formatted_previous_positions}\n"
            "Round {round_number}\n"
            "{user_question_instruction}"
        ),
    },
    "verdict": {
        "system": (
            "Verdict pour: {question}\n"
            "Réponses user: {user_answers}\n"
            "Opening:\n{formatted_opening_positions}\n"
            "Rounds:\n{formatted_rounds}"
        ),
    },
    "challenge_retry": (
        "Challenge obligatoire.\n"
        "Positions des autres:\n{other_positions}"
    ),
}

MOCK_DEBATE_CONFIG = {
    "context": {
        "sliding_window_rounds": 2,
        "summary_tokens_per_participant": 200,
    },
}


@pytest.fixture
def mock_context_config():
    """Mock des configs prompts.yaml et debate.yaml pour ContextBuilder."""
    with patch("app.services.debate.context_builder.get_prompts", return_value=MOCK_PROMPTS), \
         patch("app.services.debate.context_builder.get_debate_config", return_value=MOCK_DEBATE_CONFIG):
        yield


# ============================================================
# Helpers pour créer des données de test
# ============================================================

def make_turn(
    participant_id: str,
    round_number: int,
    phase: DebatePhase = DebatePhase.DEBATE,
    thesis: str = "Ma position",
    confidence: int = 75,
    arguments: list = None,
    content: str = "Analyse détaillée...",
    challenged: str = None,
    challenge_reason: str = None,
) -> Turn:
    """Helper : crée un Turn de test avec une Position structurée."""
    pos = Position(
        thesis=thesis,
        confidence=confidence,
        arguments=arguments or ["arg1", "arg2"],
        challenged=challenged,
        challenge_reason=challenge_reason,
    )
    return Turn(
        participant_id=participant_id,
        round_number=round_number,
        phase=phase,
        content=content,
        structured_position=pos,
    )


def make_debate_with_rounds(n_rounds: int) -> Debate:
    """Helper : crée un Debate avec N rounds et 2 participants."""
    debate = Debate(question="Faut-il migrer vers Kubernetes ?")

    # Opening turns
    debate.opening_turns = [
        make_turn("llm-a", 0, DebatePhase.OPENING, thesis="Pour K8s", confidence=80),
        make_turn("llm-b", 0, DebatePhase.OPENING, thesis="Contre K8s", confidence=70),
    ]

    # Rounds de débat
    for r in range(1, n_rounds + 1):
        rnd = Round(number=r, turns=[
            make_turn(
                "llm-a", r, thesis=f"Position A round {r}",
                confidence=80 + r, challenged="llm-b",
                challenge_reason=f"Argument faible round {r}",
            ),
            make_turn(
                "llm-b", r, thesis=f"Position B round {r}",
                confidence=70 - r, challenged="llm-a",
                challenge_reason=f"Contre-argument round {r}",
            ),
        ])
        debate.rounds.append(rnd)

    return debate


# ============================================================
# Tests Opening
# ============================================================

class TestBuildOpeningMessages:
    """Tests de la construction des messages pour la phase opening."""

    def test_opening_returns_2_messages(self, mock_context_config):
        """Opening produit exactement 2 messages : system + user."""
        builder = ContextBuilder()
        participant = make_participant("llm-a")
        participant.persona_name = "Pragmatique"
        participant.persona_description = "Analyse coût-bénéfice"

        messages = builder.build_opening_messages(participant, "Ma question ?", 3)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_opening_injects_persona(self, mock_context_config):
        """Le system prompt contient le persona du participant."""
        builder = ContextBuilder()
        participant = make_participant("llm-a")
        participant.persona_name = "Avocat du diable"
        participant.persona_description = "Conteste systématiquement"

        messages = builder.build_opening_messages(participant, "Question ?", 2)
        system = messages[0]["content"]
        assert "Avocat du diable" in system
        assert "Conteste systématiquement" in system

    def test_opening_injects_n_participants(self, mock_context_config):
        """Le system prompt contient le nombre de participants."""
        builder = ContextBuilder()
        participant = make_participant("llm-a")
        participant.persona_name = "Test"
        participant.persona_description = "Desc"

        messages = builder.build_opening_messages(participant, "Q?", 5)
        assert "5" in messages[0]["content"]

    def test_opening_user_message_is_question(self, mock_context_config):
        """Le message user est la question originale."""
        builder = ContextBuilder()
        participant = make_participant("llm-a")
        participant.persona_name = "Test"
        participant.persona_description = "Desc"

        messages = builder.build_opening_messages(
            participant, "Faut-il migrer vers K8s ?", 3
        )
        assert messages[1]["content"] == "Faut-il migrer vers K8s ?"


# ============================================================
# Tests Debate
# ============================================================

class TestBuildDebateMessages:
    """Tests de la construction des messages pour la phase debate."""

    def test_debate_returns_2_messages(self, mock_context_config):
        """Debate produit exactement 2 messages : system + user."""
        builder = ContextBuilder()
        participant = make_participant("llm-a")
        participant.persona_name = "Pragmatique"
        participant.persona_description = "Analyse"
        debate = make_debate_with_rounds(1)

        messages = builder.build_debate_messages(
            participant, "Question ?", debate, round_number=2
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"

    def test_debate_includes_previous_positions(self, mock_context_config):
        """Le contexte inclut les positions des rounds précédents."""
        builder = ContextBuilder()
        participant = make_participant("llm-a")
        participant.persona_name = "Test"
        participant.persona_description = "Desc"
        debate = make_debate_with_rounds(1)

        messages = builder.build_debate_messages(
            participant, "Question ?", debate, round_number=2
        )
        system = messages[0]["content"]
        # Doit contenir les positions d'ouverture
        assert "Pour K8s" in system or "llm-a" in system

    def test_debate_includes_round_number(self, mock_context_config):
        """Le message user contient le numéro du round."""
        builder = ContextBuilder()
        participant = make_participant("llm-a")
        participant.persona_name = "Test"
        participant.persona_description = "Desc"
        debate = make_debate_with_rounds(1)

        messages = builder.build_debate_messages(
            participant, "Q?", debate, round_number=2
        )
        assert "Round 2" in messages[1]["content"]


# ============================================================
# Tests Context Window (zone glissante vs résumée)
# ============================================================

class TestContextWindow:
    """Tests de la gestion du context window (§16)."""

    def test_recent_rounds_full(self, mock_context_config):
        """Les rounds récents (N-1, N-2) sont inclus en entier."""
        builder = ContextBuilder()
        debate = make_debate_with_rounds(3)

        # Round 4, sliding_window=2 → rounds 2 et 3 en entier
        context = builder._format_debate_context(debate, "llm-a", current_round=4)
        # Round 3 doit être en entier (dans la zone glissante)
        assert "Position A round 3" in context
        assert "Position B round 3" in context

    def test_old_rounds_summarized(self, mock_context_config):
        """Les rounds anciens (> sliding_window) sont résumés."""
        builder = ContextBuilder()
        debate = make_debate_with_rounds(4)

        # Round 5, sliding_window=2 → rounds 3+4 en entier, rounds 1+2 résumés
        context = builder._format_debate_context(debate, "llm-a", current_round=5)
        # Round 1 doit être résumé (marqueur "(résumé)")
        assert "Round 1 (résumé)" in context

    def test_opening_always_included(self, mock_context_config):
        """Les positions d'ouverture sont toujours incluses."""
        builder = ContextBuilder()
        debate = make_debate_with_rounds(5)

        context = builder._format_debate_context(debate, "llm-a", current_round=6)
        assert "Positions initiales" in context

    def test_current_round_not_included(self, mock_context_config):
        """Le round en cours n'est pas inclus dans le contexte."""
        builder = ContextBuilder()
        debate = make_debate_with_rounds(3)

        # On est au round 3 → round 3 ne doit PAS être dans le contexte
        context = builder._format_debate_context(debate, "llm-a", current_round=3)
        assert "Position A round 3" not in context


# ============================================================
# Tests Verdict
# ============================================================

class TestBuildVerdictMessages:
    """Tests de la construction des messages pour le verdict."""

    def test_verdict_returns_2_messages(self, mock_context_config):
        """Verdict produit exactement 2 messages : system + user."""
        builder = ContextBuilder()
        debate = make_debate_with_rounds(2)

        messages = builder.build_verdict_messages("Question ?", debate)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"

    def test_verdict_includes_full_trajectory(self, mock_context_config):
        """Le verdict inclut TOUS les rounds (pas de résumé)."""
        builder = ContextBuilder()
        debate = make_debate_with_rounds(3)

        messages = builder.build_verdict_messages("Question ?", debate)
        system = messages[0]["content"]
        # Tous les rounds doivent être présents
        assert "Round 1" in system
        assert "Round 2" in system
        assert "Round 3" in system

    def test_verdict_includes_opening(self, mock_context_config):
        """Le verdict inclut les positions d'ouverture."""
        builder = ContextBuilder()
        debate = make_debate_with_rounds(1)

        messages = builder.build_verdict_messages("Question ?", debate)
        system = messages[0]["content"]
        assert "Pour K8s" in system or "llm-a" in system


# ============================================================
# Tests Challenge Retry
# ============================================================

class TestChallengeRetry:
    """Tests du prompt de retry anti-conformité."""

    def test_challenge_retry_format(self, mock_context_config):
        """Le retry contient les positions des autres participants."""
        builder = ContextBuilder()
        positions = "llm-a: Pour K8s\nllm-b: Contre K8s"

        messages = builder.build_challenge_retry_messages(positions)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Pour K8s" in messages[0]["content"]
        assert "Contre K8s" in messages[0]["content"]


# ============================================================
# Tests Summarize Round
# ============================================================

class TestSummarizeRound:
    """Tests du résumé compact d'un round ancien."""

    def test_summarize_includes_confidence(self, mock_context_config):
        """Le résumé contient la confidence de chaque participant."""
        rnd = Round(number=1, turns=[
            make_turn("llm-a", 1, confidence=85),
            make_turn("llm-b", 1, confidence=60),
        ])
        summary = ContextBuilder._summarize_round(rnd)
        assert "Conf 85" in summary
        assert "Conf 60" in summary

    def test_summarize_includes_challenge(self, mock_context_config):
        """Le résumé inclut les challenges."""
        rnd = Round(number=1, turns=[
            make_turn("llm-a", 1, challenged="llm-b",
                      challenge_reason="Argument faible sur le TCO"),
        ])
        summary = ContextBuilder._summarize_round(rnd)
        assert "Challenge → llm-b" in summary
        assert "TCO" in summary

    def test_summarize_no_position_fallback(self, mock_context_config):
        """Turn sans position structurée → marqueur '(non structuré)'."""
        turn = Turn(
            participant_id="llm-x", round_number=1,
            phase=DebatePhase.DEBATE, content="Texte brut",
        )
        rnd = Round(number=1, turns=[turn])
        summary = ContextBuilder._summarize_round(rnd)
        assert "non structuré" in summary


# ============================================================
# Tests User Answers
# ============================================================

class TestUserAnswers:
    """Tests du formatage des réponses utilisateur."""

    def test_no_answers(self, mock_context_config):
        """Pas de réponses → chaîne vide."""
        result = ContextBuilder._format_user_answers([])
        assert result == ""

    def test_one_answer(self, mock_context_config):
        """Une réponse est correctement formatée."""
        answers = [
            UserAnswer(
                question="Quel est votre budget ?",
                answer="500K€/an",
                asked_by="llm-a",
                round_number=2,
            )
        ]
        result = ContextBuilder._format_user_answers(answers)
        assert "budget" in result
        assert "500K€/an" in result
        assert "llm-a" in result

    def test_debate_with_user_answers(self, mock_context_config):
        """Les réponses utilisateur apparaissent dans le contexte debate."""
        builder = ContextBuilder()
        participant = make_participant("llm-a")
        participant.persona_name = "Test"
        participant.persona_description = "Desc"

        debate = make_debate_with_rounds(1)
        debate.user_answers = [
            UserAnswer(
                question="Budget ?",
                answer="Illimité",
                asked_by="llm-b",
                round_number=1,
            )
        ]

        messages = builder.build_debate_messages(
            participant, "Q?", debate, round_number=2
        )
        system = messages[0]["content"]
        assert "Illimité" in system

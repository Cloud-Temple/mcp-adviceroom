"""
Tests VerdictSynthesizer — Production du verdict via LLM synthétiseur.

Couvre :
- Verdict consensus réussi (mock LLM)
- Verdict dissensus réussi
- Fallback quand le modèle par défaut échoue
- Réponse vide du LLM → Verdict error
- Réponse sans bloc ---VERDICT--- → fallback
- Modèle ou provider non trouvé → error
- Parsing des champs du verdict (agreement_points, divergence_points, etc.)

Ref: DESIGN/architecture.md §3.4
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.debate.verdict import VerdictSynthesizer
from app.services.debate.models import (
    Debate,
    DebatePhase,
    Position,
    Round,
    Turn,
    Verdict,
    VerdictType,
)
from app.services.llm.base import LLMResponse, ModelConfig


# ============================================================
# Mock configs
# ============================================================

MOCK_DEBATE_CONFIG = {
    "synthesizer": {
        "default_model": "claude-opus-46",
        "fallback_model": "gpt-52",
    },
    "context": {
        "sliding_window_rounds": 2,
        "summary_tokens_per_participant": 200,
    },
}

MOCK_PROMPTS = {
    "verdict": {
        "system": (
            "Verdict pour: {question}\n"
            "Réponses user: {user_answers}\n"
            "Opening:\n{formatted_opening_positions}\n"
            "Rounds:\n{formatted_rounds}"
        ),
    },
    "opening": {"system": ""},
    "debate": {"system": ""},
}

MOCK_MODEL_CONFIG = ModelConfig(
    id="claude-opus-46",
    display_name="Claude Opus 4.6",
    provider="anthropic",
    category="anthropic",
    api_model_id="claude-opus-4.6",
    capabilities=["chat", "tools", "streaming"],
)


@pytest.fixture
def mock_verdict_deps():
    """Mock de toutes les dépendances du VerdictSynthesizer."""
    with patch("app.services.debate.verdict.get_debate_config", return_value=MOCK_DEBATE_CONFIG), \
         patch("app.services.debate.context_builder.get_prompts", return_value=MOCK_PROMPTS), \
         patch("app.services.debate.context_builder.get_debate_config", return_value=MOCK_DEBATE_CONFIG):
        yield


# ============================================================
# Helpers
# ============================================================

def make_simple_debate() -> Debate:
    """Crée un débat simple avec opening + 1 round."""
    debate = Debate(question="Faut-il migrer vers K8s ?")
    debate.opening_turns = [
        Turn(
            participant_id="llm-a", round_number=0,
            phase=DebatePhase.OPENING, content="Pour K8s",
            structured_position=Position(thesis="Pour", confidence=80, arguments=["TCO"]),
        ),
    ]
    debate.rounds = [
        Round(number=1, turns=[
            Turn(
                participant_id="llm-a", round_number=1,
                phase=DebatePhase.DEBATE, content="Toujours pour",
                structured_position=Position(thesis="Pour", confidence=85, arguments=["TCO"]),
            ),
        ]),
    ]
    return debate


def make_llm_response(content: str, usage: dict = None) -> LLMResponse:
    """Crée une LLMResponse mockée."""
    return LLMResponse(
        content=content,
        finish_reason="stop",
        model="claude-opus-4.6",
        provider="anthropic",
        usage=usage or {"total_tokens": 1500},
    )


# Réponse LLM avec un verdict consensus valide
CONSENSUS_RESPONSE = """
Après analyse de la trajectoire du débat...

---VERDICT---
verdict: consensus
confidence: 85
summary: |
  Les participants convergent vers la migration K8s.
agreement_points:
- Le TCO est favorable
- La scalabilité est un avantage majeur
divergence_points: []
recommendation: |
  Migrer vers K8s en commençant par les services stateless.
unresolved_questions:
- Quel provider cloud choisir ?
key_insights:
- Le consensus s'est formé dès le round 2
---END---
"""

# Réponse LLM avec un verdict dissensus
DISSENSUS_RESPONSE = """
Le débat révèle des positions irréconciliables.

---VERDICT---
verdict: dissensus
confidence: 70
summary: |
  Pas de consensus possible entre les participants.
agreement_points: []
divergence_points:
- topic: Migration K8s
  camp_a:
    participants: [llm-a]
    position: Pour la migration
  camp_b:
    participants: [llm-b]
    position: Contre la migration
recommendation: |
  Conduire un POC avant de décider.
unresolved_questions: []
key_insights:
- Les positions n'ont pas convergé malgré 3 rounds
---END---
"""


# ============================================================
# Tests du verdict réussi
# ============================================================

class TestVerdictSuccess:
    """Tests de la production de verdict quand le LLM répond correctement."""

    @pytest.mark.asyncio
    async def test_consensus_verdict(self, mock_verdict_deps):
        """Réponse consensus → Verdict avec type=CONSENSUS."""
        # Mock du LLM provider
        mock_provider = AsyncMock()
        mock_provider.chat_completion = AsyncMock(
            return_value=make_llm_response(CONSENSUS_RESPONSE)
        )

        # Mock du router
        mock_router = MagicMock()
        mock_router.get_model_by_id.return_value = MOCK_MODEL_CONFIG
        mock_router.get_provider.return_value = mock_provider

        with patch("app.services.debate.verdict.get_llm_router", return_value=mock_router):
            synth = VerdictSynthesizer()
            verdict = await synth.produce_verdict(make_simple_debate())

        assert verdict.type == VerdictType.CONSENSUS
        assert verdict.confidence == 85
        assert "convergent" in verdict.summary or "K8s" in verdict.summary
        assert len(verdict.agreement_points) >= 1
        assert verdict.synthesizer_model == "claude-opus-4.6"
        assert verdict.tokens_used == 1500

    @pytest.mark.asyncio
    async def test_dissensus_verdict(self, mock_verdict_deps):
        """Réponse dissensus → Verdict avec type=DISSENSUS."""
        mock_provider = AsyncMock()
        mock_provider.chat_completion = AsyncMock(
            return_value=make_llm_response(DISSENSUS_RESPONSE)
        )

        mock_router = MagicMock()
        mock_router.get_model_by_id.return_value = MOCK_MODEL_CONFIG
        mock_router.get_provider.return_value = mock_provider

        with patch("app.services.debate.verdict.get_llm_router", return_value=mock_router):
            synth = VerdictSynthesizer()
            verdict = await synth.produce_verdict(make_simple_debate())

        assert verdict.type == VerdictType.DISSENSUS
        assert verdict.confidence == 70
        assert len(verdict.divergence_points) >= 1


# ============================================================
# Tests d'erreur et fallback
# ============================================================

class TestVerdictErrors:
    """Tests des cas d'erreur et du mécanisme de fallback."""

    @pytest.mark.asyncio
    async def test_model_not_found(self, mock_verdict_deps):
        """Modèle non trouvé → Verdict error."""
        mock_router = MagicMock()
        mock_router.get_model_by_id.return_value = None

        with patch("app.services.debate.verdict.get_llm_router", return_value=mock_router):
            synth = VerdictSynthesizer()
            verdict = await synth.produce_verdict(make_simple_debate())

        assert verdict.type == VerdictType.ERROR
        assert "non trouvé" in verdict.summary

    @pytest.mark.asyncio
    async def test_provider_not_found(self, mock_verdict_deps):
        """Provider non initialisé → Verdict error."""
        mock_router = MagicMock()
        mock_router.get_model_by_id.return_value = MOCK_MODEL_CONFIG
        mock_router.get_provider.return_value = None

        with patch("app.services.debate.verdict.get_llm_router", return_value=mock_router):
            synth = VerdictSynthesizer()
            verdict = await synth.produce_verdict(make_simple_debate())

        assert verdict.type == VerdictType.ERROR
        assert "non initialisé" in verdict.summary

    @pytest.mark.asyncio
    async def test_empty_response(self, mock_verdict_deps):
        """Réponse vide du LLM → Verdict error."""
        mock_provider = AsyncMock()
        mock_provider.chat_completion = AsyncMock(
            return_value=LLMResponse(content="", finish_reason="stop")
        )

        mock_router = MagicMock()
        mock_router.get_model_by_id.return_value = MOCK_MODEL_CONFIG
        mock_router.get_provider.return_value = mock_provider

        with patch("app.services.debate.verdict.get_llm_router", return_value=mock_router):
            synth = VerdictSynthesizer()
            verdict = await synth.produce_verdict(make_simple_debate())

        assert verdict.type == VerdictType.ERROR

    @pytest.mark.asyncio
    async def test_llm_error_triggers_fallback(self, mock_verdict_deps):
        """LLM erreur sur défaut → fallback appelé."""
        # Premier appel : erreur
        error_response = LLMResponse(
            content="Erreur interne", finish_reason="error"
        )
        # Deuxième appel (fallback) : succès
        success_response = make_llm_response(CONSENSUS_RESPONSE)

        mock_provider = AsyncMock()
        mock_provider.chat_completion = AsyncMock(
            side_effect=[error_response, success_response]
        )

        # Config avec 2 modèles
        fallback_config = ModelConfig(
            id="gpt-52", display_name="GPT-5.2", provider="openai",
            category="openai", api_model_id="gpt-5.2",
        )

        mock_router = MagicMock()
        mock_router.get_model_by_id.side_effect = lambda mid: (
            MOCK_MODEL_CONFIG if mid == "claude-opus-46" else fallback_config
        )
        mock_router.get_provider.return_value = mock_provider

        with patch("app.services.debate.verdict.get_llm_router", return_value=mock_router):
            synth = VerdictSynthesizer()
            verdict = await synth.produce_verdict(make_simple_debate())

        # Le fallback doit avoir réussi
        assert verdict.type == VerdictType.CONSENSUS
        # Le provider a été appelé 2 fois (défaut + fallback)
        assert mock_provider.chat_completion.call_count == 2

    @pytest.mark.asyncio
    async def test_no_verdict_block_fallback(self, mock_verdict_deps):
        """Réponse sans bloc ---VERDICT--- → fallback parsing."""
        mock_provider = AsyncMock()
        mock_provider.chat_completion = AsyncMock(
            return_value=make_llm_response("Juste du texte sans structure")
        )

        mock_router = MagicMock()
        mock_router.get_model_by_id.return_value = MOCK_MODEL_CONFIG
        mock_router.get_provider.return_value = mock_provider

        with patch("app.services.debate.verdict.get_llm_router", return_value=mock_router):
            synth = VerdictSynthesizer()
            verdict = await synth.produce_verdict(make_simple_debate())

        # Le parser retourne un verdict error quand pas de bloc structuré
        assert verdict.type == VerdictType.ERROR


# ============================================================
# Tests du parsing des champs
# ============================================================

class TestVerdictParsing:
    """Tests du parsing détaillé des champs du verdict."""

    @pytest.mark.asyncio
    async def test_verdict_duration_set(self, mock_verdict_deps):
        """La durée du verdict est mesurée."""
        mock_provider = AsyncMock()
        mock_provider.chat_completion = AsyncMock(
            return_value=make_llm_response(CONSENSUS_RESPONSE)
        )

        mock_router = MagicMock()
        mock_router.get_model_by_id.return_value = MOCK_MODEL_CONFIG
        mock_router.get_provider.return_value = mock_provider

        with patch("app.services.debate.verdict.get_llm_router", return_value=mock_router):
            synth = VerdictSynthesizer()
            verdict = await synth.produce_verdict(make_simple_debate())

        assert verdict.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_error_verdict_helper(self, mock_verdict_deps):
        """_error_verdict produit un Verdict error correct."""
        synth = VerdictSynthesizer()
        verdict = VerdictSynthesizer._error_verdict("Test raison")

        assert verdict.type == VerdictType.ERROR
        assert verdict.confidence == 0
        assert "Test raison" in verdict.summary

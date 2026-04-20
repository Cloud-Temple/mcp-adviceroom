"""
VerdictSynthesizer — Analyse de la trajectoire complète → verdict structuré.

Responsabilités :
- Appeler un LLM DÉDIÉ (hors quota des 5 participants) pour synthétiser
- Fournir la trajectoire complète du débat (opening + rounds + user answers)
- Parser le verdict structuré (---VERDICT--- markers)
- Retourner un objet Verdict typé (consensus / consensus_partiel / dissensus)

Le synthétiseur est un analyste NEUTRE — il n'a pas de persona et n'est pas
un participant. Il reçoit l'intégralité de la trajectoire.

Ref: DESIGN/architecture.md §3.4 (Phase 3 — Verdict)
"""
import logging
import time
from typing import Any, Dict, Optional

from .context_builder import ContextBuilder
from .models import Debate, Verdict, VerdictType
from .parser import parse_verdict
from ..llm.base import BaseLLMProvider, LLMResponse
from ..llm.router import get_llm_router
from ...config.loader import get_debate_config

logger = logging.getLogger(__name__)

__all__ = ["VerdictSynthesizer"]


class VerdictSynthesizer:
    """
    Produit le verdict final d'un débat via un LLM synthétiseur dédié.

    Pipeline :
    1. ContextBuilder construit les messages avec la trajectoire complète
    2. Le LLM Router résout le modèle synthétiseur (configuré dans debate.yaml)
    3. Appel LLM non-streaming (le verdict n'est pas streamé vers le client)
    4. Parser le bloc ---VERDICT--- dans la réponse
    5. Construire et retourner l'objet Verdict

    Le synthétiseur utilise un modèle dédié (par défaut claude-opus-46),
    avec fallback configurable.

    Usage :
        synthesizer = VerdictSynthesizer()
        verdict = await synthesizer.produce_verdict(debate)
    """

    def __init__(self, context_builder: Optional[ContextBuilder] = None) -> None:
        """
        Initialise le VerdictSynthesizer.

        Args:
            context_builder: ContextBuilder à utiliser (optionnel, créé sinon).
        """
        self._context_builder = context_builder or ContextBuilder()
        config = get_debate_config()
        synth_cfg = config.get("synthesizer", {})

        # Modèle par défaut et fallback
        self._default_model_id: str = synth_cfg.get("default_model", "claude-opus-46")
        self._fallback_model_id: str = synth_cfg.get("fallback_model", "gpt-52")

        logger.info(
            f"✓ VerdictSynthesizer chargé : modèle={self._default_model_id}, "
            f"fallback={self._fallback_model_id}"
        )

    # ─── Production du verdict ───────────────────────────────

    async def produce_verdict(self, debate: Debate) -> Verdict:
        """
        Produit le verdict final du débat.

        Tente d'abord avec le modèle par défaut, puis le fallback si échec.

        Args:
            debate: L'objet Debate complet (opening + rounds terminés).

        Returns:
            Verdict structuré (consensus/consensus_partiel/dissensus/error).
        """
        start_time = time.monotonic()

        # Construire les messages pour le synthétiseur
        messages = self._context_builder.build_verdict_messages(
            question=debate.question,
            debate=debate,
        )

        # Tenter avec le modèle par défaut
        verdict = await self._call_synthesizer(
            messages, self._default_model_id, debate
        )

        # Fallback si échec
        if verdict.type == VerdictType.ERROR and self._fallback_model_id:
            logger.warning(
                f"⚠ Verdict échoué avec {self._default_model_id}, "
                f"retry avec fallback {self._fallback_model_id}"
            )
            verdict = await self._call_synthesizer(
                messages, self._fallback_model_id, debate
            )

        # Durée totale
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        verdict.duration_ms = elapsed_ms

        logger.info(
            f"✓ Verdict produit : {verdict.type.value} "
            f"(confidence={verdict.confidence}, {elapsed_ms}ms)"
        )

        return verdict

    async def _call_synthesizer(
        self,
        messages: list,
        model_id: str,
        debate: Debate,
    ) -> Verdict:
        """
        Appelle le LLM synthétiseur et parse la réponse.

        Args:
            messages: Messages au format OpenAI (system + user).
            model_id: ID du modèle dans llm_models.yaml.
            debate: L'objet Debate (pour les métadonnées).

        Returns:
            Verdict parsé depuis la réponse du LLM.
        """
        router = get_llm_router()

        # Résoudre le modèle
        model_config = router.get_model_by_id(model_id)
        if not model_config:
            logger.error(f"✗ Modèle synthétiseur '{model_id}' non trouvé")
            return self._error_verdict(f"Modèle '{model_id}' non trouvé")

        provider = router.get_provider(model_config.provider)
        if not provider:
            logger.error(f"✗ Provider '{model_config.provider}' non initialisé")
            return self._error_verdict(
                f"Provider '{model_config.provider}' non initialisé"
            )

        try:
            # Appel LLM non-streaming (le verdict est parsé en entier)
            response: LLMResponse = await provider.chat_completion(
                messages=messages,
                temperature=0.3,  # Bas pour un verdict factuel
                model_override=model_config.api_model_id,
            )

            if response.finish_reason == "error":
                return self._error_verdict(
                    response.content or "Erreur LLM inconnue"
                )

            # Parser le bloc ---VERDICT---
            return self._parse_response(
                response, model_id, model_config.api_model_id
            )

        except Exception as e:
            logger.error(f"✗ Erreur synthétiseur ({model_id}): {e}")
            return self._error_verdict(str(e))

    # ─── Parsing de la réponse ───────────────────────────────

    def _parse_response(
        self,
        response: LLMResponse,
        model_id: str,
        api_model_id: str,
    ) -> Verdict:
        """
        Parse la réponse du synthétiseur en objet Verdict.

        Utilise le parser de marqueurs YAML (---VERDICT---/---END---).

        Args:
            response: Réponse du LLM.
            model_id: ID interne du modèle.
            api_model_id: ID API du modèle.

        Returns:
            Verdict structuré.
        """
        if not response.content:
            return self._error_verdict("Réponse vide du synthétiseur")

        # Parser le bloc structuré
        prose, verdict_data = parse_verdict(response.content)

        # Mapper le type de verdict
        verdict_type_str = verdict_data.get("verdict", "error")
        try:
            verdict_type = VerdictType(verdict_type_str)
        except ValueError:
            logger.warning(
                f"⚠ Type de verdict inconnu '{verdict_type_str}' → error"
            )
            verdict_type = VerdictType.ERROR

        # Construire l'objet Verdict
        verdict = Verdict(
            type=verdict_type,
            confidence=int(verdict_data.get("confidence", 0)),
            summary=verdict_data.get("summary", prose),
            agreement_points=verdict_data.get("agreement_points", []) or [],
            divergence_points=verdict_data.get("divergence_points", []) or [],
            recommendation=verdict_data.get("recommendation", ""),
            unresolved_questions=verdict_data.get("unresolved_questions", []) or [],
            key_insights=verdict_data.get("key_insights", []) or [],
            synthesizer_model=api_model_id,
            tokens_used=response.usage.get("total_tokens", 0) if response.usage else 0,
        )

        return verdict

    # ─── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _error_verdict(reason: str) -> Verdict:
        """Crée un Verdict de type ERROR avec un message explicatif."""
        return Verdict(
            type=VerdictType.ERROR,
            confidence=0,
            summary=f"Erreur lors de la production du verdict : {reason}",
        )

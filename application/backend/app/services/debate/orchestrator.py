"""
DebateOrchestrator — Chef d'orchestre du débat multi-LLM.

Gère le cycle de vie complet d'un débat :
1. Création (participants, personas, config)
2. Phase OPENING : positions initiales en parallèle (anti-ancrage)
3. Phase DEBATE : round-robin séquentiel avec anti-conformité et stabilité
4. Phase VERDICT : synthétiseur dédié → verdict structuré
5. Gestion d'erreurs (skip, graceful degradation)

L'orchestrateur yielde des événements NDJSON pour le streaming temps réel.
Il ne gère PAS le HTTP — c'est le rôle des routers.

Ref: DESIGN/architecture.md §3 (Protocole), §14 (Anti-conformité), §15 (Erreurs)
"""
import asyncio
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from .context_builder import ContextBuilder
from .models import (
    ChallengeQuality,
    Debate,
    DebatePhase,
    DebateStatus,
    Participant,
    Position,
    Round,
    Turn,
    UserAnswer,
)
from .parser import parse_position, parse_challenge, parse_user_question
from .personas import PersonaManager
from .stability import StabilityDetector, StabilityResult
from .verdict import VerdictSynthesizer
from ..llm.base import BaseLLMProvider, LLMResponse
from ..llm.router import get_llm_router
from ..tools.executor import get_tool_executor
from ...config.loader import get_debate_config

logger = logging.getLogger(__name__)

__all__ = ["DebateOrchestrator"]


class DebateOrchestrator:
    """
    Orchestre un débat multi-LLM de bout en bout.

    Yield des événements NDJSON pour le streaming :
    - debate_start, phase, turn_start, chunk, turn_end
    - stability, user_question, debate_paused
    - verdict, debate_end, error

    Usage :
        orchestrator = DebateOrchestrator()
        debate = orchestrator.create_debate(question, participant_specs, ...)
        async for event in orchestrator.run(debate):
            send_ndjson(event)
    """

    def __init__(self) -> None:
        """Initialise les sous-modules depuis la config."""
        self._config = get_debate_config()
        self._persona_manager = PersonaManager()
        self._context_builder = ContextBuilder()
        self._stability_detector = StabilityDetector()
        self._verdict_synth = VerdictSynthesizer(self._context_builder)

        limits = self._config.get("limits", {})
        self._max_rounds: int = limits.get("max_rounds", 5)
        self._max_participants: int = limits.get("max_participants", 5)

        errors = self._config.get("error_handling", {})
        self._provider_timeout: int = errors.get("provider_timeout_seconds", 60)
        self._skip_threshold: int = errors.get("skip_threshold", 3)
        self._min_active: int = errors.get("min_active_participants", 2)

        anti = self._config.get("anti_conformity", {})
        self._challenge_max_retries: int = anti.get("max_retries", 1)

    # ============================================================
    # Création du débat
    # ============================================================

    def create_debate(
        self,
        question: str,
        participant_specs: List[Dict[str, str]],
        persona_overrides: Optional[Dict[str, str]] = None,
        config_overrides: Optional[Dict[str, Any]] = None,
    ) -> Debate:
        """
        Crée un objet Debate prêt à être exécuté.

        Args:
            question: La question de l'utilisateur.
            participant_specs: Liste de {"provider": ..., "model": ...}.
            persona_overrides: Dict {model_id: persona_id} (optionnel).
            config_overrides: Surcharges de config (max_rounds, etc.).

        Returns:
            Debate initialisé avec participants et personas.
        """
        router = get_llm_router()

        # Résoudre les participants depuis le registre de modèles
        participants = []
        for spec in participant_specs[:self._max_participants]:
            model_id = spec.get("model", "")
            model_cfg = router.get_model_by_id(model_id)
            if not model_cfg or not model_cfg.active:
                logger.warning(f"⚠ Modèle '{model_id}' non trouvé ou inactif — ignoré")
                continue
            participants.append(Participant(
                id=model_id,
                model_id=model_id,
                provider=model_cfg.provider,
                display_name=model_cfg.display_name,
            ))

        # Attribuer les personas
        self._persona_manager.assign_personas(participants, persona_overrides)

        # Appliquer les surcharges de config
        if config_overrides:
            if "max_rounds" in config_overrides:
                self._max_rounds = min(
                    config_overrides["max_rounds"],
                    self._config.get("limits", {}).get("max_rounds", 5),
                )

        debate = Debate(question=question, participants=participants)
        logger.info(
            f"✓ Débat créé : {len(participants)} participants, "
            f"max_rounds={self._max_rounds}"
        )
        return debate

    # ============================================================
    # Exécution principale
    # ============================================================

    async def run(self, debate: Debate) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Exécute le débat complet et yielde des événements NDJSON.

        Pipeline :
        1. OPENING → positions initiales en parallèle
        2. DEBATE → rounds séquentiels avec stabilité
        3. VERDICT → synthétiseur dédié

        Yields:
            Événements NDJSON (dicts) pour le streaming.
        """
        debate.status = DebateStatus.RUNNING
        yield {"type": "debate_start", "debate_id": debate.id,
               "question": debate.question,
               "participants": [self._participant_info(p) for p in debate.participants]}

        try:
            # Phase 1 — OPENING
            async for event in self._run_opening(debate):
                yield event

            # Phase 2 — DEBATE ROUNDS
            async for event in self._run_debate_rounds(debate):
                yield event

            # Phase 3 — VERDICT
            async for event in self._run_verdict(debate):
                yield event

            debate.status = DebateStatus.COMPLETED
            yield {"type": "debate_end", "debate_id": debate.id,
                   "status": "completed"}

        except Exception as e:
            logger.error(f"✗ Erreur fatale dans le débat : {e}")
            debate.status = DebateStatus.ERROR
            debate.error = str(e)
            yield {"type": "error", "debate_id": debate.id, "error": str(e)}

    # ============================================================
    # Phase 1 — OPENING (parallèle, anti-ancrage)
    # ============================================================

    async def _run_opening(self, debate: Debate) -> AsyncGenerator[Dict, None]:
        """Phase d'ouverture : positions initiales en parallèle."""
        debate.phase = DebatePhase.OPENING
        yield {"type": "phase", "phase": "opening", "round": 0}

        n = len(debate.participants)
        tasks = [
            self._run_single_turn(p, debate, round_number=0, phase=DebatePhase.OPENING)
            for p in debate.participants if p.active
        ]

        # Exécution en PARALLÈLE (anti-ancrage — §3.2)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            participant = debate.participants[i]
            if isinstance(result, Exception):
                logger.error(f"✗ Opening échoué pour {participant.id}: {result}")
                turn = Turn(
                    participant_id=participant.id, round_number=0,
                    phase=DebatePhase.OPENING, error=str(result),
                )
            else:
                turn = result

            debate.opening_turns.append(turn)
            yield {"type": "turn_end", "participant_id": participant.id,
                   "phase": "opening", "round": 0,
                   "has_position": turn.structured_position is not None}

    # ============================================================
    # Phase 2 — DEBATE (round-robin séquentiel)
    # ============================================================

    async def _run_debate_rounds(self, debate: Debate) -> AsyncGenerator[Dict, None]:
        """Rounds de débat avec détection de stabilité."""
        debate.phase = DebatePhase.DEBATE

        for round_num in range(1, self._max_rounds + 1):
            yield {"type": "phase", "phase": "debate", "round": round_num}

            rnd = Round(number=round_num)
            active_participants = [p for p in debate.participants if p.active]

            # Vérifier le minimum de participants actifs (§15)
            if len(active_participants) < self._min_active:
                logger.error(
                    f"✗ Seulement {len(active_participants)} participants actifs "
                    f"(min={self._min_active}) — arrêt"
                )
                debate.phase = DebatePhase.ERROR
                yield {"type": "error", "reason": "insufficient_participants",
                       "active": len(active_participants)}
                return

            # Round-robin séquentiel (§3.3)
            for participant in active_participants:
                yield {"type": "turn_start",
                       "participant": self._participant_info(participant),
                       "round": round_num}

                try:
                    turn = await self._run_single_turn(
                        participant, debate, round_num, DebatePhase.DEBATE
                    )

                    # Anti-conformité check (§14)
                    if turn.structured_position:
                        turn = await self._check_anti_conformity(
                            turn, participant, debate, round_num
                        )

                    # User question check (§3.6)
                    user_q = parse_user_question(turn.content)
                    if user_q:
                        turn.user_question = user_q
                        yield {"type": "user_question",
                               "participant_id": participant.id,
                               "question": user_q, "round": round_num}
                        # NOTE: La pause/reprise est gérée par la couche API
                        # L'orchestrateur s'arrête ici pour ce tour

                    participant.consecutive_skips = 0
                    rnd.turns.append(turn)

                except Exception as e:
                    logger.error(f"✗ Tour échoué {participant.id} round {round_num}: {e}")
                    participant.consecutive_skips += 1
                    rnd.turns.append(Turn(
                        participant_id=participant.id, round_number=round_num,
                        phase=DebatePhase.DEBATE, error=str(e),
                    ))

                    # Skip threshold (§15)
                    if participant.consecutive_skips >= self._skip_threshold:
                        participant.active = False
                        logger.warning(
                            f"⚠ {participant.id} retiré après "
                            f"{self._skip_threshold} rounds skipés"
                        )

                yield {"type": "turn_end", "participant_id": participant.id,
                       "round": round_num,
                       "has_position": bool(
                           rnd.turns and rnd.turns[-1].structured_position
                       )}

            debate.rounds.append(rnd)

            # Détection de stabilité (§13)
            stability = self._stability_detector.evaluate(debate, round_num)
            rnd.stability_score = stability.score
            yield {"type": "stability", **stability.to_dict()}

            if stability.can_stop:
                logger.info(f"✓ Débat stable après round {round_num} — passage au verdict")
                return

    # ============================================================
    # Phase 3 — VERDICT
    # ============================================================

    async def _run_verdict(self, debate: Debate) -> AsyncGenerator[Dict, None]:
        """Phase de verdict par le synthétiseur dédié."""
        debate.phase = DebatePhase.VERDICT
        yield {"type": "phase", "phase": "verdict"}

        verdict = await self._verdict_synth.produce_verdict(debate)
        debate.verdict = verdict

        yield {"type": "verdict",
               "verdict_type": verdict.type.value,
               "confidence": verdict.confidence,
               "summary": verdict.summary,
               "agreement_points": verdict.agreement_points,
               "divergence_points": verdict.divergence_points,
               "recommendation": verdict.recommendation,
               "key_insights": verdict.key_insights}

        debate.phase = DebatePhase.COMPLETED

    # ============================================================
    # Exécution d'un tour individuel
    # ============================================================

    async def _run_single_turn(
        self,
        participant: Participant,
        debate: Debate,
        round_number: int,
        phase: DebatePhase,
    ) -> Turn:
        """
        Exécute un tour de parole pour un participant.

        Construit le contexte, appelle le LLM, gère les tool calls,
        et parse la réponse finale.

        Pipeline tool call (§9) :
        1. Appel LLM avec tools disponibles
        2. Si tool_calls → exécuter via ToolExecutor
        3. Ajouter les résultats aux messages
        4. Rappeler le LLM pour la réponse finale
        Max 3 boucles tool call par tour (sécurité).

        Returns:
            Turn avec contenu, position structurée, et tool_calls/results.
        """
        import json as _json

        start_time = time.monotonic()
        router = get_llm_router()
        tool_executor = get_tool_executor()
        model_cfg = router.get_model_by_id(participant.model_id)
        provider = router.get_provider(participant.provider)

        if not model_cfg or not provider:
            raise RuntimeError(
                f"Provider/modèle non trouvé pour {participant.id}"
            )

        # Construire les messages selon la phase
        if phase == DebatePhase.OPENING:
            messages = self._context_builder.build_opening_messages(
                participant, debate.question, len(debate.participants)
            )
        else:
            messages = self._context_builder.build_debate_messages(
                participant, debate.question, debate, round_number
            )

        # Outils disponibles (format OpenAI function calling)
        tools = tool_executor.get_tool_definitions() if tool_executor.available else None

        # Boucle appel LLM + tool calls (max 3 itérations)
        all_tool_calls = []
        all_tool_results = []
        max_tool_loops = 3

        for loop_idx in range(max_tool_loops + 1):
            response: LLMResponse = await asyncio.wait_for(
                provider.chat_completion(
                    messages=messages,
                    tools=tools if loop_idx == 0 else None,  # Tools au 1er appel
                    temperature=0.7,
                    model_override=model_cfg.api_model_id,
                ),
                timeout=self._provider_timeout,
            )

            # Si pas de tool calls ou dernière boucle → sortir
            if not response.tool_calls or loop_idx >= max_tool_loops:
                break

            # Exécuter les tool calls
            # Ajouter la réponse assistant avec tool_calls aux messages
            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": response.tool_calls,
            })

            for tc in response.tool_calls:
                tc_id = tc.get("id", f"call_{loop_idx}")
                tc_name = tc.get("function", {}).get("name", "")
                tc_args_str = tc.get("function", {}).get("arguments", "{}")

                try:
                    tc_args = _json.loads(tc_args_str) if isinstance(tc_args_str, str) else tc_args_str
                except _json.JSONDecodeError:
                    tc_args = {}

                all_tool_calls.append({"name": tc_name, "arguments": tc_args})
                logger.info(f"🔧 {participant.id} appelle {tc_name}({tc_args})")

                # Exécuter via le bridge MCP Tools
                result = await tool_executor.execute_tool_call(tc_name, tc_args)
                result_str = _json.dumps(result, ensure_ascii=False)[:2000]
                all_tool_results.append({"name": tc_name, "result": result})

                # Ajouter le résultat au format OpenAI
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_str,
                })

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Parser la réponse finale
        prose, position = parse_position(response.content or "")
        tokens = response.usage.get("total_tokens", 0) if response.usage else 0

        return Turn(
            participant_id=participant.id,
            round_number=round_number,
            phase=phase,
            content=prose,
            structured_position=position,
            tool_calls=all_tool_calls,
            tool_results=all_tool_results,
            tokens_used=tokens,
            duration_ms=elapsed_ms,
        )

    # ============================================================
    # Anti-conformité (§14)
    # ============================================================

    async def _check_anti_conformity(
        self,
        turn: Turn,
        participant: Participant,
        debate: Debate,
        round_number: int,
    ) -> Turn:
        """
        Vérifie que le participant a challengé un argument.

        Si le challenge est absent ou superficiel, déclenche un retry
        (max 1 retry selon la config).

        Returns:
            Turn mis à jour (avec challenge ajouté si retry réussi).
        """
        pos = turn.structured_position
        if not pos:
            return turn

        if pos.challenge_quality != ChallengeQuality.ABSENT:
            return turn  # Challenge présent → OK

        # Challenge absent → retry
        for retry in range(self._challenge_max_retries):
            logger.info(
                f"🔄 Anti-conformité retry {retry + 1} pour {participant.id} "
                f"round {round_number}"
            )
            # Construire le prompt de retry
            other_positions = self._format_other_positions(debate, participant.id)
            retry_messages = self._context_builder.build_challenge_retry_messages(
                other_positions
            )

            router = get_llm_router()
            provider = router.get_provider(participant.provider)
            model_cfg = router.get_model_by_id(participant.model_id)

            if not provider or not model_cfg:
                break

            try:
                response = await provider.chat_completion(
                    messages=retry_messages,
                    temperature=0.8,
                    model_override=model_cfg.api_model_id,
                )
                challenge = parse_challenge(response.content or "")
                if challenge:
                    pos.challenged = challenge.get("challenged")
                    pos.challenge_target = challenge.get("challenge_target")
                    pos.challenge_reason = challenge.get("challenge_reason")
                    pos.challenge_quality = ChallengeQuality.SUBSTANTIVE
                    turn.flags.append("anti_conformity_retry_success")
                    return turn
            except Exception as e:
                logger.warning(f"⚠ Anti-conformité retry échoué: {e}")

        # Toujours absent après retries → flag
        turn.flags.append("no_challenge")
        return turn

    # ============================================================
    # Helpers
    # ============================================================

    @staticmethod
    def _participant_info(p: Participant) -> Dict[str, str]:
        """Sérialise un participant pour les événements NDJSON."""
        return {
            "model": p.model_id,
            "provider": p.provider,
            "persona": p.persona_name,
            "icon": p.persona_icon,
        }

    @staticmethod
    def _format_other_positions(debate: Debate, exclude_id: str) -> str:
        """Formate les positions des autres participants pour le retry."""
        lines = []
        # Derniers turns (opening ou dernier round)
        turns = debate.opening_turns if not debate.rounds else debate.rounds[-1].turns
        for turn in turns:
            if turn.participant_id != exclude_id and turn.structured_position:
                pos = turn.structured_position
                lines.append(
                    f"{turn.participant_id}: {pos.thesis} (conf {pos.confidence})"
                )
        return "\n".join(lines)

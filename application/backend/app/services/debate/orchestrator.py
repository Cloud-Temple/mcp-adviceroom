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
import collections
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from .context_builder import ContextBuilder
from .models import (
    ChallengeQuality,
    Debate,
    DebateMode,
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

# Ring buffer global pour l'activité LLM (accessible depuis l'admin API)
_llm_activity_log = collections.deque(maxlen=500)


def get_llm_activity_log() -> list:
    """Retourne l'activité LLM récente (plus récent en premier)."""
    return list(reversed(_llm_activity_log))


def _log_llm_activity(
    event_type: str,
    debate_id: str = "",
    participant_id: str = "",
    model_id: str = "",
    provider: str = "",
    persona: str = "",
    phase: str = "",
    round_number: int = 0,
    tokens: int = 0,
    duration_ms: int = 0,
    status: str = "ok",
    error: str = "",
    thesis: str = "",
    confidence: int = 0,
    tool_calls: int = 0,
    details: str = "",
):
    """Enregistre un événement dans le log d'activité LLM."""
    _llm_activity_log.append({
        "timestamp": time.time(),
        "type": event_type,
        "debate_id": debate_id[:8] if debate_id else "",
        "participant": participant_id,
        "model": model_id,
        "provider": provider,
        "persona": persona,
        "phase": phase,
        "round": round_number,
        "tokens": tokens,
        "duration_ms": duration_ms,
        "status": status,
        "error": error[:150] if error else "",
        "thesis": thesis[:100] if thesis else "",
        "confidence": confidence,
        "tool_calls": tool_calls,
        "details": details[:200] if details else "",
    })


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
        self._max_participants: int = limits.get("max_participants", 5)

        # Mode par défaut et configs des modes (§3.1.1)
        self._default_mode: str = self._config.get("default_mode", "parallel")
        self._modes_config: Dict[str, Any] = self._config.get("modes", {})

        # Valeurs par défaut (surchargées par le mode actif dans create_debate)
        self._max_rounds: int = 5
        self._min_rounds: int = 1
        self._parallel_turns: bool = True
        self._tools_enabled: bool = True
        self._max_response_tokens: Optional[int] = None

        errors = self._config.get("error_handling", {})
        self._provider_timeout: int = errors.get("provider_timeout_seconds", 120)
        self._provider_max_retries: int = errors.get("provider_max_retries", 2)
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
        mode: Optional[str] = None,
    ) -> Debate:
        """
        Crée un objet Debate prêt à être exécuté.

        Args:
            question: La question de l'utilisateur.
            participant_specs: Liste de {"provider": ..., "model": ...}.
            persona_overrides: Dict {model_id: persona_id} (optionnel).
            config_overrides: Surcharges de config (max_rounds, etc.).
            mode: Mode de débat "standard" | "parallel" | "blitz" (§3.1.1).

        Returns:
            Debate initialisé avec participants et personas.
        """
        router = get_llm_router()

        # Résoudre le mode de débat (§3.1.1)
        mode_str = mode or self._default_mode
        try:
            debate_mode = DebateMode(mode_str)
        except ValueError:
            logger.warning(f"⚠ Mode '{mode_str}' inconnu — fallback sur '{self._default_mode}'")
            debate_mode = DebateMode(self._default_mode)

        # Charger la config du mode
        mode_cfg = self._modes_config.get(debate_mode.value, {})
        self._max_rounds = mode_cfg.get("max_rounds", 3)
        self._min_rounds = mode_cfg.get("min_rounds", 1)
        self._parallel_turns = mode_cfg.get("parallel_turns", True)
        self._tools_enabled = mode_cfg.get("tools_enabled", True)
        self._max_response_tokens = mode_cfg.get("max_response_tokens") or None

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

        # Appliquer les surcharges de config (max_rounds déjà borné 1-20 par l'API)
        if config_overrides:
            if "max_rounds" in config_overrides:
                self._max_rounds = max(int(config_overrides["max_rounds"]), 1)

        debate = Debate(
            question=question,
            mode=debate_mode,
            participants=participants,
        )
        logger.info(
            f"✓ Débat créé : {len(participants)} participants, "
            f"mode={debate_mode.value}, max_rounds={self._max_rounds}"
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
               "mode": debate.mode.value,
               "max_rounds": self._max_rounds,
               "participants": [self._participant_info(p) for p in debate.participants]}

        try:
            # Phase 1 — OPENING (toujours parallèle)
            async for event in self._run_opening(debate):
                yield event

            # Phase 2 — DEBATE ROUNDS (sautée en mode blitz — §3.1.1)
            if self._max_rounds > 0:
                if self._parallel_turns:
                    async for event in self._run_parallel_debate_rounds(debate):
                        yield event
                else:
                    async for event in self._run_debate_rounds(debate):
                        yield event
            else:
                logger.info("⚡ Mode blitz — Phase 2 sautée, passage direct au verdict")

            # Phase 3 — VERDICT (toujours)
            async for event in self._run_verdict(debate):
                yield event

            debate.status = DebateStatus.COMPLETED
            yield {"type": "debate_end", "debate_id": debate.id,
                   "status": "completed",
                   "rounds": len(debate.rounds),
                   "total_tokens": debate.total_tokens}

        except Exception as e:
            logger.error(f"✗ Erreur fatale dans le débat : {e}")
            debate.status = DebateStatus.ERROR
            debate.error = "Erreur interne lors du débat"
            yield {"type": "error", "debate_id": debate.id, "error": "Erreur interne lors du débat"}

    # ============================================================
    # Phase 1 — OPENING (parallèle, anti-ancrage)
    # ============================================================

    async def _run_opening(self, debate: Debate) -> AsyncGenerator[Dict, None]:
        """Phase d'ouverture : positions initiales en parallèle."""
        debate.phase = DebatePhase.OPENING
        yield {"type": "phase", "phase": "opening", "round": 0}

        active = [p for p in debate.participants if p.active]

        # Émettre turn_start pour tous les participants (parallèle)
        for p in active:
            yield {"type": "turn_start",
                   "participant": self._participant_info(p),
                   "round": 0, "phase": "opening"}

        tasks = [
            self._run_single_turn(p, debate, round_number=0, phase=DebatePhase.OPENING)
            for p in active
        ]

        # Exécution en PARALLÈLE (anti-ancrage — §3.2)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            participant = active[i]
            if isinstance(result, Exception):
                logger.error(f"✗ Opening échoué pour {participant.id}: {result}")
                turn = Turn(
                    participant_id=participant.id, round_number=0,
                    phase=DebatePhase.OPENING, error="Erreur lors de la génération de la position initiale",
                )
            else:
                turn = result

            debate.opening_turns.append(turn)
            debate.total_tokens += turn.tokens_used

            # Événement enrichi avec contenu, tokens, durée, position
            event: Dict[str, Any] = {
                "type": "turn_end",
                "participant_id": participant.id,
                "participant": self._participant_info(participant),
                "phase": "opening",
                "round": 0,
                "content": turn.content,
                "tokens_used": turn.tokens_used,
                "duration_ms": turn.duration_ms,
                "has_position": turn.structured_position is not None,
            }
            if turn.structured_position:
                event["position"] = {
                    "thesis": turn.structured_position.thesis,
                    "confidence": turn.structured_position.confidence,
                    "arguments": turn.structured_position.arguments,
                }
            if turn.error:
                event["error"] = turn.error
            if turn.tool_calls:
                event["tool_calls"] = turn.tool_calls
            if turn.tool_results:
                event["tool_results"] = turn.tool_results
            yield event

    # ============================================================
    # Phase 2 — DEBATE (round-robin séquentiel)
    # ============================================================

    async def _run_debate_rounds(self, debate: Debate) -> AsyncGenerator[Dict, None]:
        """
        Rounds de débat séquentiels — Within-Round [4].

        Chaque participant parle à tour de rôle. Les agents suivants voient
        les turns déjà complétés dans le même round (same-round visibility).
        C'est le protocole WR du papier [4], qui maximise le peer-referencing.
        """
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

            # Round-robin séquentiel Within-Round [4] (§3.3)
            # Chaque agent voit les turns déjà complétés dans le même round
            for participant in active_participants:
                yield {"type": "turn_start",
                       "participant": self._participant_info(participant),
                       "round": round_num}

                try:
                    # Within-Round [4] : passer rnd.turns (same-round visibility)
                    turn = await self._run_single_turn(
                        participant, debate, round_num, DebatePhase.DEBATE,
                        current_round_turns=list(rnd.turns),  # copie pour éviter les mutations
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
                        phase=DebatePhase.DEBATE, error="Erreur lors du tour de débat",
                    ))

                    # Skip threshold (§15)
                    if participant.consecutive_skips >= self._skip_threshold:
                        participant.active = False
                        logger.warning(
                            f"⚠ {participant.id} retiré après "
                            f"{self._skip_threshold} rounds skipés"
                        )

                # Événement enrichi avec contenu, tokens, durée, position
                last_turn = rnd.turns[-1] if rnd.turns else None
                te: Dict[str, Any] = {
                    "type": "turn_end",
                    "participant_id": participant.id,
                    "participant": self._participant_info(participant),
                    "round": round_num,
                    "has_position": bool(last_turn and last_turn.structured_position),
                }
                if last_turn:
                    te["content"] = last_turn.content
                    te["tokens_used"] = last_turn.tokens_used
                    te["duration_ms"] = last_turn.duration_ms
                    debate.total_tokens += last_turn.tokens_used
                    if last_turn.structured_position:
                        pos = last_turn.structured_position
                        te["position"] = {
                            "thesis": pos.thesis,
                            "confidence": pos.confidence,
                            "arguments": pos.arguments,
                            "challenged": pos.challenged,
                            "challenge_reason": pos.challenge_reason,
                        }
                    if last_turn.error:
                        te["error"] = last_turn.error
                    if last_turn.tool_calls:
                        te["tool_calls"] = last_turn.tool_calls
                    if last_turn.tool_results:
                        te["tool_results"] = last_turn.tool_results
                yield te

            debate.rounds.append(rnd)

            # Détection de stabilité (§13)
            stability = self._stability_detector.evaluate(debate, round_num)
            rnd.stability_score = stability.score
            yield {"type": "stability", **stability.to_dict()}

            if stability.can_stop:
                logger.info(f"✓ Débat stable après round {round_num} — passage au verdict")
                return

    # ============================================================
    # Phase 2 bis — DEBATE PARALLÈLE (Within-Round [4])
    # ============================================================

    async def _run_parallel_debate_rounds(self, debate: Debate) -> AsyncGenerator[Dict, None]:
        """
        Rounds de débat avec turns parallèles — Cross-Round [4].

        Cross-Round [4] : tous les participants parlent en même temps.
        Chaque participant voit les positions du round PRÉCÉDENT (pas du round en cours).
        Pas de same-round visibility (contrairement au mode standard/WR).
        3× plus rapide que le mode standard.
        """
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

            # Émettre turn_start pour tous (parallèle)
            for p in active_participants:
                yield {"type": "turn_start",
                       "participant": self._participant_info(p),
                       "round": round_num}

            # Exécuter TOUS les turns en parallèle (asyncio.gather)
            tasks = [
                self._run_single_turn(p, debate, round_num, DebatePhase.DEBATE)
                for p in active_participants
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Traiter les résultats
            for i, result in enumerate(results):
                participant = active_participants[i]

                if isinstance(result, Exception):
                    logger.error(f"✗ Tour échoué {participant.id} round {round_num}: {result}")
                    participant.consecutive_skips += 1
                    turn = Turn(
                        participant_id=participant.id, round_number=round_num,
                        phase=DebatePhase.DEBATE, error="Erreur lors du tour de débat",
                    )
                    if participant.consecutive_skips >= self._skip_threshold:
                        participant.active = False
                        logger.warning(f"⚠ {participant.id} retiré après {self._skip_threshold} rounds skipés")
                else:
                    turn = result
                    # Anti-conformité check (§14) — même en parallèle
                    if turn.structured_position:
                        turn = await self._check_anti_conformity(
                            turn, participant, debate, round_num
                        )
                    participant.consecutive_skips = 0

                rnd.turns.append(turn)
                debate.total_tokens += turn.tokens_used

                # Événement turn_end enrichi
                te: Dict[str, Any] = {
                    "type": "turn_end",
                    "participant_id": participant.id,
                    "participant": self._participant_info(participant),
                    "round": round_num,
                    "has_position": bool(turn.structured_position),
                    "content": turn.content,
                    "tokens_used": turn.tokens_used,
                    "duration_ms": turn.duration_ms,
                }
                if turn.structured_position:
                    pos = turn.structured_position
                    te["position"] = {
                        "thesis": pos.thesis,
                        "confidence": pos.confidence,
                        "arguments": pos.arguments,
                        "challenged": pos.challenged,
                        "challenge_reason": pos.challenge_reason,
                    }
                if turn.error:
                    te["error"] = turn.error
                if turn.tool_calls:
                    te["tool_calls"] = turn.tool_calls
                if turn.tool_results:
                    te["tool_results"] = turn.tool_results
                yield te

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

        # Log verdict LLM
        _log_llm_activity(
            event_type="verdict",
            debate_id=debate.id,
            model_id=verdict.synthesizer_model or "",
            tokens=verdict.tokens_used,
            duration_ms=verdict.duration_ms,
            status="ok" if verdict.type.value != "error" else "error",
            confidence=verdict.confidence,
            details=f"{verdict.type.value} — {(verdict.summary or '')[:100]}",
        )

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
        current_round_turns: Optional[list] = None,
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
            # Within-Round [4] : en mode standard, current_round_turns contient
            # les turns déjà complétés dans le round courant (same-round visibility)
            messages = self._context_builder.build_debate_messages(
                participant, debate.question, debate, round_number,
                current_round_turns=current_round_turns,
            )

        # Outils disponibles (format OpenAI function calling)
        tools = tool_executor.get_tool_definitions() if tool_executor.available else None

        # Boucle appel LLM + tool calls
        # Opus fait souvent des chaînes de tool calls (web_search x2, datetime, etc.)
        # On laisse le modèle faire ses tool calls autant qu'il veut (limite haute de sécurité)
        all_tool_calls = []
        all_tool_results = []
        max_tool_loops = 10

        for loop_idx in range(max_tool_loops + 1):
            response: LLMResponse = await asyncio.wait_for(
                provider.chat_completion(
                    messages=messages,
                    tools=tools,  # Toujours passer les tools — Anthropic l'exige quand les messages contiennent des tool_use/tool_result blocks
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
        tokens = response.usage.get("total_tokens", 0) if response.usage else 0
        raw_content = response.content or ""

        # Détecter les réponses vides → retry avec backoff généreux (§15)
        # IMPORTANT : une réponse avec tool_calls mais sans texte n'est PAS vide !
        # Le modèle veut utiliser ses tools — c'est une réponse valide.
        # On ne retry que si il n'y a NI texte NI tool_calls.
        has_tool_calls = bool(response.tool_calls)
        if not raw_content.strip() and not has_tool_calls:
            max_retries = max(self._provider_max_retries, 5)  # Au moins 5 retries
            for retry_num in range(1, max_retries + 1):
                backoff_seconds = retry_num * 15  # 15s, 30s, 45s, 60s, 75s
                logger.warning(
                    f"⚠ Réponse vide de {participant.id} (round {round_number}) "
                    f"— retry {retry_num}/{max_retries} après {backoff_seconds}s"
                )
                await asyncio.sleep(backoff_seconds)

                try:
                    retry_response: LLMResponse = await asyncio.wait_for(
                        provider.chat_completion(
                            messages=messages,
                            tools=tools,  # Anthropic exige les tools quand les messages contiennent des tool_use/tool_result blocks
                            temperature=0.7,
                            model_override=model_cfg.api_model_id,
                        ),
                        timeout=self._provider_timeout,
                    )
                    retry_content = retry_response.content or ""
                    if retry_content.strip():
                        # Retry réussi !
                        logger.info(
                            f"✓ Retry {retry_num} réussi pour {participant.id}"
                        )
                        elapsed_ms = int((time.monotonic() - start_time) * 1000)
                        retry_tokens = retry_response.usage.get("total_tokens", 0) if retry_response.usage else 0
                        tokens += retry_tokens
                        raw_content = retry_content
                        break
                except Exception as e:
                    logger.warning(f"⚠ Retry {retry_num} échoué pour {participant.id}: {e}")
            else:
                # Tous les retries épuisés → erreur
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                logger.error(
                    f"✗ Réponse vide persistante de {participant.id} "
                    f"après {self._provider_max_retries} retries ({elapsed_ms}ms)"
                )
                # Log erreur LLM
                _log_llm_activity(
                    event_type="turn", debate_id=debate.id,
                    participant_id=participant.id, model_id=participant.model_id,
                    provider=participant.provider, persona=participant.persona_name,
                    phase=phase.value, round_number=round_number,
                    tokens=tokens, duration_ms=elapsed_ms,
                    status="error", error=f"Réponse vide après {self._provider_max_retries} retries",
                )
                return Turn(
                    participant_id=participant.id,
                    round_number=round_number,
                    phase=phase,
                    content="",
                    structured_position=None,
                    tool_calls=all_tool_calls,
                    tool_results=all_tool_results,
                    tokens_used=tokens,
                    duration_ms=elapsed_ms,
                    error=f"Réponse vide du modèle {participant.model_id} après {self._provider_max_retries} retries ({elapsed_ms}ms)",
                )

        # Parser la réponse finale
        prose, position = parse_position(raw_content)

        # Log activité LLM
        _log_llm_activity(
            event_type="turn",
            debate_id=debate.id,
            participant_id=participant.id,
            model_id=participant.model_id,
            provider=participant.provider,
            persona=participant.persona_name,
            phase=phase.value,
            round_number=round_number,
            tokens=tokens,
            duration_ms=elapsed_ms,
            status="ok" if position else "no_position",
            thesis=position.thesis if position else "",
            confidence=position.confidence if position else 0,
            tool_calls=len(all_tool_calls),
        )

        return Turn(
            participant_id=participant.id,
            round_number=round_number,
            phase=phase,
            content=prose,
            structured_position=position,  # peut être None si parsing échoue
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
                # Tous les modèles doivent pouvoir utiliser leurs tools
                tool_executor = get_tool_executor()
                ac_tools = tool_executor.get_tool_definitions() if tool_executor.available else None

                response = await provider.chat_completion(
                    messages=retry_messages,
                    tools=ac_tools,
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
            "id": p.id,
            "model": p.model_id,
            "provider": p.provider,
            "display_name": p.display_name,
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

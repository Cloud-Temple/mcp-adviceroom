"""
ContextBuilder — Construction du contexte (messages) pour chaque tour de parole.

Responsabilités :
- Injecter le system prompt avec les variables du template (persona, question, etc.)
- Formater les positions précédentes pour le contexte de débat
- Gérer le context window : zones protégée, glissante, résumée (§16)
- Résumer les rounds anciens pour ne pas exploser la fenêtre de contexte
- Construire les messages pour le verdict (trajectoire complète)

Ref: DESIGN/architecture.md §3.2-§3.4, §12, §16
"""
import logging
from typing import Any, Dict, List, Optional

from .models import (
    Debate,
    DebatePhase,
    Participant,
    Position,
    Round,
    Turn,
    UserAnswer,
)
from ...config.loader import get_prompts, get_debate_config

logger = logging.getLogger(__name__)

__all__ = ["ContextBuilder"]


class ContextBuilder:
    """
    Construit les messages (format OpenAI) pour chaque appel LLM du débat.

    Trois cas principaux :
    - Opening : system prompt + question (pas de contexte de débat)
    - Debate : system prompt + positions précédentes + historique
    - Verdict : system prompt + trajectoire complète du débat

    Gère aussi le context window (§16) en résumant les rounds anciens.
    """

    def __init__(self) -> None:
        """Charge les templates de prompts et la config du débat."""
        self._prompts = get_prompts()
        self._debate_config = get_debate_config()

        # Paramètres de context window (§16)
        ctx_cfg = self._debate_config.get("context", {})
        self._sliding_window_rounds: int = ctx_cfg.get("sliding_window_rounds", 2)
        self._summary_tokens_per_participant: int = ctx_cfg.get(
            "summary_tokens_per_participant", 200
        )

    # ============================================================
    # Phase 1 — OPENING
    # ============================================================

    def build_opening_messages(
        self,
        participant: Participant,
        question: str,
        n_participants: int,
    ) -> List[Dict[str, Any]]:
        """
        Construit les messages pour la phase d'ouverture.

        Le participant reçoit son persona et la question, sans connaître
        les positions des autres (anti-ancrage).

        Args:
            participant: Le participant pour qui on construit le contexte.
            question: La question posée par l'utilisateur.
            n_participants: Nombre total de participants.

        Returns:
            Messages au format OpenAI : [system, user].
        """
        # Charger et formater le template opening
        system_template = self._prompts.get("opening", {}).get("system", "")
        system_prompt = system_template.format(
            participant_id=participant.id,
            persona_name=participant.persona_name,
            persona_description=participant.persona_description,
            n_participants=n_participants,
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

    # ============================================================
    # Phase 2 — DEBATE
    # ============================================================

    def build_debate_messages(
        self,
        participant: Participant,
        question: str,
        debate: Debate,
        round_number: int,
    ) -> List[Dict[str, Any]]:
        """
        Construit les messages pour un round de débat.

        Le contexte inclut :
        - System prompt avec persona et règles du round
        - Historique : positions opening + rounds précédents
        - Gestion du context window (résumés pour rounds anciens)

        Args:
            participant: Le participant qui va parler.
            question: La question originale.
            debate: L'objet Debate complet (opening, rounds, user_answers).
            round_number: Numéro du round actuel (1-based).

        Returns:
            Messages au format OpenAI : [system, user].
        """
        # Formater les positions précédentes (tous les autres participants)
        formatted_positions = self._format_debate_context(
            debate, participant.id, round_number
        )

        # Formater les réponses utilisateur (si applicable)
        user_answers_text = self._format_user_answers(debate.user_answers)
        user_answers_section = (
            f"\n\n## Réponses de l'utilisateur\n{user_answers_text}"
            if user_answers_text
            else ""
        )

        # Instruction pour poser une question à l'utilisateur
        user_question_instruction = (
            "## Question pour l'utilisateur\n"
            "Si tu as absolument besoin d'une information manquante, "
            "tu peux poser UNE question :\n"
            "---USER_QUESTION---\n[Ta question]\n---END---"
        )

        # Formater le system prompt
        system_template = self._prompts.get("debate", {}).get("system", "")
        system_prompt = system_template.format(
            participant_id=participant.id,
            persona_name=participant.persona_name,
            persona_description=participant.persona_description,
            question=question,
            user_answers_if_any=user_answers_section,
            formatted_previous_positions=formatted_positions,
            round_number=round_number,
            user_question_instruction=user_question_instruction,
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Round {round_number} — C'est ton tour."},
        ]

    # ============================================================
    # Phase 3 — VERDICT
    # ============================================================

    def build_verdict_messages(
        self,
        question: str,
        debate: Debate,
    ) -> List[Dict[str, Any]]:
        """
        Construit les messages pour le synthétiseur (verdict).

        Le synthétiseur reçoit la trajectoire COMPLÈTE du débat :
        - Positions initiales (opening)
        - Tous les rounds de débat
        - Réponses utilisateur

        Args:
            question: La question originale.
            debate: L'objet Debate complet.

        Returns:
            Messages au format OpenAI : [system, user].
        """
        # Formater les positions d'ouverture
        formatted_opening = self._format_opening_positions(debate.opening_turns)

        # Formater tous les rounds
        formatted_rounds = self._format_all_rounds(debate.rounds)

        # Formater les réponses utilisateur
        user_answers_text = self._format_user_answers(debate.user_answers)

        # Formater le system prompt du verdict
        system_template = self._prompts.get("verdict", {}).get("system", "")
        system_prompt = system_template.format(
            question=question,
            user_answers=user_answers_text or "Aucune",
            formatted_opening_positions=formatted_opening,
            formatted_rounds=formatted_rounds,
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Analyse cette trajectoire et produis ton verdict."},
        ]

    # ============================================================
    # Challenge retry
    # ============================================================

    def build_challenge_retry_messages(
        self,
        other_positions: str,
    ) -> List[Dict[str, Any]]:
        """
        Construit les messages pour le retry anti-conformité.

        Quand un participant n'a pas challengé d'argument, on lui demande
        explicitement de le faire (§14).

        Args:
            other_positions: Résumé des positions des autres participants.

        Returns:
            Messages au format OpenAI : [system, user].
        """
        template = self._prompts.get("challenge_retry", "")
        content = template.format(other_positions=other_positions)

        return [
            {"role": "user", "content": content},
        ]

    # ============================================================
    # Formatage du contexte de débat
    # ============================================================

    def _format_debate_context(
        self,
        debate: Debate,
        current_participant_id: str,
        current_round: int,
    ) -> str:
        """
        Formate le contexte complet du débat pour un participant.

        Gère le context window (§16) :
        - Opening : toujours inclus (résumé si trop long)
        - Rounds récents (N, N-1) : en entier (zone glissante)
        - Rounds anciens : résumés (zone résumée)

        Args:
            debate: L'objet Debate complet.
            current_participant_id: ID du participant qui va parler.
            current_round: Numéro du round actuel.

        Returns:
            Texte formaté avec toutes les positions.
        """
        sections = []

        # 1. Positions d'ouverture (toujours incluses)
        if debate.opening_turns:
            sections.append("### Positions initiales (Opening)")
            sections.append(self._format_opening_positions(debate.opening_turns))

        # 2. Rounds précédents avec gestion du context window
        for rnd in debate.rounds:
            # Ne pas inclure les tours du round en cours qui n'ont pas encore eu lieu
            if rnd.number >= current_round:
                continue

            # Zone glissante : rounds récents en entier
            if current_round - rnd.number <= self._sliding_window_rounds:
                sections.append(f"\n### Round {rnd.number}")
                sections.append(self._format_round_full(rnd, current_participant_id))
            else:
                # Zone résumée : rounds anciens
                sections.append(f"\n### Round {rnd.number} (résumé)")
                sections.append(self._summarize_round(rnd))

        return "\n".join(sections)

    def _format_opening_positions(self, opening_turns: List[Turn]) -> str:
        """
        Formate les positions d'ouverture pour le contexte.

        Args:
            opening_turns: Liste des tours d'ouverture.

        Returns:
            Texte formaté avec les positions initiales.
        """
        lines = []
        for turn in opening_turns:
            pos = turn.structured_position
            if pos:
                args_str = ', '.join(str(a) for a in pos.arguments[:4])
                lines.append(
                    f"**{turn.participant_id}** :\n"
                    f"- Thèse : {pos.thesis}\n"
                    f"- Confidence : {pos.confidence}/100\n"
                    f"- Arguments : {args_str}"
                )
            elif turn.content:
                # Pas de position structurée → texte brut (tronqué)
                lines.append(
                    f"**{turn.participant_id}** : {turn.content[:500]}"
                )
        return "\n\n".join(lines)

    def _format_round_full(
        self, rnd: Round, current_participant_id: str
    ) -> str:
        """
        Formate un round en entier (zone glissante — pas de troncation).

        Args:
            rnd: Le round à formater.
            current_participant_id: ID du participant courant (pour le marquer).

        Returns:
            Texte formaté avec tous les tours du round.
        """
        lines = []
        for turn in rnd.turns:
            pos = turn.structured_position
            marker = " *(toi)*" if turn.participant_id == current_participant_id else ""

            header = f"**{turn.participant_id}**{marker} :"
            parts = [header]

            # Contenu prose
            if turn.content:
                parts.append(turn.content)

            # Position structurée
            if pos:
                args_str = ', '.join(str(a) for a in pos.arguments[:4])
                parts.append(
                    f"\n> Thèse : {pos.thesis}\n"
                    f"> Confidence : {pos.confidence}/100\n"
                    f"> Arguments : {args_str}"
                )
                if pos.challenged:
                    parts.append(
                        f"> Challenge → {pos.challenged} : "
                        f"{pos.challenge_reason or 'non détaillé'}"
                    )

            # Tool calls (résumé — format Turn: [{"name": ..., "arguments": ...}])
            if turn.tool_calls:
                tc_summary = ", ".join(
                    tc.get("name", tc.get("function", {}).get("name", "?"))
                    for tc in turn.tool_calls
                )
                parts.append(f"> Outils utilisés : {tc_summary}")

            lines.append("\n".join(parts))

        return "\n\n".join(lines)

    # ============================================================
    # Résumé de rounds (zone résumée, §16.4)
    # ============================================================

    @staticmethod
    def _summarize_round(rnd: Round) -> str:
        """
        Résume un round ancien en format compact (§16.4).

        Chaque participant est résumé en ~1 ligne :
        "GPT-5.2 : Pour. Conf 80. Args: TCO, scalabilité. Challenge → Claude: risque lock-in."

        Args:
            rnd: Le round à résumer.

        Returns:
            Texte résumé compact.
        """
        lines = []
        for turn in rnd.turns:
            pos = turn.structured_position
            if not pos:
                lines.append(f"- **{turn.participant_id}** : (non structuré)")
                continue

            # Résumé compact : sentiment, confidence, arguments, challenge
            args_str = ", ".join(pos.arguments[:3])
            line = (
                f"- **{turn.participant_id}** : "
                f"Conf {pos.confidence}. "
                f"Args: {args_str}."
            )
            if pos.challenged:
                reason = (pos.challenge_reason or "")[:80]
                line += f" Challenge → {pos.challenged}: {reason}"

            lines.append(line)

        return "\n".join(lines)

    def _format_all_rounds(self, rounds: List[Round]) -> str:
        """
        Formate TOUS les rounds pour le verdict (pas de troncation).

        Le synthétiseur reçoit la trajectoire complète.

        Args:
            rounds: Liste de tous les rounds.

        Returns:
            Texte formaté avec tous les rounds.
        """
        sections = []
        for rnd in rounds:
            sections.append(f"\n### Round {rnd.number}")
            sections.append(self._format_round_full(rnd, current_participant_id=""))
            if rnd.stability_score is not None:
                sections.append(
                    f"> Score de stabilité : {rnd.stability_score:.2f}"
                )
        return "\n".join(sections)

    # ============================================================
    # Réponses utilisateur
    # ============================================================

    @staticmethod
    def _format_user_answers(user_answers: List[UserAnswer]) -> str:
        """
        Formate les réponses utilisateur pour le contexte.

        Args:
            user_answers: Liste des réponses utilisateur.

        Returns:
            Texte formaté, ou chaîne vide si pas de réponse.
        """
        if not user_answers:
            return ""

        lines = []
        for answer in user_answers:
            lines.append(
                f"**Question de {answer.asked_by} (round {answer.round_number})** :\n"
                f"Q: {answer.question}\n"
                f"R: {answer.answer}"
            )
        return "\n\n".join(lines)

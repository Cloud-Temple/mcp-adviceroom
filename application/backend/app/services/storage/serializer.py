"""
Debate Serializer — Sérialisation complète et export des débats.

Trois formats :
- JSON complet (pour S3 et API)
- Markdown (pour export humain)
- HTML (wrappé autour du Markdown)

La sérialisation capture TOUT : turns, positions, tools, stability, verdict.
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..debate.models import (
    Debate,
    DebatePhase,
    DebateStatus,
    Participant,
    Position,
    Round,
    Turn,
    Verdict,
)

__all__ = [
    "serialize_debate_full",
    "export_debate_markdown",
    "export_debate_html",
]


# ============================================================
# Sérialisation complète → dict (pour S3 JSON)
# ============================================================

def serialize_debate_full(debate: Debate) -> Dict[str, Any]:
    """
    Sérialise un Debate complet en dict JSON-ready.

    Inclut TOUTES les données : turns, positions, tools, stability, verdict.
    C'est ce qui est stocké sur S3.
    """
    return {
        "id": debate.id,
        "question": debate.question,
        "mode": debate.mode.value if hasattr(debate.mode, 'value') else str(debate.mode),
        "status": debate.status.value,
        "phase": debate.phase.value,
        "created_at": debate.created_at.isoformat(),
        "completed_at": debate.completed_at.isoformat() if debate.completed_at else None,
        "total_tokens": debate.total_tokens,
        "error": debate.error,

        # Participants
        "participants": [
            _serialize_participant(p) for p in debate.participants
        ],

        # Opening
        "opening_turns": [
            _serialize_turn(t) for t in debate.opening_turns
        ],

        # Rounds de débat
        "rounds": [
            _serialize_round(r) for r in debate.rounds
        ],

        # Verdict
        "verdict": _serialize_verdict(debate.verdict) if debate.verdict else None,

        # User answers
        "user_answers": [
            {
                "question": a.question,
                "answer": a.answer,
                "asked_by": a.asked_by,
                "round_number": a.round_number,
                "timestamp": a.timestamp.isoformat(),
            }
            for a in debate.user_answers
        ],

        # Metadata
        "metadata": debate.metadata,

        # Stats techniques
        "stats": _compute_stats(debate),
    }


def _serialize_participant(p: Participant) -> Dict[str, Any]:
    return {
        "id": p.id,
        "model_id": p.model_id,
        "provider": p.provider,
        "display_name": p.display_name,
        "persona_id": p.persona_id,
        "persona_name": p.persona_name,
        "persona_description": p.persona_description,
        "persona_icon": p.persona_icon,
        "active": p.active,
        "consecutive_skips": p.consecutive_skips,
        "flags": p.flags,
    }


def _serialize_position(pos: Optional[Position]) -> Optional[Dict[str, Any]]:
    if not pos:
        return None
    return {
        "thesis": pos.thesis,
        "confidence": pos.confidence,
        "arguments": [str(a) for a in pos.arguments],
        "challenged": pos.challenged,
        "challenge_target": pos.challenge_target,
        "challenge_reason": pos.challenge_reason,
        "challenge_quality": pos.challenge_quality.value if pos.challenge_quality else None,
        "agrees_with": pos.agrees_with,
        "disagrees_with": pos.disagrees_with,
        "sentiment": pos.sentiment,
    }


def _serialize_turn(t: Turn) -> Dict[str, Any]:
    return {
        "participant_id": t.participant_id,
        "round_number": t.round_number,
        "phase": t.phase.value,
        "content": t.content,
        "position": _serialize_position(t.structured_position),
        "tool_calls": t.tool_calls,
        "tool_results": t.tool_results,
        "user_question": t.user_question,
        "flags": t.flags,
        "tokens_used": t.tokens_used,
        "duration_ms": t.duration_ms,
        "timestamp": t.timestamp.isoformat(),
        "error": t.error,
    }


def _serialize_round(r: Round) -> Dict[str, Any]:
    return {
        "number": r.number,
        "turns": [_serialize_turn(t) for t in r.turns],
        "stability_score": r.stability_score,
        "timestamp": r.timestamp.isoformat(),
    }


def _serialize_verdict(v: Verdict) -> Dict[str, Any]:
    return {
        "type": v.type.value,
        "confidence": v.confidence,
        "summary": v.summary,
        "agreement_points": v.agreement_points,
        "divergence_points": v.divergence_points,
        "recommendation": v.recommendation,
        "unresolved_questions": v.unresolved_questions,
        "key_insights": v.key_insights,
        "synthesizer_model": v.synthesizer_model,
        "tokens_used": v.tokens_used,
        "duration_ms": v.duration_ms,
    }


def _compute_stats(debate: Debate) -> Dict[str, Any]:
    """Calcule des stats techniques globales sur le débat."""
    all_turns = list(debate.opening_turns)
    for r in debate.rounds:
        all_turns.extend(r.turns)

    total_duration = sum(t.duration_ms for t in all_turns)
    total_tokens = sum(t.tokens_used for t in all_turns)
    tool_calls_count = sum(len(t.tool_calls) for t in all_turns)
    errors_count = sum(1 for t in all_turns if t.error)

    # Tokens par participant
    tokens_by_participant = {}
    for t in all_turns:
        pid = t.participant_id
        if pid not in tokens_by_participant:
            tokens_by_participant[pid] = {"tokens": 0, "turns": 0, "duration_ms": 0}
        tokens_by_participant[pid]["tokens"] += t.tokens_used
        tokens_by_participant[pid]["turns"] += 1
        tokens_by_participant[pid]["duration_ms"] += t.duration_ms

    # Évolution des positions (confiance par round)
    position_evolution = {}
    for t in all_turns:
        if t.structured_position:
            pid = t.participant_id
            if pid not in position_evolution:
                position_evolution[pid] = []
            position_evolution[pid].append({
                "round": t.round_number,
                "thesis": t.structured_position.thesis,
                "confidence": t.structured_position.confidence,
            })

    # Stabilité par round
    stability_history = [
        {"round": r.number, "score": r.stability_score}
        for r in debate.rounds
        if r.stability_score is not None
    ]

    return {
        "total_turns": len(all_turns),
        "total_tokens": total_tokens,
        "total_duration_ms": total_duration,
        "total_rounds": len(debate.rounds),
        "tool_calls_count": tool_calls_count,
        "errors_count": errors_count,
        "tokens_by_participant": tokens_by_participant,
        "position_evolution": position_evolution,
        "stability_history": stability_history,
    }


# ============================================================
# Export Markdown
# ============================================================

def export_debate_markdown(debate_dict: Dict[str, Any]) -> str:
    """
    Exporte un débat sérialisé en Markdown lisible.

    Args:
        debate_dict: Débat sérialisé (via serialize_debate_full).

    Returns:
        Document Markdown complet.
    """
    lines = []

    # Header
    lines.append(f"# 🏛️ AdviceRoom — Débat")
    lines.append("")
    lines.append(f"**Question :** {debate_dict['question']}")
    lines.append(f"**Statut :** {debate_dict['status']}")
    lines.append(f"**Date :** {debate_dict['created_at']}")
    lines.append("")

    # Participants
    lines.append("## 👥 Participants")
    lines.append("")
    for p in debate_dict.get("participants", []):
        icon = p.get("persona_icon", "🤖")
        lines.append(
            f"- {icon} **{p['display_name']}** ({p['id']}) "
            f"— {p.get('persona_name', '')} [{p['provider']}]"
        )
    lines.append("")

    # Stats techniques
    stats = debate_dict.get("stats", {})
    if stats:
        lines.append("## 📊 Statistiques techniques")
        lines.append("")
        lines.append(f"| Métrique | Valeur |")
        lines.append(f"|----------|--------|")
        lines.append(f"| Rounds | {stats.get('total_rounds', 0)} |")
        lines.append(f"| Tours total | {stats.get('total_turns', 0)} |")
        lines.append(f"| Tokens total | {stats.get('total_tokens', 0)} |")
        dur_s = stats.get("total_duration_ms", 0) / 1000
        lines.append(f"| Durée totale | {dur_s:.1f}s |")
        lines.append(f"| Appels outils | {stats.get('tool_calls_count', 0)} |")
        lines.append(f"| Erreurs | {stats.get('errors_count', 0)} |")
        lines.append("")

        # Tokens par participant
        tbp = stats.get("tokens_by_participant", {})
        if tbp:
            lines.append("### Tokens par participant")
            lines.append("")
            lines.append("| Participant | Tokens | Tours | Durée |")
            lines.append("|------------|--------|-------|-------|")
            for pid, data in tbp.items():
                dur = data.get("duration_ms", 0) / 1000
                lines.append(
                    f"| {pid} | {data['tokens']} | {data['turns']} | {dur:.1f}s |"
                )
            lines.append("")

    # Opening
    opening = debate_dict.get("opening_turns", [])
    if opening:
        lines.append("## 📖 Phase 1 — Ouverture")
        lines.append("")
        for turn in opening:
            _render_turn_md(lines, turn, debate_dict)
        lines.append("")

    # Rounds
    for rnd in debate_dict.get("rounds", []):
        lines.append(f"## 💬 Round {rnd['number']}")
        lines.append("")
        for turn in rnd.get("turns", []):
            _render_turn_md(lines, turn, debate_dict)

        # Stabilité
        if rnd.get("stability_score") is not None:
            score = rnd["stability_score"]
            bar_len = 20
            filled = int(score * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"> 📊 Stabilité : {bar} {score:.0%}")
            lines.append("")

    # Verdict
    verdict = debate_dict.get("verdict")
    if verdict:
        lines.append("## ⚖️ Verdict")
        lines.append("")
        vtype = verdict.get("type", "?").upper()
        lines.append(f"**Type :** {vtype}")
        lines.append(f"**Confiance :** {verdict.get('confidence', 0)}%")
        lines.append("")

        if verdict.get("summary"):
            lines.append("### Synthèse")
            lines.append("")
            lines.append(verdict["summary"].strip())
            lines.append("")

        agreement = verdict.get("agreement_points", [])
        if agreement:
            lines.append("### ✅ Points d'accord")
            lines.append("")
            for pt in agreement:
                lines.append(f"- {pt}")
            lines.append("")

        divergence = verdict.get("divergence_points", [])
        if divergence:
            lines.append("### ❌ Points de divergence")
            lines.append("")
            for pt in divergence:
                if isinstance(pt, dict):
                    topic = pt.get("topic", "")
                    lines.append(f"- **{topic}**")
                else:
                    lines.append(f"- {pt}")
            lines.append("")

        if verdict.get("recommendation"):
            lines.append("### 💡 Recommandation")
            lines.append("")
            lines.append(verdict["recommendation"].strip())
            lines.append("")

        insights = verdict.get("key_insights", [])
        if insights:
            lines.append("### 🔍 Insights clés")
            lines.append("")
            for ins in insights:
                lines.append(f"- {ins}")
            lines.append("")

    # Position evolution
    pe = stats.get("position_evolution", {}) if stats else {}
    if pe:
        lines.append("## 📈 Évolution des positions")
        lines.append("")
        lines.append("| Participant | Round | Confiance | Thèse |")
        lines.append("|------------|-------|-----------|-------|")
        for pid, positions in pe.items():
            for pos in positions:
                r = "Ouv." if pos["round"] == 0 else f"R{pos['round']}"
                thesis = pos["thesis"][:60]
                lines.append(f"| {pid} | {r} | {pos['confidence']}% | {thesis} |")
        lines.append("")

    lines.append("---")
    lines.append(f"*Exporté par AdviceRoom — {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(lines)


def _render_turn_md(lines: List[str], turn: Dict, debate_dict: Dict):
    """Rend un tour de parole en Markdown."""
    pid = turn.get("participant_id", "?")

    # Trouver le participant
    p_info = next(
        (p for p in debate_dict.get("participants", []) if p["id"] == pid),
        {"display_name": pid, "persona_icon": "🤖", "persona_name": "", "provider": ""}
    )
    icon = p_info.get("persona_icon", "🤖")
    name = p_info.get("display_name", pid)
    persona = p_info.get("persona_name", "")

    lines.append(f"### {icon} {name} — {persona}")
    lines.append("")

    # Erreur
    if turn.get("error"):
        lines.append(f"> ❌ **Erreur :** {turn['error']}")
        lines.append("")
        return

    # Contenu
    content = turn.get("content", "")
    if content:
        lines.append(content.strip())
        lines.append("")

    # Tools
    for i, tc in enumerate(turn.get("tool_calls", [])):
        tc_name = tc.get("name", "?")
        results = turn.get("tool_results", [])
        lines.append(f"🔧 **Outil :** `{tc_name}`")
        if i < len(results):
            res = results[i].get("result", {})
            if isinstance(res, dict) and res.get("status") == "success":
                lines.append(f"> Résultat : ✅ (voir contenu)")
            elif isinstance(res, dict) and res.get("error"):
                lines.append(f"> Résultat : ❌ {res['error']}")
        lines.append("")

    # Position
    pos = turn.get("position")
    if pos:
        lines.append(f"> 💭 **Thèse :** {pos.get('thesis', '')}")
        lines.append(f"> 📊 **Confiance :** {pos.get('confidence', '?')}%")
        args = pos.get("arguments", [])
        if args:
            lines.append(f"> 📌 **Arguments :**")
            for a in args[:5]:
                lines.append(f">   - {a}")
        if pos.get("challenged"):
            lines.append(f"> ⚔️ **Challenge →** {pos['challenged']}")
            if pos.get("challenge_reason"):
                lines.append(f">   {pos['challenge_reason'][:200]}")
        lines.append("")

    # Stats du tour
    tokens = turn.get("tokens_used", 0)
    dur = turn.get("duration_ms", 0)
    dur_str = f"{dur}ms" if dur < 1000 else f"{dur/1000:.1f}s"
    lines.append(f"*{tokens} tokens, {dur_str}*")
    lines.append("")


# ============================================================
# Export HTML (wrapper autour du Markdown)
# ============================================================

def export_debate_html(debate_dict: Dict[str, Any]) -> str:
    """
    Exporte un débat en HTML (Markdown → HTML).

    Utilise un rendu simple avec styles inline pour portabilité.
    """
    md = export_debate_markdown(debate_dict)

    # Conversion MD → HTML basique (sans dépendance markdown)
    # On wrap le Markdown dans une page HTML avec styles
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AdviceRoom — Débat</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333;
               line-height: 1.6; }}
        h1 {{ color: #1a56db; border-bottom: 2px solid #1a56db; padding-bottom: 10px; }}
        h2 {{ color: #374151; margin-top: 30px; }}
        h3 {{ color: #4b5563; }}
        table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
        th, td {{ border: 1px solid #d1d5db; padding: 8px 12px; text-align: left; }}
        th {{ background: #f3f4f6; font-weight: 600; }}
        blockquote {{ border-left: 3px solid #60a5fa; margin: 10px 0; padding: 5px 15px;
                      background: #eff6ff; }}
        code {{ background: #f3f4f6; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }}
        pre {{ background: #f3f4f6; padding: 15px; border-radius: 5px; overflow-x: auto; }}
        hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 30px 0; }}
        em {{ color: #6b7280; }}
    </style>
</head>
<body>
<pre style="white-space: pre-wrap; font-family: inherit;">{_escape_html(md)}</pre>
</body>
</html>"""
    return html


def _escape_html(text: str) -> str:
    """Échappe les caractères HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

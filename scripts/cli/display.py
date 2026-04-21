# -*- coding: utf-8 -*-
"""
Fonctions d'affichage Rich pour le CLI AdviceRoom.

Chaque endpoint admin a sa propre fonction show_xxx_result().
Partagées entre commands.py (Click) et shell.py (interactif).
"""

import json
import textwrap
from typing import Dict, List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.syntax import Syntax
from rich import box

console = Console()

# Styles par provider LLM (couleur, label court)
PROVIDER_STYLES = {
    "llmaas":    ("cyan",   "SNC"),
    "openai":    ("green",  "OpenAI"),
    "anthropic": ("yellow", "Anthropic"),
    "google":    ("blue",   "Google"),
}


# =============================================================================
# Utilitaires communs
# =============================================================================

def show_error(msg: str):
    """Affiche un message d'erreur."""
    console.print(f"[red]❌ {msg}[/red]")


def show_success(msg: str):
    """Affiche un message de succès."""
    console.print(f"[green]✅ {msg}[/green]")


def show_warning(msg: str):
    """Affiche un avertissement."""
    console.print(f"[yellow]⚠️  {msg}[/yellow]")


def show_json(data: dict):
    """Affiche un dict en JSON coloré."""
    console.print(Syntax(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        "json",
    ))


def _style_for(provider: str) -> tuple:
    """Retourne (couleur, label) pour un provider."""
    return PROVIDER_STYLES.get(provider, ("white", provider or "?"))


def _wrap(text: str, width: int = 90) -> str:
    """Wrap un texte long en préservant les sauts de ligne."""
    lines = text.split("\n")
    wrapped = []
    for line in lines:
        if len(line) > width:
            wrapped.extend(textwrap.wrap(line, width=width))
        else:
            wrapped.append(line)
    return "\n".join(wrapped)


def _dur(ms) -> str:
    """Formate une durée ms → chaîne lisible."""
    if not ms:
        return "—"
    ms = int(ms)
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60000:
        return f"{ms / 1000:.1f}s"
    return f"{ms / 60000:.1f}min"


def _dur_s(seconds) -> str:
    """Formate une durée en secondes → chaîne lisible."""
    if not seconds:
        return "—"
    s = float(seconds)
    if s < 60:
        return f"{s:.1f}s"
    m = int(s // 60)
    sec = int(s % 60)
    return f"{m}min {sec}s"


# =============================================================================
# health — GET /admin/api/health
# =============================================================================

def show_health_result(result: dict):
    """Affiche le résultat de /admin/api/health."""
    status = result.get("status", "?")
    version = result.get("version", "?")
    py = result.get("python_version", "?")
    s3 = result.get("s3_status", "?")
    llm = result.get("llm_status", "?")
    models = result.get("llm_models_count", 0)
    tools = result.get("tools", [])
    tools_count = result.get("tools_count", len(tools))

    icon = "✅" if status == "ok" else "❌"

    table = Table(
        title=f"{icon} AdviceRoom — Health Check",
        show_header=True, box=box.ROUNDED,
    )
    table.add_column("Composant", style="cyan bold", min_width=18)
    table.add_column("Statut", min_width=10)
    table.add_column("Détails", style="dim")

    # Serveur
    table.add_row(
        "Serveur", f"[green]✅ v{version}[/]", f"Python {py}",
    )

    # S3
    s3_icon = "✅" if s3 == "ok" else ("⚠️" if s3 == "not_configured" else "❌")
    s3_color = "green" if s3 == "ok" else ("yellow" if s3 == "not_configured" else "red")
    table.add_row("S3 Storage", f"[{s3_color}]{s3_icon} {s3}[/]", "")

    # LLM Router
    llm_icon = "✅" if llm == "ok" else "❌"
    llm_color = "green" if llm == "ok" else "red"
    table.add_row(
        "LLM Router",
        f"[{llm_color}]{llm_icon} {llm}[/]",
        f"{models} modèles" if models else "",
    )

    # MCP Tools
    table.add_row(
        "MCP Tools",
        f"[green]✅ {tools_count}[/]" if tools_count else "[yellow]⚠️ 0[/]",
        ", ".join(tools[:5]) if tools else "",
    )

    console.print(table)


# =============================================================================
# whoami — GET /admin/api/whoami
# =============================================================================

def show_whoami_result(result: dict, url: str = ""):
    """Affiche le résultat de /admin/api/whoami."""
    auth_type = result.get("auth_type", "?")
    client = result.get("client_name", "?")
    perms = ", ".join(result.get("permissions", []))
    email = result.get("email", "")
    hash_prefix = result.get("hash_prefix", "")

    lines = []
    if url:
        lines.append(f"[bold]URL        :[/bold] [dim]{url}[/dim]")
    lines.append(f"[bold]Auth type  :[/bold] [cyan]{auth_type}[/cyan]")
    lines.append(f"[bold]Client     :[/bold] [green]{client}[/green]")
    lines.append(f"[bold]Permissions:[/bold] {perms}")
    if hash_prefix:
        lines.append(f"[bold]Hash       :[/bold] [dim]{hash_prefix}…[/dim]")
    if email:
        lines.append(f"[bold]Email      :[/bold] {email}")

    console.print(Panel.fit(
        "\n".join(lines),
        title="👤 Identité",
        border_style="cyan",
    ))


# =============================================================================
# models — GET /admin/api/models
# =============================================================================

def show_models_result(result: dict):
    """Affiche la liste des modèles LLM."""
    models = result.get("models", [])
    total = result.get("total", len(models))

    table = Table(
        title=f"🤖 Modèles LLM ({total})",
        show_header=True, box=box.ROUNDED,
    )
    table.add_column("ID", style="cyan bold", min_width=18)
    table.add_column("Nom", min_width=16)
    table.add_column("Provider", min_width=10)
    table.add_column("Catégorie", style="dim")
    table.add_column("Actif", justify="center")

    for m in models:
        provider = m.get("provider", "?")
        style, label = _style_for(provider)
        active = "[green]✅[/]" if m.get("active", True) else "[red]❌[/]"
        table.add_row(
            m.get("id", "?"),
            m.get("display_name", "?"),
            f"[{style}]{label}[/]",
            m.get("category", ""),
            active,
        )

    console.print(table)


# =============================================================================
# tokens — GET/POST/DELETE /admin/api/tokens
# =============================================================================

def show_token_list_result(result: dict):
    """Affiche la liste des tokens."""
    tokens = result.get("tokens", [])

    table = Table(
        title=f"🔑 Tokens ({len(tokens)})",
        show_header=True, box=box.ROUNDED,
    )
    table.add_column("Client", style="cyan bold")
    table.add_column("Email", style="dim")
    table.add_column("Permissions", style="green")
    table.add_column("Hash", style="dim")
    table.add_column("Statut")

    for t in tokens:
        status = "[red]révoqué[/]" if t.get("revoked") else "[green]actif[/]"
        perms = ", ".join(t.get("permissions", []))
        table.add_row(
            t.get("client_name", "?"),
            t.get("email", "") or "—",
            perms,
            t.get("hash_prefix", "?") + "…",
            status,
        )

    console.print(table)


def show_token_create_result(result: dict):
    """Affiche le résultat de la création de token."""
    raw = result.get("raw_token", result.get("token", "?"))
    name = result.get("client_name", "?")
    perms = ", ".join(result.get("permissions", []))
    email = result.get("email", "")

    console.print(Panel.fit(
        f"[bold]Client  :[/bold] [cyan]{name}[/cyan]\n"
        f"[bold]Email   :[/bold] {email or '[dim]—[/dim]'}\n"
        f"[bold]Perms   :[/bold] {perms}\n"
        f"\n[bold yellow]⚠️  Token (affiché UNE SEULE FOIS) :[/bold yellow]\n"
        f"[green bold]{raw}[/green bold]",
        title="🔑 Token créé",
        border_style="green",
    ))


def show_token_revoke_result(result: dict):
    """Affiche le résultat de la révocation."""
    msg = result.get("message", "Token révoqué")
    show_success(msg)


# =============================================================================
# debates — GET /admin/api/debates
# =============================================================================

def show_debates_list_result(result: dict):
    """Affiche la liste des débats (mémoire + S3)."""
    debates = result.get("debates", [])
    total = result.get("total", len(debates))

    if not debates:
        console.print("[dim]Aucun débat trouvé.[/dim]")
        return

    table = Table(
        title=f"🏛️ Débats ({total})",
        show_header=True, box=box.ROUNDED,
    )
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Question", min_width=30, max_width=50)
    table.add_column("Statut", justify="center")
    table.add_column("Participants", justify="center")
    table.add_column("Rounds", justify="center")
    table.add_column("Tokens", justify="right", style="dim")
    table.add_column("Verdict", min_width=14)
    table.add_column("Source", style="dim", justify="center")

    for d in debates:
        # ID tronqué
        did = d.get("id", "?")[:11]

        # Question tronquée
        question = d.get("question", "?")
        if len(question) > 48:
            question = question[:45] + "..."

        # Statut avec couleur
        status = d.get("status", "?")
        if status == "completed":
            status_str = "[green]✅ terminé[/]"
        elif status in ("running", "active"):
            status_str = "[yellow]⏳ en cours[/]"
        else:
            status_str = f"[dim]{status}[/]"

        # Participants avec badges colorés
        participants = d.get("participants", [])
        p_badges = []
        for p in participants[:4]:
            prov = p.get("provider", "")
            style, label = _style_for(prov)
            name = p.get("display_name", p.get("model_id", "?"))
            # Nom court
            short = name[:12] if len(name) > 12 else name
            p_badges.append(f"[{style}]{short}[/]")
        p_str = ", ".join(p_badges) if p_badges else str(d.get("num_participants", "?"))

        # Rounds
        rounds = str(d.get("num_rounds", "—"))

        # Tokens
        tokens = d.get("total_tokens", 0)
        tokens_str = f"{tokens:,}" if tokens else "—"

        # Verdict
        verdict = d.get("verdict")
        if verdict:
            vtype = verdict.get("type", "")
            vconf = verdict.get("confidence", 0)
            type_map = {
                "consensus":         ("[green]", "✅"),
                "consensus_partiel": ("[yellow]", "⚠️"),
                "dissensus":         ("[red]",   "❌"),
            }
            color, icon = type_map.get(vtype, ("[dim]", ""))
            verdict_str = f"{color}{icon} {vtype} {vconf}%[/]"
        else:
            verdict_str = "[dim]—[/]"

        # Source
        source = d.get("source", "?")

        table.add_row(
            did, question, status_str, p_str, rounds,
            tokens_str, verdict_str, source,
        )

    console.print(table)


# =============================================================================
# debate get — GET /admin/api/debates/{id}
# =============================================================================

def show_debate_detail_result(result: dict):
    """Affiche les détails d'un débat."""
    source = result.get("source", "?")
    debate = result.get("debate", {})

    if not debate:
        show_error("Données de débat vides")
        return

    did = debate.get("id", "?")
    question = debate.get("question", "?")
    status = debate.get("status", "?")
    phase = debate.get("phase", "")
    created = debate.get("created_at", "")[:19] if debate.get("created_at") else ""
    total_tokens = debate.get("total_tokens", 0)

    # ── Header ──
    console.print()
    console.print(Panel.fit(
        f"[bold]ID       :[/bold] [dim]{did}[/dim]\n"
        f"[bold]Question :[/bold] {question}\n"
        f"[bold]Statut   :[/bold] {status}\n"
        f"[bold]Phase    :[/bold] {phase}\n"
        f"[bold]Créé     :[/bold] {created}\n"
        f"[bold]Tokens   :[/bold] {total_tokens:,}\n"
        f"[bold]Source   :[/bold] {source}",
        title="🏛️ Détails du Débat",
        border_style="blue",
    ))

    # ── Participants ──
    participants = debate.get("participants", [])
    if participants:
        table = Table(
            title=f"👥 Participants ({len(participants)})",
            show_header=True, box=box.ROUNDED,
        )
        table.add_column("Modèle", style="cyan bold")
        table.add_column("Provider")
        table.add_column("Persona", style="dim")

        for p in participants:
            provider = p.get("provider", "?")
            style, label = _style_for(provider)
            icon = p.get("persona_icon", "🤖")
            table.add_row(
                f"{icon} {p.get('display_name', p.get('model_id', '?'))}",
                f"[{style}]{label}[/]",
                p.get("persona_name", "auto"),
            )
        console.print(table)

    # ── Rounds ──
    rounds = debate.get("rounds", [])
    if rounds:
        console.print(f"\n  [bold]📊 Rounds :[/bold] {len(rounds)}")
        for i, r in enumerate(rounds):
            turns = r.get("turns", [])
            stab = r.get("stability", {})
            score = stab.get("score", 0) if stab else 0
            console.print(
                f"    Round {i+1} : {len(turns)} tours, "
                f"stabilité {score:.0%}" if score else
                f"    Round {i+1} : {len(turns)} tours"
            )

    # ── Verdict ──
    verdict = debate.get("verdict")
    if verdict:
        vtype = verdict.get("type", "?")
        vconf = verdict.get("confidence", 0)
        summary = verdict.get("summary", "")

        type_map = {
            "consensus":         ("green",  "✅ CONSENSUS"),
            "consensus_partiel": ("yellow", "⚠️  CONSENSUS PARTIEL"),
            "dissensus":         ("red",    "❌ DISSENSUS"),
        }
        color, type_label = type_map.get(vtype, ("white", vtype.upper()))

        parts = [f"[{color} bold]{type_label}[/] — Confiance : [{color}]{vconf}%[/]"]

        if summary:
            parts.append("")
            parts.append("[bold]📝 Synthèse :[/]")
            parts.append(_wrap(summary.strip(), width=85))

        agreement = verdict.get("agreement_points", [])
        if agreement:
            parts.append("")
            parts.append("[bold green]✅ Points d'accord :[/]")
            for pt in agreement[:5]:
                parts.append(f"   • {pt}")

        divergence = verdict.get("divergence_points", [])
        if divergence:
            parts.append("")
            parts.append("[bold red]❌ Points de divergence :[/]")
            for pt in divergence[:5]:
                if isinstance(pt, dict):
                    parts.append(f"   • {pt.get('point', pt.get('topic', str(pt)[:80]))}")
                else:
                    parts.append(f"   • {pt}")

        recommendation = verdict.get("recommendation", "")
        if recommendation:
            parts.append("")
            parts.append("[bold cyan]💡 Recommandation :[/]")
            parts.append(f"   {_wrap(recommendation.strip(), width=82)}")

        insights = verdict.get("key_insights", [])
        if insights:
            parts.append("")
            parts.append("[bold]🔍 Insights :[/]")
            for ins in insights[:5]:
                parts.append(f"   • {ins}")

        console.print()
        console.print(Panel(
            "\n".join(parts),
            title="[bold]⚖️  VERDICT[/]",
            border_style=color,
            padding=(1, 3),
        ))

    console.print()


# =============================================================================
# debate delete — DELETE /admin/api/debates/{id}
# =============================================================================

def show_debate_delete_result(result: dict):
    """Affiche le résultat de suppression d'un débat."""
    msg = result.get("message", "Débat supprimé")
    deleted_from = result.get("deleted_from", [])
    show_success(f"{msg} (sources: {', '.join(deleted_from)})")


# =============================================================================
# logs — GET /admin/api/logs
# =============================================================================

def show_logs_result(result: dict):
    """Affiche les logs d'activité récents."""
    logs = result.get("logs", [])
    count = result.get("count", len(logs))

    if not logs:
        console.print("[dim]Aucun log récent.[/dim]")
        return

    table = Table(
        title=f"📋 Activité récente ({count} entrées)",
        show_header=True, box=box.SIMPLE,
    )
    table.add_column("Heure", style="dim", min_width=8)
    table.add_column("Méthode", style="cyan", min_width=6)
    table.add_column("Path", min_width=20)
    table.add_column("Status", justify="center")
    table.add_column("Durée", style="dim", justify="right")

    for log in logs[-30:]:  # Derniers 30
        ts = log.get("timestamp", "")
        time_str = ts[11:19] if len(ts) > 19 else ts
        method = log.get("method", "?")
        path = log.get("path", "?")
        status = log.get("status_code", "?")
        duration = log.get("duration_ms", "")

        status_color = "green" if str(status).startswith("2") else "red"

        table.add_row(
            time_str, method, path,
            f"[{status_color}]{status}[/]",
            f"{duration}ms" if duration else "",
        )

    console.print(table)


# =============================================================================
# llm-activity — GET /admin/api/llm-activity
# =============================================================================

def show_llm_activity_result(result: dict):
    """Affiche l'activité LLM (tours, verdicts, erreurs)."""
    logs = result.get("logs", [])
    count = result.get("count", len(logs))

    if not logs:
        console.print("[dim]Aucune activité LLM récente.[/dim]")
        return

    table = Table(
        title=f"🤖 Activité LLM ({count} événements)",
        show_header=True, box=box.SIMPLE,
    )
    table.add_column("Heure", style="dim", min_width=8)
    table.add_column("Type", style="cyan", min_width=10)
    table.add_column("Modèle", min_width=16)
    table.add_column("Tokens", justify="right", style="dim")
    table.add_column("Durée", justify="right", style="dim")
    table.add_column("Détails", max_width=30)

    for log in logs[-30:]:
        ts = log.get("timestamp", "")
        time_str = ts[11:19] if len(ts) > 19 else ts
        etype = log.get("type", "?")
        model = log.get("model", log.get("model_id", "?"))
        tokens = log.get("tokens", log.get("tokens_used", ""))
        duration = log.get("duration_ms", "")
        details = log.get("error", log.get("phase", ""))

        # Couleur par type
        type_colors = {
            "turn": "green", "verdict": "blue",
            "error": "red", "retry": "yellow",
        }
        tc = type_colors.get(etype, "white")

        table.add_row(
            time_str,
            f"[{tc}]{etype}[/]",
            model[:16] if model else "?",
            str(tokens) if tokens else "",
            _dur(duration) if duration else "",
            str(details)[:28] if details else "",
        )

    console.print(table)


# =============================================================================
# DebateRenderer — Affichage temps réel d'un débat NDJSON
# =============================================================================

class DebateRenderer:
    """
    Rend un débat en temps réel via Rich.

    Chaque événement NDJSON est dispatché vers un handler _on_<type>.
    Accumule les positions pour la table récapitulative finale.
    """

    def __init__(self):
        self.participants: Dict[str, dict] = {}
        self.position_history: Dict[str, List[dict]] = {}
        self.total_tokens = 0
        self.start_time = 0.0

    def handle(self, event: dict):
        """Dispatche un événement vers le handler approprié."""
        etype = event.get("type", "unknown")
        handler = getattr(self, f"_on_{etype}", None)
        if handler:
            handler(event)
        else:
            raw = json.dumps(event, ensure_ascii=False)[:150]
            console.print(f"  [dim]\\[{etype}] {raw}[/]")

    def _on_debate_start(self, e: dict):
        import time
        self.start_time = time.time()
        console.print()
        console.print(Rule("[bold blue]🏛️  Débat lancé[/]", style="blue"))
        console.print()
        console.print(f"  [bold]Question :[/] {e.get('question', '?')}")
        console.print(f"  [bold]Participants :[/]")

        for p in e.get("participants", []):
            pid = p.get("id", p.get("model", "?"))
            name = p.get("display_name", pid)
            provider = p.get("provider", "")
            persona = p.get("persona", "")
            icon = p.get("icon", "")
            style, label = _style_for(provider)

            self.participants[pid] = {
                "display_name": name, "provider": provider,
                "persona": persona, "icon": icon,
                "style": style, "label": label,
            }

            parts = f"     [{style}]• {icon} {name}[/]"
            if persona:
                parts += f" [dim]— {persona}[/]"
            parts += f" [dim]\\[{label}][/]"
            console.print(parts)
        console.print()

    def _on_phase(self, e: dict):
        phase = e.get("phase", "?").upper()
        round_num = e.get("round", "")
        labels = {
            "OPENING": "📖 OUVERTURE — Positions initiales (parallèle)",
            "DEBATE":  f"💬 DÉBAT — Round {round_num}",
            "VERDICT": "⚖️  VERDICT — Synthèse finale",
        }
        label = labels.get(phase, f"Phase : {phase}")
        console.print()
        console.print(Rule(f"[bold]{label}[/]", style="dim"))
        console.print()

    def _on_turn_start(self, e: dict):
        p = e.get("participant", {})
        pid = p.get("id", "?")
        info = self.participants.get(pid, {})
        name = info.get("display_name", p.get("display_name", pid))
        icon = info.get("icon", p.get("icon", ""))
        console.print(f"  [dim]⏳ {icon} {name} réfléchit...[/]")

    def _on_turn_end(self, e: dict):
        pid = e.get("participant_id", "?")
        p_evt = e.get("participant", {})
        info = self.participants.get(pid, {})

        name = info.get("display_name", p_evt.get("display_name", pid))
        style = info.get("style", _style_for(p_evt.get("provider", ""))[0])
        label = info.get("label", _style_for(p_evt.get("provider", ""))[1])
        icon = info.get("icon", p_evt.get("icon", ""))
        persona = info.get("persona", p_evt.get("persona", ""))

        content = e.get("content", "")
        tokens = e.get("tokens_used", 0)
        duration = e.get("duration_ms", 0)
        position = e.get("position")
        error = e.get("error")
        tool_calls = e.get("tool_calls", [])
        tool_results = e.get("tool_results", [])

        self.total_tokens += tokens

        parts: List[str] = []

        if error:
            parts.append(f"[red bold]❌ Erreur : {error}[/]")
        elif content:
            parts.append(_wrap(content.strip(), width=88))

        if tool_calls:
            parts.append("")
            parts.append("[bold]🔧 Outils utilisés :[/]")
            for i, tc in enumerate(tool_calls):
                tc_name = tc.get("name", "?")
                tc_args = tc.get("arguments", {})
                args_str = json.dumps(tc_args, ensure_ascii=False)[:80]
                parts.append(f"  • [cyan]{tc_name}[/]({args_str})")
                if i < len(tool_results):
                    res = tool_results[i].get("result", {})
                    if isinstance(res, dict) and "error" not in res:
                        res_str = json.dumps(res, ensure_ascii=False)[:120]
                        parts.append(f"    → [dim]{res_str}[/]")

        if position:
            thesis = position.get("thesis", "")
            confidence = position.get("confidence", "?")
            arguments = position.get("arguments", [])
            challenged = position.get("challenged")
            challenge_reason = position.get("challenge_reason")

            parts.append("")
            parts.append(f"[bold]💭 Thèse :[/] \"{thesis}\"")
            parts.append(f"[bold]📊 Confiance :[/] [bold]{confidence}%[/]")

            if arguments:
                parts.append("[bold]📌 Arguments :[/]")
                for arg in arguments[:5]:
                    parts.append(f"   • {arg}")

            if challenged:
                ch_name = self.participants.get(challenged, {}).get(
                    "display_name", challenged
                )
                parts.append(f"[bold red]⚔️  Challenge →[/] {ch_name}")
                if challenge_reason:
                    parts.append(f"   [italic]{challenge_reason[:200]}[/]")

            if pid not in self.position_history:
                self.position_history[pid] = []
            self.position_history[pid].append({
                "round": e.get("round", 0),
                "thesis": thesis,
                "confidence": confidence,
            })

        dur_str = _dur(duration)
        footer = f"⏱  {tokens} tokens, {dur_str}"

        title = f"{icon} {name}"
        if persona:
            title += f" — {persona}"
        title += f" [dim]\\[{label}][/]"

        panel_content = "\n".join(parts) if parts else "[dim]Pas de contenu[/]"
        console.print(Panel(
            panel_content,
            title=f"[{style} bold]{title}[/]",
            subtitle=f"[dim]{footer}[/]",
            border_style=style,
            padding=(0, 2),
        ))

    def _on_stability(self, e: dict):
        score = e.get("score", 0)
        can_stop = e.get("can_stop", False)
        round_num = e.get("round", "?")

        bar_len = 30
        filled = int(score * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        color = "green" if score >= 0.85 else ("yellow" if score >= 0.5 else "red")
        status = "[green bold]✓ STABLE[/]" if can_stop else "[yellow]→ CONTINUE[/]"

        console.print(
            f"\n  📊 [bold]Stabilité Round {round_num}[/] : "
            f"[{color}]{bar}[/] [{color} bold]{score:.0%}[/] {status}\n"
        )

    def _on_verdict(self, e: dict):
        vtype = e.get("verdict_type", "?")
        confidence = e.get("confidence", 0)
        summary = e.get("summary", "")
        agreement = e.get("agreement_points", [])
        divergence = e.get("divergence_points", [])
        recommendation = e.get("recommendation", "")
        insights = e.get("key_insights", [])

        type_map = {
            "consensus":         ("green",  "✅ CONSENSUS"),
            "consensus_partiel": ("yellow", "⚠️  CONSENSUS PARTIEL"),
            "dissensus":         ("red",    "❌ DISSENSUS"),
        }
        color, type_label = type_map.get(vtype, ("white", vtype.upper()))

        parts = [f"[{color} bold]{type_label}[/] — Confiance : [{color}]{confidence}%[/]"]

        if summary:
            parts.extend(["", "[bold]📝 Synthèse :[/]", _wrap(summary.strip(), width=85)])
        if agreement:
            parts.extend(["", "[bold green]✅ Points d'accord :[/]"])
            for pt in agreement:
                parts.append(f"   • {pt}")
        if divergence:
            parts.extend(["", "[bold red]❌ Points de divergence :[/]"])
            for pt in divergence:
                if isinstance(pt, dict):
                    parts.append(f"   • {pt.get('point', str(pt))}")
                else:
                    parts.append(f"   • {pt}")
        if recommendation:
            parts.extend(["", "[bold cyan]💡 Recommandation :[/]",
                           f"   {_wrap(recommendation.strip(), width=82)}"])
        if insights:
            parts.extend(["", "[bold]🔍 Insights clés :[/]"])
            for ins in insights:
                parts.append(f"   • {ins}")

        console.print()
        console.print(Panel(
            "\n".join(parts),
            title="[bold]⚖️  VERDICT[/]",
            border_style=color,
            padding=(1, 3),
        ))

    def _on_debate_end(self, e: dict):
        import time
        status = e.get("status", "?")
        rounds = e.get("rounds", 0)
        total_tokens = e.get("total_tokens", self.total_tokens)
        elapsed = time.time() - self.start_time if self.start_time else 0

        console.print()

        # Table d'évolution des positions
        if self.position_history:
            console.print(Rule("[bold]📊 Évolution des Positions[/]", style="dim"))
            console.print()

            all_rounds = sorted({
                p["round"]
                for positions in self.position_history.values()
                for p in positions
            })

            table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
            table.add_column("Participant", style="bold", min_width=16)
            table.add_column("Thèse (dernière)", min_width=28)
            for r in all_rounds:
                lbl = "Ouv." if r == 0 else f"R{r}"
                table.add_column(lbl, justify="center", min_width=7)

            for pid, positions in self.position_history.items():
                info = self.participants.get(pid, {})
                name = info.get("display_name", pid)
                pstyle = info.get("style", "white")

                thesis = positions[-1]["thesis"] if positions else "?"
                thesis_short = (thesis[:38] + "...") if len(thesis) > 38 else thesis

                conf_by_round = {p["round"]: p["confidence"] for p in positions}
                cells = []
                prev = None
                for r in all_rounds:
                    conf = conf_by_round.get(r)
                    if conf is not None:
                        if prev is not None and conf > prev:
                            cells.append(f"[green]{conf}% ↑[/]")
                        elif prev is not None and conf < prev:
                            cells.append(f"[red]{conf}% ↓[/]")
                        else:
                            cells.append(f"{conf}%")
                        prev = conf
                    else:
                        cells.append("[dim]—[/]")

                table.add_row(f"[{pstyle}]{name}[/]", thesis_short, *cells)

            console.print(table)
            console.print()

        # Résumé final
        console.print(Rule("[bold]🏁 Fin du Débat[/]", style="dim"))
        console.print()
        status_style = "green" if status == "completed" else "red"
        console.print(f"  Statut       : [{status_style} bold]{status}[/]")
        console.print(f"  Rounds       : {rounds}")
        console.print(f"  Tokens total : {total_tokens:,}")
        console.print(f"  Durée        : {elapsed:.1f}s")
        console.print()

    def _on_error(self, e: dict):
        msg = e.get("error", e.get("reason", "?"))
        console.print(f"\n  [red bold]❌ ERREUR : {msg}[/]\n")

    def _on_user_question(self, e: dict):
        pid = e.get("participant_id", "?")
        question = e.get("question", "?")
        info = self.participants.get(pid, {})
        name = info.get("display_name", pid)
        console.print(
            f"\n  [yellow bold]❓ {name} vous pose une question :[/]\n"
            f"     {question}\n"
        )

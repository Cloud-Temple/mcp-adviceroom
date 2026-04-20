#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AdviceRoom CLI — Lance un débat multi-LLM en streaming.

Crée un débat via l'API REST, puis affiche les événements NDJSON
en temps réel avec couleurs et formatage.

Usage :
    python scripts/adviceroom_cli.py "Quelle est la meilleure approche pour le RAG ?"
    python scripts/adviceroom_cli.py --models gpt-oss-120b,gpt-52 "Ma question"
    python scripts/adviceroom_cli.py --url http://localhost:8000 "Ma question"
    python scripts/adviceroom_cli.py --list-models

Variables d'environnement :
    ADVICEROOM_URL — URL du backend (défaut: http://localhost:8000)
"""

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Dict, List, Optional


# ============================================================
# Configuration
# ============================================================

DEFAULT_URL = os.environ.get("ADVICEROOM_URL", "http://localhost:8000")
API_PREFIX = "/api/v1"

# Couleurs ANSI (fonctionne sans dépendance externe)
COLORS = {
    "reset":    "\033[0m",
    "bold":     "\033[1m",
    "dim":      "\033[2m",
    "red":      "\033[91m",
    "green":    "\033[92m",
    "yellow":   "\033[93m",
    "blue":     "\033[94m",
    "magenta":  "\033[95m",
    "cyan":     "\033[96m",
    "white":    "\033[97m",
    "gray":     "\033[90m",
}

# Couleurs par provider (pour distinguer les participants)
PROVIDER_COLORS = {
    "llmaas":    "cyan",
    "openai":    "green",
    "anthropic": "yellow",
    "google":    "blue",
}

# Icônes par type d'événement
EVENT_ICONS = {
    "debate_start":  "🏛️ ",
    "phase":         "📋",
    "turn_start":    "🎤",
    "chunk":         "",
    "turn_end":      "✓ ",
    "stability":     "📊",
    "verdict":       "⚖️ ",
    "debate_end":    "🏁",
    "error":         "❌",
    "user_question": "❓",
}


# ============================================================
# Helpers d'affichage
# ============================================================

def c(color: str, text: str) -> str:
    """Colore un texte."""
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def print_header(title: str):
    """Affiche un header encadré."""
    width = 60
    print(f"\n{c('bold', '╔' + '═' * width + '╗')}")
    print(f"{c('bold', '║')} {c('cyan', title.center(width - 1))}{c('bold', '║')}")
    print(f"{c('bold', '╚' + '═' * width + '╝')}")


def print_separator(label: str = ""):
    """Affiche un séparateur léger."""
    if label:
        print(f"\n{c('dim', '─── ')} {c('bold', label)} {c('dim', '─' * 40)}")
    else:
        print(c('dim', '─' * 60))


def format_duration(ms: int) -> str:
    """Formate une durée en ms/s."""
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def get_participant_color(provider: str) -> str:
    """Retourne la couleur ANSI pour un provider."""
    return PROVIDER_COLORS.get(provider, "white")


# ============================================================
# API Client (httpx async)
# ============================================================

async def get_models(base_url: str) -> dict:
    """Récupère la liste des modèles disponibles."""
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{base_url}{API_PREFIX}/providers")
        resp.raise_for_status()
        return resp.json()


async def create_debate(
    base_url: str,
    question: str,
    models: List[str],
    model_registry: dict,
) -> dict:
    """Crée un débat via POST /api/v1/debates."""
    import httpx

    # Construire les participants à partir des model IDs
    participants = []
    for model_id in models:
        model_info = model_registry.get(model_id)
        if model_info:
            participants.append({
                "provider": model_info["provider"],
                "model": model_id,
            })
        else:
            print(c("red", f"  ❌ Modèle inconnu : {model_id}"))
            sys.exit(1)

    payload = {
        "question": question,
        "participants": participants,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}{API_PREFIX}/debates",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def stream_debate(base_url: str, stream_url: str, participants: dict):
    """
    Streame le débat NDJSON et affiche les événements en temps réel.

    Args:
        base_url: URL du backend
        stream_url: URL relative du stream (/api/v1/debates/{id}/stream)
        participants: Dict {participant_id: {provider, display_name, ...}}
    """
    import httpx

    url = f"{base_url}{stream_url}"
    current_speaker = None
    current_text = ""
    debate_start_time = time.time()
    total_tokens = 0

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream("GET", url, headers={"Accept": "application/x-ndjson"}) as resp:
            resp.raise_for_status()
            buffer = ""

            async for raw_chunk in resp.aiter_text():
                buffer += raw_chunk
                lines = buffer.split("\n")
                buffer = lines.pop()  # Garder la dernière ligne incomplète

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Dispatcher selon le type d'événement
                    etype = event.get("type", "unknown")

                    if etype == "debate_start":
                        _show_debate_start(event)

                    elif etype == "phase":
                        _show_phase(event)

                    elif etype == "turn_start":
                        current_speaker = event.get("participant_id", "?")
                        current_text = ""
                        info = participants.get(current_speaker, {})
                        pcolor = get_participant_color(info.get("provider", ""))
                        name = info.get("display_name", current_speaker)
                        persona = info.get("persona_name", "")
                        label = f"{name}"
                        if persona:
                            label += f" ({persona})"
                        print(f"\n  {EVENT_ICONS['turn_start']} {c(pcolor, c('bold', label))}")

                    elif etype == "chunk":
                        # Affichage streaming du texte (chunk par chunk)
                        delta = event.get("content", "")
                        if delta:
                            current_text += delta
                            sys.stdout.write(delta)
                            sys.stdout.flush()

                    elif etype == "turn_end":
                        if current_text:
                            print()  # Fin de ligne après le streaming
                        tokens = event.get("tokens_used", 0)
                        duration = event.get("duration_ms", 0)
                        total_tokens += tokens
                        turn_icon = EVENT_ICONS["turn_end"]
                        dur_str = format_duration(duration)
                        print(c("dim", f"  {turn_icon} {tokens} tokens, {dur_str}"))
                        current_speaker = None

                    elif etype == "stability":
                        _show_stability(event)

                    elif etype == "verdict":
                        _show_verdict(event)

                    elif etype == "debate_end":
                        elapsed = time.time() - debate_start_time
                        _show_debate_end(event, elapsed, total_tokens)

                    elif etype == "error":
                        err_msg = event.get("error", "?")
                        print(f"\n  {c('red', f'❌ ERREUR : {err_msg}')}")

                    elif etype == "user_question":
                        q_msg = event.get("question", "?")
                        print(f"\n  {c('yellow', f'❓ Question pour vous : {q_msg}')}")

                    else:
                        # Événement inconnu, afficher en JSON
                        print(f"\n  {c('dim', f'[{etype}] {json.dumps(event, ensure_ascii=False)[:100]}')}")


def _show_debate_start(event: dict):
    """Affiche le début du débat."""
    question = event.get("question", "?")
    participants = event.get("participants", [])
    print(f"\n  {EVENT_ICONS['debate_start']} {c('bold', 'Débat lancé')}")
    print(f"  {c('dim', '   Question :')} {c('white', question)}")
    print(f"  {c('dim', '   Participants :')}")
    for p in participants:
        pcolor = get_participant_color(p.get("provider", ""))
        name = p.get("display_name", "?")
        persona = p.get("persona_name", "")
        line = f"     • {c(pcolor, name)}"
        if persona:
            line += f" {c('dim', f'— {persona}')}"
        print(line)


def _show_phase(event: dict):
    """Affiche un changement de phase."""
    phase = event.get("phase", "?").upper()
    phase_labels = {
        "OPENING": "📖 OUVERTURE — Positions initiales (parallèle)",
        "DEBATE": "💬 DÉBAT — Discussion (round-robin)",
        "VERDICT": "⚖️  VERDICT — Synthèse finale",
    }
    label = phase_labels.get(phase, f"Phase : {phase}")
    print_separator(label)


def _show_stability(event: dict):
    """Affiche le score de stabilité."""
    score = event.get("score", 0)
    can_stop = event.get("can_stop", False)
    round_num = event.get("round", "?")

    # Barre de stabilité visuelle
    bar_len = 20
    filled = int(score * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    color = "green" if score >= 0.85 else "yellow" if score >= 0.5 else "red"
    status = "✓ STABLE" if can_stop else "→ CONTINUE"

    print(f"\n  {EVENT_ICONS['stability']} Round {round_num} — "
          f"Stabilité : {c(color, f'{bar} {score:.0%}')} "
          f"{c('bold', status)}")


def _show_verdict(event: dict):
    """Affiche le verdict structuré."""
    vtype = event.get("verdict_type", "?")
    confidence = event.get("confidence", 0)
    summary = event.get("summary", "")
    agreement = event.get("agreement_points", [])
    recommendation = event.get("recommendation", "")

    type_colors = {
        "consensus": "green",
        "consensus_partiel": "yellow",
        "dissensus": "red",
    }
    vcolor = type_colors.get(vtype, "white")

    print_separator(f"⚖️  VERDICT — {vtype.upper()}")
    print(f"\n  {c('bold', 'Type :')} {c(vcolor, c('bold', vtype.upper()))}")
    print(f"  {c('bold', 'Confiance :')} {confidence}%")

    if summary:
        print(f"\n  {c('bold', 'Synthèse :')}")
        # Afficher le résumé en wrappant les lignes longues
        for line in summary.split("\n"):
            print(f"    {line}")

    if agreement:
        label = "Points d'accord :"
        print(f"\n  {c('bold', label)}")
        for pt in agreement:
            print(f"    {c('green', '✓')} {pt}")

    if recommendation:
        print(f"\n  {c('bold', 'Recommandation :')}")
        print(f"    {c('cyan', recommendation)}")


def _show_debate_end(event: dict, elapsed: float, total_tokens: int):
    """Affiche la fin du débat."""
    status = event.get("status", "?")
    rounds = event.get("rounds", 0)

    print_separator("FIN DU DÉBAT")
    print(f"\n  {EVENT_ICONS['debate_end']} {c('bold', 'Débat terminé')}")
    print(f"     Statut      : {c('green' if status == 'completed' else 'red', status)}")
    print(f"     Rounds      : {rounds}")
    print(f"     Tokens total: {total_tokens}")
    print(f"     Durée       : {elapsed:.1f}s")
    print()


# ============================================================
# Commande list-models
# ============================================================

async def cmd_list_models(base_url: str):
    """Affiche les modèles LLM disponibles."""
    try:
        data = await get_models(base_url)
    except Exception as e:
        print(c("red", f"❌ Impossible de contacter {base_url} : {e}"))
        sys.exit(1)

    categories = data.get("categories", {})
    default_cat = data.get("default_category", "?")

    print_header("Modèles LLM Disponibles")
    print(f"  {c('dim', 'Catégorie par défaut :')} {c('bold', default_cat)}")

    total = 0
    for cat_id, cat_info in categories.items():
        models = cat_info.get("models", [])
        icon = cat_info.get("icon", "")
        name = cat_info.get("display_name", cat_id)
        print(f"\n  {icon} {c('bold', name)} ({len(models)} modèles)")

        for m in models:
            mid = m["id"]
            dname = m["display_name"]
            default = " ⭐" if m.get("default") else ""
            caps = ", ".join(m.get("capabilities", []))
            pcolor = get_participant_color(m.get("provider", ""))
            print(f"     {c(pcolor, f'{mid:20s}')} {dname:20s} [{caps}]{default}")
            total += 1

    print(f"\n  {c('dim', f'Total : {total} modèles')}\n")


# ============================================================
# Commande debate (principale)
# ============================================================

async def cmd_debate(base_url: str, question: str, model_ids: List[str]):
    """Lance un débat et streame les événements."""

    # 1. Récupérer le registre des modèles
    print(f"\n  {c('dim', f'Connexion à {base_url}...')}")
    try:
        data = await get_models(base_url)
    except Exception as e:
        print(c("red", f"❌ Impossible de contacter {base_url} : {e}"))
        sys.exit(1)

    # Construire le registre plat {model_id: {provider, display_name, ...}}
    model_registry: Dict[str, dict] = {}
    for cat_id, cat_info in data.get("categories", {}).items():
        for m in cat_info.get("models", []):
            model_registry[m["id"]] = m

    # Si pas de modèles spécifiés, prendre les défauts de 2 premières catégories
    if not model_ids:
        defaults = []
        for cat_id, cat_info in data.get("categories", {}).items():
            for m in cat_info.get("models", []):
                if m.get("default"):
                    defaults.append(m["id"])
        model_ids = defaults[:3] if len(defaults) >= 3 else defaults[:2]

    if len(model_ids) < 2:
        print(c("red", "❌ Il faut au moins 2 modèles pour un débat."))
        print(c("dim", "   Utilisez --list-models pour voir les modèles disponibles."))
        sys.exit(1)

    # 2. Afficher le plan
    print_header("AdviceRoom — Débat Multi-LLM")
    print(f"  {c('bold', 'Question :')} {question}")
    print(f"  {c('bold', 'Participants :')}")
    for mid in model_ids:
        info = model_registry.get(mid, {})
        pcolor = get_participant_color(info.get("provider", ""))
        print(f"     • {c(pcolor, info.get('display_name', mid))} ({mid})")
    print()

    # 3. Créer le débat
    print(f"  {c('dim', 'Création du débat...')}")
    try:
        result = await create_debate(base_url, question, model_ids, model_registry)
    except Exception as e:
        print(c("red", f"❌ Erreur création : {e}"))
        sys.exit(1)

    debate_id = result["debate_id"]
    stream_url = result["stream_url"]
    print(f"  {c('green', f'✓ Débat créé : {debate_id}')}")
    print(f"  {c('dim', f'  Stream : {stream_url}')}")

    # 4. Récupérer les infos des participants pour l'affichage
    # On réutilise le registre pour mapper participant_id → couleur/nom
    # (le backend utilise model_id comme participant_id)
    participants_map = {}
    for mid in model_ids:
        info = model_registry.get(mid, {})
        participants_map[mid] = {
            "display_name": info.get("display_name", mid),
            "provider": info.get("provider", ""),
            "persona_name": "",  # Sera rempli par les événements
        }

    # 5. Streamer les événements
    try:
        await stream_debate(base_url, stream_url, participants_map)
    except KeyboardInterrupt:
        msg = "⚠ Débat interrompu par l'utilisateur"
        print(f"\n\n  {c('yellow', msg)}\n")
    except Exception as e:
        print(c("red", f"\n❌ Erreur stream : {e}"))


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="🏛️  AdviceRoom CLI — Débats multi-LLM en streaming",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  %(prog)s "Quelle architecture pour un SaaS multi-tenant ?"
  %(prog)s --models gpt-oss-120b,gpt-52 "Ma question"
  %(prog)s --models gpt-oss-120b,claude-opus-46,gemini-31-pro "Question complexe"
  %(prog)s --list-models
  %(prog)s --url http://mon-serveur:8000 "Ma question"
""",
    )

    parser.add_argument(
        "question",
        nargs="?",
        help="La question à débattre",
    )
    parser.add_argument(
        "--models", "-m",
        help="IDs des modèles séparés par des virgules (défaut: 2-3 modèles par défaut)",
    )
    parser.add_argument(
        "--url", "-u",
        default=DEFAULT_URL,
        help=f"URL du backend AdviceRoom (défaut: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--list-models", "-l",
        action="store_true",
        help="Lister les modèles LLM disponibles",
    )

    args = parser.parse_args()

    # Commande list-models
    if args.list_models:
        asyncio.run(cmd_list_models(args.url))
        return

    # Commande debate (par défaut)
    if not args.question:
        parser.print_help()
        sys.exit(1)

    model_ids = []
    if args.models:
        model_ids = [m.strip() for m in args.models.split(",")]

    asyncio.run(cmd_debate(args.url, args.question, model_ids))


if __name__ == "__main__":
    main()

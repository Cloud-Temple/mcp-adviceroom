# -*- coding: utf-8 -*-
"""
Shell interactif AdviceRoom — Couche 3 : interface interactive avec autocomplétion.

Commandes alignées 1:1 avec /admin/api/*.
Utilise prompt_toolkit pour l'autocomplétion et Rich pour l'affichage.
"""

import asyncio
from pathlib import Path

from .client import AdminClient
from .display import (
    console, show_error, show_success, show_warning, show_json,
    show_health_result, show_whoami_result, show_models_result,
    show_token_list_result, show_token_create_result, show_token_revoke_result,
    show_debates_list_result, show_debate_detail_result, show_debate_delete_result,
    show_logs_result, show_llm_activity_result,
    DebateRenderer,
)


# =============================================================================
# Commandes disponibles (pour autocomplétion + help)
# =============================================================================

SHELL_COMMANDS = {
    "help":         "Afficher l'aide",
    "health":       "État du serveur (LLM, S3, MCP Tools)",
    "whoami":       "Identité du token courant",
    "models":       "Liste des modèles LLM",
    "logs":         "Activité HTTP récente",
    "llm-activity": "Activité LLM détaillée",
    "token":        "Tokens: token list | token create NOM | token revoke HASH",
    "debate":       "Débats: debate list | debate get ID | debate delete ID | debate start \"question\"",
    "quit":         "Quitter le shell",
    "exit":         "Quitter le shell",
}


# =============================================================================
# Handlers
# =============================================================================

async def cmd_health(client: AdminClient, args: str = "", json_output: bool = False):
    result = await client.health()
    if json_output:
        show_json(result)
    elif result.get("status") == "ok":
        show_health_result(result)
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_whoami(client: AdminClient, args: str = "", json_output: bool = False):
    result = await client.whoami()
    if json_output:
        show_json(result)
    elif result.get("status") == "ok":
        show_whoami_result(result, url=client.base_url)
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_models(client: AdminClient, args: str = "", json_output: bool = False):
    result = await client.list_models()
    if json_output:
        show_json(result)
    elif result.get("status") == "ok":
        show_models_result(result)
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_logs(client: AdminClient, args: str = "", json_output: bool = False):
    result = await client.logs()
    if json_output:
        show_json(result)
    elif result.get("status") == "ok":
        show_logs_result(result)
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_llm_activity(client: AdminClient, args: str = "", json_output: bool = False):
    result = await client.llm_activity()
    if json_output:
        show_json(result)
    elif result.get("status") == "ok":
        show_llm_activity_result(result)
    else:
        show_error(result.get("message", "Erreur"))


# =============================================================================
# Handler token
# =============================================================================

async def cmd_token(client: AdminClient, args: str = "", json_output: bool = False):
    """Gestion des tokens : list | create NOM | revoke HASH."""
    parts = args.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    sub_args = parts[1] if len(parts) > 1 else ""

    if sub == "list":
        result = await client.list_tokens()
        if json_output:
            show_json(result)
        elif result.get("status") == "ok":
            show_token_list_result(result)
        else:
            show_error(result.get("message", "Erreur"))

    elif sub == "create":
        # Parser: token create NOM [--email EMAIL] [--permissions PERMS]
        create_parts = sub_args.split()
        if not create_parts:
            show_warning("Usage: token create NOM [--email EMAIL] [--permissions read,write]")
            return
        name = create_parts[0]
        email = ""
        permissions = "read"
        i = 1
        while i < len(create_parts):
            if create_parts[i] == "--email" and i + 1 < len(create_parts):
                email = create_parts[i + 1]
                i += 2
            elif create_parts[i] == "--permissions" and i + 1 < len(create_parts):
                permissions = create_parts[i + 1]
                i += 2
            else:
                i += 1

        perms = [p.strip() for p in permissions.split(",")]
        result = await client.create_token(name, perms, email=email)
        if json_output:
            show_json(result)
        elif result.get("status") in ("ok", "created"):
            show_token_create_result(result)
        else:
            show_error(result.get("message", "Erreur"))

    elif sub == "revoke":
        if not sub_args.strip():
            show_warning("Usage: token revoke HASH_PREFIX")
            return
        result = await client.revoke_token(sub_args.strip())
        if json_output:
            show_json(result)
        elif result.get("status") == "ok":
            show_token_revoke_result(result)
        else:
            show_error(result.get("message", "Erreur"))

    else:
        show_warning("Usage: token <list|create|revoke> [args]")


# =============================================================================
# Handler debate
# =============================================================================

async def cmd_debate(client: AdminClient, args: str = "", json_output: bool = False):
    """Gestion des débats : list | get ID | delete ID | start "question" [-m models]."""
    parts = args.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    sub_args = parts[1] if len(parts) > 1 else ""

    if sub == "list":
        result = await client.list_debates()
        if json_output:
            show_json(result)
        elif result.get("status") == "ok":
            show_debates_list_result(result)
        else:
            show_error(result.get("message", "Erreur"))

    elif sub == "get":
        if not sub_args.strip():
            show_warning("Usage: debate get DEBATE_ID")
            return
        result = await client.get_debate(sub_args.strip())
        if json_output:
            show_json(result)
        elif result.get("status") == "ok":
            show_debate_detail_result(result)
        else:
            show_error(result.get("message", "Erreur"))

    elif sub == "delete":
        if not sub_args.strip():
            show_warning("Usage: debate delete DEBATE_ID")
            return
        result = await client.delete_debate(sub_args.strip())
        if json_output:
            show_json(result)
        elif result.get("status") == "ok":
            show_debate_delete_result(result)
        else:
            show_error(result.get("message", "Erreur"))

    elif sub == "start":
        await _debate_start_shell(client, sub_args)

    else:
        show_warning("Usage: debate <list|get|delete|start> [args]")


async def _debate_start_shell(client: AdminClient, args: str):
    """Lancer un débat depuis le shell interactif."""
    # Parser : debate start "question" [-m model1,model2] [--mode parallel] [-r 5]
    import shlex
    try:
        tokens = shlex.split(args)
    except ValueError:
        tokens = args.split()

    if not tokens:
        show_warning('Usage: debate start "Ma question" [-m models] [--mode standard|parallel|blitz] [-r rounds]')
        return

    question = tokens[0]
    model_ids_str = ""
    mode = None
    max_rounds = None
    i = 1
    while i < len(tokens):
        if tokens[i] in ("-m", "--models") and i + 1 < len(tokens):
            model_ids_str = tokens[i + 1]
            i += 2
        elif tokens[i] == "--mode" and i + 1 < len(tokens):
            mode = tokens[i + 1]
            i += 2
        elif tokens[i] in ("-r", "--rounds") and i + 1 < len(tokens):
            try:
                max_rounds = int(tokens[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    # Récupérer les modèles disponibles
    providers_data = await client.get_providers()
    if providers_data.get("status") == "error":
        show_error(providers_data.get("message", "Impossible de récupérer les modèles"))
        return

    model_registry = {}
    for cat_info in providers_data.get("categories", {}).values():
        for m in cat_info.get("models", []):
            model_registry[m["id"]] = m

    if model_ids_str:
        model_ids = [m.strip() for m in model_ids_str.split(",")]
    else:
        defaults = [
            m["id"]
            for cat in providers_data.get("categories", {}).values()
            for m in cat.get("models", [])
            if m.get("default")
        ]
        model_ids = defaults[:3] if len(defaults) >= 3 else defaults[:2]

    if len(model_ids) < 2:
        show_error("Il faut au moins 2 modèles. Utilisez 'models' pour voir les disponibles.")
        return

    participants = []
    for mid in model_ids:
        info = model_registry.get(mid)
        if not info:
            show_error(f"Modèle inconnu : {mid}")
            return
        participants.append({"provider": info["provider"], "model": mid})

    # Créer et streamer
    console.print(f"  [dim]Création du débat...[/]")
    result = await client.create_debate(question, participants, mode=mode, max_rounds=max_rounds)
    if result.get("status") == "error":
        show_error(result.get("message", "Erreur"))
        return

    debate_id = result.get("debate_id", "?")
    stream_url = result.get("stream_url", "")
    console.print(f"  [green]✓ Débat créé : {debate_id}[/]")

    renderer = DebateRenderer()
    try:
        async for event in client.stream_debate(stream_url):
            renderer.handle(event)
    except Exception as e:
        show_error(f"Erreur stream : {e}")


# =============================================================================
# Help
# =============================================================================

def cmd_help():
    """Affiche l'aide du shell."""
    from rich.table import Table

    table = Table(title="🐚 AdviceRoom Shell — Commandes", show_header=True)
    table.add_column("Commande", style="cyan bold", min_width=20)
    table.add_column("Description", style="white")

    for cmd, desc in SHELL_COMMANDS.items():
        table.add_row(cmd, desc)

    table.add_row("", "")
    table.add_row("[dim]--json[/dim]", "[dim]Ajouter après une commande pour la sortie JSON[/dim]")

    console.print(table)


# =============================================================================
# Boucle principale du shell
# =============================================================================

async def run_shell(url: str, token: str):
    """Lance le shell interactif AdviceRoom."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.history import FileHistory
    except ImportError:
        console.print("[yellow]⚠️  prompt_toolkit non installé. Shell basique activé.[/]")
        console.print("[dim]   pip install prompt_toolkit[/]")
        await _run_basic_shell(url, token)
        return

    client = AdminClient(url, token)

    # Autocomplétion
    all_words = list(SHELL_COMMANDS.keys()) + [
        "--json", "list", "create", "get", "delete", "revoke", "start",
    ]
    completer = WordCompleter(all_words, ignore_case=True)

    # Historique persistant
    history_path = Path.home() / ".adviceroom_shell_history"
    session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=completer,
    )

    console.print(f"\n[bold cyan]🏛️  AdviceRoom Shell[/bold cyan] — connecté à [green]{url}[/green]")
    console.print("[dim]Tapez 'help' pour l'aide, 'quit' pour quitter.[/dim]\n")

    while True:
        try:
            user_input = await session.prompt_async("adviceroom> ")

            if not user_input.strip():
                continue

            # Parser la commande
            parts = user_input.strip().split(None, 1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            # Détecter --json
            json_output = "--json" in args
            if json_output:
                args = args.replace("--json", "").strip()

            # Dispatch
            if command in ("quit", "exit"):
                console.print("[dim]Au revoir 👋[/dim]")
                break
            elif command == "help":
                cmd_help()
            elif command == "health":
                await cmd_health(client, args, json_output)
            elif command == "whoami":
                await cmd_whoami(client, args, json_output)
            elif command == "models":
                await cmd_models(client, args, json_output)
            elif command == "logs":
                await cmd_logs(client, args, json_output)
            elif command in ("llm-activity", "llm_activity"):
                await cmd_llm_activity(client, args, json_output)
            elif command == "token":
                await cmd_token(client, args, json_output)
            elif command == "debate":
                await cmd_debate(client, args, json_output)
            else:
                show_warning(f"Commande inconnue: '{command}'. Tapez 'help'.")

        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C — tapez 'quit' pour quitter[/dim]")
        except EOFError:
            console.print("[dim]Au revoir 👋[/dim]")
            break
        except Exception as e:
            show_error(f"Erreur: {e}")


async def _run_basic_shell(url: str, token: str):
    """Shell basique sans prompt_toolkit (fallback)."""
    client = AdminClient(url, token)

    console.print(f"\n[bold cyan]🏛️  AdviceRoom Shell (basique)[/bold cyan] — {url}")
    console.print("[dim]Tapez 'help' pour l'aide, 'quit' pour quitter.[/dim]\n")

    while True:
        try:
            user_input = input("adviceroom> ")
            if not user_input.strip():
                continue

            parts = user_input.strip().split(None, 1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            json_output = "--json" in args
            if json_output:
                args = args.replace("--json", "").strip()

            if command in ("quit", "exit"):
                console.print("[dim]Au revoir 👋[/dim]")
                break
            elif command == "help":
                cmd_help()
            elif command == "health":
                await cmd_health(client, args, json_output)
            elif command == "whoami":
                await cmd_whoami(client, args, json_output)
            elif command == "models":
                await cmd_models(client, args, json_output)
            elif command == "logs":
                await cmd_logs(client, args, json_output)
            elif command in ("llm-activity", "llm_activity"):
                await cmd_llm_activity(client, args, json_output)
            elif command == "token":
                await cmd_token(client, args, json_output)
            elif command == "debate":
                await cmd_debate(client, args, json_output)
            else:
                show_warning(f"Commande inconnue: '{command}'. Tapez 'help'.")

        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C — tapez 'quit' pour quitter[/dim]")
        except EOFError:
            console.print("[dim]Au revoir 👋[/dim]")
            break
        except Exception as e:
            show_error(f"Erreur: {e}")

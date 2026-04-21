# -*- coding: utf-8 -*-
"""
CLI Click — Commandes scriptables AdviceRoom.

Aligné 1:1 avec les endpoints /admin/api/*.
Chaque commande appelle AdminClient puis affiche via display.py.

Usage :
    python scripts/adviceroom_cli.py health
    python scripts/adviceroom_cli.py models
    python scripts/adviceroom_cli.py debate list
    python scripts/adviceroom_cli.py debate start "Ma question" -m gpt-52,claude-opus-46
    python scripts/adviceroom_cli.py shell
"""

import asyncio
import click
from . import BASE_URL, TOKEN
from .client import AdminClient
from .display import (
    console, show_error, show_json,
    show_health_result, show_whoami_result,
    show_models_result,
    show_token_list_result, show_token_create_result, show_token_revoke_result,
    show_debates_list_result, show_debate_detail_result, show_debate_delete_result,
    show_logs_result, show_llm_activity_result,
    DebateRenderer,
)


# =============================================================================
# Groupe racine
# =============================================================================

@click.group()
@click.option(
    "--url", "-u",
    envvar=["ADVICEROOM_URL"],
    default=BASE_URL,
    help="URL du backend AdviceRoom",
)
@click.option(
    "--token", "-t",
    envvar=["ADVICEROOM_TOKEN"],
    default=TOKEN,
    help="Token admin Bearer",
)
@click.pass_context
def cli(ctx, url, token):
    """🏛️  AdviceRoom CLI — Administration et débats multi-LLM."""
    ctx.ensure_object(dict)
    ctx.obj["url"] = url
    ctx.obj["token"] = token


# =============================================================================
# Commandes système
# =============================================================================

@cli.command("health")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def health_cmd(ctx, output_json):
    """❤️  État du serveur (LLM Router, S3, MCP Tools)."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.health()
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_health_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@cli.command("whoami")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def whoami_cmd(ctx, output_json):
    """👤 Identité du token courant."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.whoami()
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_whoami_result(result, url=ctx.obj["url"])
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@cli.command("models")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def models_cmd(ctx, output_json):
    """🤖 Liste des modèles LLM disponibles."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.list_models()
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_models_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@cli.command("logs")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def logs_cmd(ctx, output_json):
    """📋 Activité HTTP récente (ring buffer)."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.logs()
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_logs_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@cli.command("llm-activity")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def llm_activity_cmd(ctx, output_json):
    """🤖 Activité LLM détaillée (tours, verdicts, erreurs)."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.llm_activity()
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_llm_activity_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


# =============================================================================
# Commandes token (gestion des tokens d'accès)
# =============================================================================

@cli.group("token")
def token_group():
    """🔑 Gestion des tokens d'accès (admin)."""
    pass


@token_group.command("list")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def token_list_cmd(ctx, output_json):
    """Lister les tokens existants."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.list_tokens()
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_token_list_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@token_group.command("create")
@click.argument("client_name")
@click.option("--permissions", "-p", default="read", help="Permissions (ex: read,write,admin)")
@click.option("--email", "-e", default="", help="Email du propriétaire")
@click.option("--expires", "-d", default=90, type=int, help="Expiration en jours (0 = jamais)")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def token_create_cmd(ctx, client_name, permissions, email, expires, output_json):
    """Créer un nouveau token."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        perms = [p.strip() for p in permissions.split(",")]
        result = await client.create_token(
            client_name, perms, email=email, expires_in_days=expires,
        )
        if output_json:
            show_json(result)
        elif result.get("status") in ("ok", "created"):
            show_token_create_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@token_group.command("revoke")
@click.argument("hash_prefix")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def token_revoke_cmd(ctx, hash_prefix, output_json):
    """Révoquer un token par préfixe de hash."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.revoke_token(hash_prefix)
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_token_revoke_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


# =============================================================================
# Commandes debate (gestion des débats)
# =============================================================================

@cli.group("debate")
def debate_group():
    """🏛️ Gestion des débats multi-LLM."""
    pass


@debate_group.command("list")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def debate_list_cmd(ctx, output_json):
    """Lister les débats (mémoire + S3)."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.list_debates()
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_debates_list_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@debate_group.command("get")
@click.argument("debate_id")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def debate_get_cmd(ctx, debate_id, output_json):
    """Afficher les détails d'un débat."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.get_debate(debate_id)
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_debate_detail_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@debate_group.command("delete")
@click.argument("debate_id")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def debate_delete_cmd(ctx, debate_id, output_json):
    """Supprimer un débat (mémoire + S3)."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.delete_debate(debate_id)
        if output_json:
            show_json(result)
        elif result.get("status") == "ok":
            show_debate_delete_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())


@debate_group.command("start")
@click.argument("question")
@click.option("--models", "-m", default="", help="IDs des modèles séparés par des virgules")
@click.option("--rounds", "-r", default=5, type=int, help="Nombre max de rounds (défaut: 5)")
@click.pass_context
def debate_start_cmd(ctx, question, models, rounds):
    """Lancer un débat avec streaming temps réel."""
    async def _run():
        client = AdminClient(ctx.obj["url"], ctx.obj["token"])

        # 1. Récupérer les modèles disponibles
        console.print(f"\n  [dim]Connexion à {ctx.obj['url']}...[/]")
        providers_data = await client.get_providers()
        if providers_data.get("status") == "error":
            show_error(providers_data.get("message", "Impossible de récupérer les modèles"))
            return

        # Construire le registre plat {model_id: {...}}
        model_registry = {}
        for cat_info in providers_data.get("categories", {}).values():
            for m in cat_info.get("models", []):
                model_registry[m["id"]] = m

        # Résoudre les modèles
        if models:
            model_ids = [m.strip() for m in models.split(",")]
        else:
            # Modèles par défaut
            defaults = [
                m["id"]
                for cat in providers_data.get("categories", {}).values()
                for m in cat.get("models", [])
                if m.get("default")
            ]
            model_ids = defaults[:3] if len(defaults) >= 3 else defaults[:2]

        if len(model_ids) < 2:
            show_error(
                "Il faut au moins 2 modèles. "
                "Utilisez 'adviceroom models' pour voir les modèles disponibles."
            )
            return

        # Vérifier que tous les modèles existent
        participants = []
        for mid in model_ids:
            info = model_registry.get(mid)
            if not info:
                show_error(f"Modèle inconnu : {mid}")
                return
            participants.append({
                "provider": info["provider"],
                "model": mid,
            })

        # 2. Header
        from .display import _style_for
        console.print()
        from rich.panel import Panel
        console.print(Panel(
            "[bold cyan]🏛️  AdviceRoom — Débat Multi-LLM[/]",
            style="cyan", padding=(0, 2),
        ))
        console.print(f"  [bold]Question :[/] {question}")
        console.print(f"  [bold]Participants :[/]")
        for mid in model_ids:
            info = model_registry.get(mid, {})
            style, label = _style_for(info.get("provider", ""))
            console.print(
                f"     [{style}]• {info.get('display_name', mid)}[/] "
                f"[dim]({mid}) \\[{label}][/]"
            )
        console.print()

        # 3. Créer le débat
        console.print("  [dim]Création du débat...[/]")
        result = await client.create_debate(question, participants)
        if result.get("status") == "error":
            show_error(result.get("message", "Erreur création"))
            return

        debate_id = result.get("debate_id", "?")
        stream_url = result.get("stream_url", "")
        console.print(f"  [green]✓ Débat créé : {debate_id}[/]")
        console.print(f"  [dim]  Stream : {stream_url}[/]")

        # 4. Streamer avec affichage enrichi
        renderer = DebateRenderer()
        try:
            async for event in client.stream_debate(stream_url):
                renderer.handle(event)
        except KeyboardInterrupt:
            console.print("\n\n  [yellow bold]⚠ Débat interrompu par l'utilisateur[/]\n")
        except Exception as e:
            show_error(f"Erreur stream : {e}")

    asyncio.run(_run())


# =============================================================================
# Shell interactif
# =============================================================================

@cli.command("shell")
@click.pass_context
def shell_cmd(ctx):
    """🐚 Lancer le shell interactif."""
    from .shell import run_shell
    asyncio.run(run_shell(ctx.obj["url"], ctx.obj["token"]))

"""
MCP Tools — Outils MCP exposés aux agents IA.

Les outils sont montés sous /mcp via FastMCP (Streamable HTTP).
Ils appellent directement les services internes (DebateOrchestrator,
LLMRouter) — pas d'API REST intermédiaire.

Outils exposés :
- debate_create     (write)  → Créer et lancer un débat
- debate_status     (read)   → Statut d'un débat
- debate_list       (read)   → Lister les débats
- provider_list     (read)   → Lister les LLMs disponibles
- system_health     (—)      → État de santé du service
- system_about      (—)      → Informations sur le service

Ref: DESIGN/architecture.md §4.2.5
"""
import logging
import platform
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field
from mcp.server.fastmcp import FastMCP

from ..config.settings import get_settings
from ..services.llm.router import get_llm_router

logger = logging.getLogger(__name__)

__all__ = ["mcp", "setup_mcp"]


# ============================================================
# Instance FastMCP
# ============================================================

settings = get_settings()

mcp = FastMCP(
    name="AdviceRoom",
    instructions=(
        "AdviceRoom orchestre des débats structurés entre LLMs hétérogènes. "
        "Utilisez debate_create pour lancer un débat, debate_status pour suivre "
        "son avancement, et provider_list pour voir les LLMs disponibles."
    ),
)


# ============================================================
# Référence au store des débats (partagé avec le router REST)
# ============================================================

def _get_debate_store():
    """Accède au store en mémoire des débats (partagé avec routers/debates.py)."""
    from ..routers.debates import _active_debates
    return _active_debates


def _get_orchestrator():
    """Accède à l'orchestrateur (partagé avec routers/debates.py)."""
    from ..routers.debates import get_orchestrator
    return get_orchestrator()


# ============================================================
# Outils MCP — Débats
# ============================================================

@mcp.tool()
async def debate_create(
    question: Annotated[str, Field(description="La question à débattre")],
    participants: Annotated[
        List[Dict[str, str]],
        Field(description="Liste de participants [{\"provider\": \"...\", \"model\": \"...\"}]"),
    ],
    persona_overrides: Annotated[
        Optional[Dict[str, str]],
        Field(description="Overrides de personas {model_id: persona_id}"),
    ] = None,
    max_rounds: Annotated[
        Optional[int],
        Field(description="Nombre max de rounds (défaut: 5)"),
    ] = None,
) -> dict:
    """
    Crée et lance un nouveau débat entre LLMs.

    Le débat est exécuté en tâche de fond. Utilisez debate_status
    pour suivre l'avancement et récupérer le verdict.

    Returns:
        ID du débat créé et informations de base.
    """
    import asyncio
    from ..routers.debates import (
        _active_debates,
        _debate_events,
        _run_debate_task,
    )

    orchestrator = _get_orchestrator()

    config_overrides = {}
    if max_rounds:
        config_overrides["max_rounds"] = max_rounds

    debate = orchestrator.create_debate(
        question=question,
        participant_specs=participants,
        persona_overrides=persona_overrides,
        config_overrides=config_overrides or None,
    )

    if len(debate.participants) < 2:
        return {
            "status": "error",
            "message": "Au moins 2 participants valides requis.",
        }

    # Stocker et lancer
    _active_debates[debate.id] = debate
    _debate_events[debate.id] = asyncio.Queue()
    asyncio.create_task(_run_debate_task(debate.id))

    return {
        "status": "ok",
        "debate_id": debate.id,
        "question": debate.question,
        "participants": [
            {"model": p.model_id, "persona": p.persona_name}
            for p in debate.participants
        ],
    }


@mcp.tool()
async def debate_status(
    debate_id: Annotated[str, Field(description="ID du débat")],
) -> dict:
    """
    Retourne le statut actuel d'un débat.

    Inclut le statut, la phase, les participants, le nombre de rounds,
    et le verdict s'il est terminé.

    Returns:
        État complet du débat.
    """
    debates = _get_debate_store()
    debate = debates.get(debate_id)

    if not debate:
        return {"status": "error", "message": f"Débat '{debate_id}' non trouvé"}

    result = {
        "status": "ok",
        "debate_id": debate.id,
        "question": debate.question,
        "debate_status": debate.status.value,
        "phase": debate.phase.value,
        "participants": [
            {
                "model": p.model_id,
                "persona": p.persona_name,
                "active": p.active,
            }
            for p in debate.participants
        ],
        "rounds": len(debate.rounds),
    }

    if debate.verdict:
        result["verdict"] = {
            "type": debate.verdict.type.value,
            "confidence": debate.verdict.confidence,
            "summary": debate.verdict.summary,
            "agreement_points": debate.verdict.agreement_points,
            "recommendation": debate.verdict.recommendation,
            "key_insights": debate.verdict.key_insights,
        }

    return result


@mcp.tool()
async def debate_list() -> dict:
    """
    Liste tous les débats connus.

    Retourne un résumé de chaque débat avec son statut et sa question.

    Returns:
        Liste des débats avec métadonnées de base.
    """
    debates = _get_debate_store()

    return {
        "status": "ok",
        "debates": [
            {
                "id": d.id,
                "question": d.question[:100],
                "status": d.status.value,
                "phase": d.phase.value,
                "participants": len(d.participants),
                "rounds": len(d.rounds),
            }
            for d in debates.values()
        ],
        "total": len(debates),
    }


# ============================================================
# Outils MCP — Providers
# ============================================================

@mcp.tool()
async def provider_list() -> dict:
    """
    Liste les LLMs disponibles, groupés par catégorie.

    Catégories : snc (SecNumCloud), openai, anthropic, google.
    Chaque modèle inclut ses capabilities (chat, tools, streaming).

    Returns:
        Modèles groupés par catégorie avec leurs métadonnées.
    """
    llm_router = get_llm_router()
    if not llm_router.loaded:
        return {"status": "error", "message": "LLM Router non initialisé"}

    return {
        "status": "ok",
        **llm_router.get_models_by_category(),
    }


# ============================================================
# Outils MCP — Système
# ============================================================

@mcp.tool()
async def system_health() -> dict:
    """
    Vérifie l'état de santé du service AdviceRoom.

    Teste la disponibilité des composants internes
    (LLM Router, Debate Engine).

    Returns:
        État global du système.
    """
    results = {}

    # LLM Router
    llm_router = get_llm_router()
    results["llm_router"] = {
        "status": "ok" if llm_router.loaded else "error",
        "models_active": sum(1 for m in llm_router.models.values() if m.active),
        "providers": list(llm_router._providers.keys()),
    }

    # Débats actifs
    debates = _get_debate_store()
    results["debates"] = {
        "status": "ok",
        "active": len(debates),
    }

    all_ok = all(r.get("status") == "ok" for r in results.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "service": "adviceroom",
        "version": settings.version,
        "services": results,
    }


@mcp.tool()
async def system_about() -> dict:
    """
    Informations sur le service AdviceRoom.

    Retourne la version, les outils MCP disponibles,
    et les informations système.

    Returns:
        Métadonnées du service.
    """
    version = settings.version

    tools = []
    for tool in mcp._tool_manager.list_tools():
        raw_desc = (tool.description or "").strip()
        first_line = raw_desc.split("\n")[0].strip()
        tools.append({"name": tool.name, "description": first_line})

    return {
        "status": "ok",
        "service": "adviceroom",
        "description": "Débats structurés entre LLMs hétérogènes",
        "version": version,
        "python_version": platform.python_version(),
        "tools_count": len(tools),
        "tools": tools,
    }


# ============================================================
# Setup MCP dans FastAPI
# ============================================================

def setup_mcp(fastapi_app):
    """
    Monte le serveur MCP dans l'application FastAPI existante.

    L'app MCP est montée sous /mcp (Streamable HTTP).
    Les agents IA se connectent à /mcp pour utiliser les outils.

    Args:
        fastapi_app: L'instance FastAPI principale.
    """
    mcp_app = mcp.streamable_http_app()
    fastapi_app.mount("/mcp", mcp_app)
    logger.info(f"✓ MCP monté sous /mcp ({len(mcp._tool_manager.list_tools())} outils)")

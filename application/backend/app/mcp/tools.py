"""
MCP Tools — Outils MCP exposés aux agents IA.

Les outils sont enregistrés via register_tools(mcp) appelé depuis main.py.
Ils appellent directement les services internes (DebateOrchestrator, LLMRouter).

Outils :
- debate_create     (write)  → Créer et lancer un débat
- debate_status     (read)   → Statut d'un débat
- debate_list       (read)   → Lister les débats
- provider_list     (read)   → Lister les LLMs disponibles
- system_health     (—)      → État de santé du service (public)
- system_about      (—)      → Informations sur le service (public)

Ref: DESIGN/architecture.md §4.2.5
Sécurité: DESIGN/SECURITY_AUDIT_V1.md V1-02, V1-03
"""
import logging
import platform
import re
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field

logger = logging.getLogger(__name__)

__all__ = ["register_tools"]

# V1-03 : validation debate_id (UUID v4)
_DEBATE_ID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
_MAX_QUESTION_LENGTH = 10_000
_MAX_ROUNDS = 20


# ============================================================
# Helpers (accès aux services partagés)
# ============================================================

def _get_debate_store():
    """Accède au store en mémoire des débats."""
    from ..routers.debates import _active_debates
    return _active_debates


def _get_orchestrator():
    """Accède à l'orchestrateur."""
    from ..routers.debates import get_orchestrator
    return get_orchestrator()


# ============================================================
# Enregistrement des outils MCP
# ============================================================

def register_tools(mcp):
    """
    Enregistre tous les outils MCP AdviceRoom sur l'instance FastMCP.

    Appelé depuis main.py après la création de l'instance FastMCP.
    """

    # ── debate_create (write) ────────────────────────────

    @mcp.tool()
    async def debate_create(
        question: Annotated[str, Field(description="La question à débattre")],
        participants: Annotated[
            List[Dict[str, str]],
            Field(description='Liste [{"provider": "...", "model": "..."}]'),
        ],
        persona_overrides: Annotated[
            Optional[Dict[str, str]],
            Field(description="Overrides de personas {model_id: persona_id}"),
        ] = None,
        mode: Annotated[
            Optional[str],
            Field(description="Mode de débat : standard | parallel | blitz (défaut: parallel)"),
        ] = None,
        max_rounds: Annotated[
            Optional[int],
            Field(description="Nombre max de rounds (défaut: selon mode, max: 20)"),
        ] = None,
    ) -> dict:
        """
        Crée et lance un nouveau débat entre LLMs.

        Requiert un token avec permission 'write' ou 'admin'.
        Le débat est exécuté en tâche de fond. Utilisez debate_status
        pour suivre l'avancement et récupérer le verdict.

        Modes disponibles (§3.1.1) :
        - standard : round-robin séquentiel, ~15-25 min, max interaction
        - parallel (défaut) : turns parallèles, ~3-8 min, bon compromis
        - blitz : opening + verdict direct, ~1-2 min, exploration rapide
        """
        # V1-02 : auth write requise
        from ..auth.context import check_write_permission
        write_err = check_write_permission()
        if write_err:
            return write_err

        # V1-03 : validation d'entrée
        if not question or len(question) > _MAX_QUESTION_LENGTH:
            return {"status": "error", "message": f"Question requise (max {_MAX_QUESTION_LENGTH} chars)"}
        if not participants or len(participants) < 2 or len(participants) > 5:
            return {"status": "error", "message": "2 à 5 participants requis"}
        if mode and mode not in ("standard", "parallel", "blitz"):
            return {"status": "error", "message": "Mode invalide. Valeurs: standard, parallel, blitz"}

        import asyncio
        from ..routers.debates import (
            _active_debates, _debate_events, _debate_events_history,
            _run_debate_task,
        )

        orchestrator = _get_orchestrator()

        # V1-03 : borner max_rounds
        config_overrides = {}
        if max_rounds:
            config_overrides["max_rounds"] = min(max(int(max_rounds), 1), _MAX_ROUNDS)

        debate = orchestrator.create_debate(
            question=question,
            participant_specs=participants,
            persona_overrides=persona_overrides,
            config_overrides=config_overrides or None,
            mode=mode,
        )

        if len(debate.participants) < 2:
            return {"status": "error", "message": "Au moins 2 participants valides requis."}

        _active_debates[debate.id] = debate
        _debate_events[debate.id] = asyncio.Queue()
        _debate_events_history[debate.id] = []
        asyncio.create_task(_run_debate_task(debate.id))

        return {
            "status": "ok",
            "debate_id": debate.id,
            "question": debate.question,
            "participants": [
                {"model": p.model_id, "persona": p.persona_name}
                for p in debate.participants
            ],
            "stream_url": f"/api/v1/debates/{debate.id}/stream",
        }

    # ── debate_status (read) ─────────────────────────────

    @mcp.tool()
    async def debate_status(
        debate_id: Annotated[str, Field(description="ID du débat (UUID)")],
    ) -> dict:
        """
        Retourne le statut actuel d'un débat.

        Requiert un token avec permission 'read' ou 'admin'.
        Inclut statut, phase, participants, rounds, et verdict si terminé.
        """
        # V1-02 : auth read requise
        from ..auth.context import check_access
        access_err = check_access(debate_id)
        if access_err:
            return access_err

        # V1-03 : validation debate_id
        if not _DEBATE_ID_RE.match(debate_id):
            return {"status": "error", "message": "debate_id invalide (UUID v4 attendu)"}

        debates = _get_debate_store()
        debate = debates.get(debate_id)

        if not debate:
            from ..services.storage.s3_store import get_debate_store
            store = get_debate_store()
            if store and store.available:
                data = store.load_debate(debate_id)
                if data:
                    return {"status": "ok", **data}
            return {"status": "error", "message": f"Débat '{debate_id}' non trouvé"}

        from ..services.storage.serializer import serialize_debate_full
        return {"status": "ok", **serialize_debate_full(debate)}

    # ── debate_list (read) ───────────────────────────────

    @mcp.tool()
    async def debate_list() -> dict:
        """
        Liste tous les débats connus (mémoire + S3).

        Requiert un token avec permission 'read' ou 'admin'.
        """
        # V1-02 : auth read requise
        from ..auth.context import check_access
        access_err = check_access("debates")
        if access_err:
            return access_err

        debates = _get_debate_store()

        items = [
            {
                "debate_id": d.id,
                "question": d.question[:100],
                "status": d.status.value,
                "phase": d.phase.value,
                "participants": len(d.participants),
                "rounds": len(d.rounds),
            }
            for d in debates.values()
        ]

        try:
            from ..services.storage.s3_store import get_debate_store
            store = get_debate_store()
            if store and store.available:
                memory_ids = {d.id for d in debates.values()}
                for s3d in store.list_debates(limit=20):
                    if s3d["id"] not in memory_ids:
                        items.append({
                            "debate_id": s3d["id"],
                            "source": "s3",
                            "size": s3d["size"],
                        })
        except Exception:
            pass

        return {"status": "ok", "debates": items, "total": len(items)}

    # ── provider_list (read) ─────────────────────────────

    @mcp.tool()
    async def provider_list() -> dict:
        """
        Liste les LLMs disponibles pour les débats.

        Requiert un token avec permission 'read' ou 'admin'.
        """
        # V1-02 : auth read requise
        from ..auth.context import check_access
        access_err = check_access("providers")
        if access_err:
            return access_err

        from ..services.llm.router import get_llm_router
        router = get_llm_router()
        return {"status": "ok", **router.list_providers()}

    # ── system_health (public) ───────────────────────────

    @mcp.tool()
    async def system_health() -> dict:
        """
        Vérifie l'état de santé du service AdviceRoom.

        Cet outil est public (pas d'authentification requise).
        Teste la connectivité S3 et les providers LLM.
        """
        results = {}

        # S3
        try:
            from ..services.storage.s3_store import get_debate_store
            store = get_debate_store()
            if store and store.available:
                results["s3"] = store.test_connectivity()
            else:
                results["s3"] = {"status": "not_configured"}
        except Exception:
            results["s3"] = {"status": "error", "message": "Erreur de connectivité S3"}

        # LLM Router
        try:
            from ..services.llm.router import get_llm_router
            router = get_llm_router()
            providers = router.list_providers()
            results["llm_router"] = {
                "status": "ok" if providers.get("loaded") else "not_loaded",
                "models_count": sum(
                    len(c.get("models", []))
                    for c in providers.get("categories", {}).values()
                ),
            }
        except Exception:
            results["llm_router"] = {"status": "error", "message": "Erreur LLM Router"}

        all_ok = all(r.get("status") == "ok" for r in results.values())

        return {
            "status": "ok" if all_ok else "degraded",
            "service": "adviceroom",
            "services": results,
        }

    # ── system_about (public) ────────────────────────────

    @mcp.tool()
    async def system_about() -> dict:
        """
        Informations sur le service AdviceRoom.

        Cet outil est public (pas d'authentification requise).
        """
        version = "dev"
        vf = Path(__file__).parent.parent.parent / "VERSION"
        if vf.exists():
            version = vf.read_text().strip()

        tools = []
        for tool in mcp._tool_manager.list_tools():
            raw_desc = (tool.description or "").strip()
            first_line = raw_desc.split("\n")[0].strip()
            tools.append({"name": tool.name, "description": first_line})

        return {
            "status": "ok",
            "service": "adviceroom",
            "version": version,
            "python_version": platform.python_version(),
            "tools_count": len(tools),
            "tools": tools,
        }

    logger.info(f"✓ {6} outils MCP enregistrés")

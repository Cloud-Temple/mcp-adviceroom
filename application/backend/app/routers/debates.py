"""
Debates Router — Endpoints REST pour la gestion des débats.

Endpoints (tous authentifiés — V1-01 fix) :
- POST /debates           → Créer et lancer un débat (write)
- GET  /debates/:id/stream → Stream NDJSON du débat en temps réel (read)
- GET  /debates/:id        → État / historique complet d'un débat (read)
- GET  /debates/:id/export → Export Markdown / HTML / JSON (read)
- GET  /debates            → Liste des débats (mémoire + S3) (read)
- POST /debates/:id/answer → Réponse utilisateur à une question LLM (write)
- POST /debates/:id/cancel → Arrêter un débat en cours (write)
- DELETE /debates/:id      → Supprimer un débat (write)

Le débat est créé puis exécuté en background task. Le client se connecte
au stream NDJSON pour recevoir les événements en temps réel.
Les débats terminés sont sauvegardés sur S3 Dell ECS.

Ref: DESIGN/architecture.md §4.2.1
Sécurité: DESIGN/SECURITY_AUDIT_V1.md V1-01, V1-03
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse
from pydantic import BaseModel, Field

from ..auth.context import require_read, require_write
from ..services.debate.orchestrator import DebateOrchestrator
from ..services.debate.models import Debate, DebateStatus, UserAnswer
from ..services.storage.s3_store import get_debate_store
from ..services.storage.serializer import (
    serialize_debate_full,
    export_debate_markdown,
    export_debate_html,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# Validation d'entrée (V1-03)
# ============================================================

# UUID v4 : 8-4-4-4-12 hex chars avec tirets
_DEBATE_ID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
_MAX_QUESTION_LENGTH = 10_000
_MAX_ANSWER_LENGTH = 10_000
_MAX_ROUNDS = 20


def _validate_debate_id(debate_id: str) -> str:
    """Valide le format UUID v4 du debate_id (V1-03)."""
    if not _DEBATE_ID_RE.match(debate_id):
        raise HTTPException(status_code=400, detail="debate_id invalide (UUID v4 attendu)")
    return debate_id


# ============================================================
# Store en mémoire + S3 persistence
# ============================================================

_active_debates: Dict[str, Debate] = {}
_debate_events: Dict[str, asyncio.Queue] = {}
_debate_events_history: Dict[str, List[Dict]] = {}  # Pour S3
_cancelled_debates: set = set()  # IDs des débats à annuler
_orchestrator: Optional[DebateOrchestrator] = None


def get_orchestrator() -> DebateOrchestrator:
    """Lazy singleton pour l'orchestrateur."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = DebateOrchestrator()
    return _orchestrator


# ============================================================
# Pydantic schemas pour l'API (V1-03 : validation renforcée)
# ============================================================

class ParticipantSpec(BaseModel):
    """Spécification d'un participant pour la création de débat."""
    provider: str = Field(
        description="Provider LLM (llmaas, openai, anthropic, google)",
        min_length=1, max_length=50,
    )
    model: str = Field(
        description="ID du modèle dans llm_models.yaml",
        min_length=1, max_length=100,
    )


class DebateCreateRequest(BaseModel):
    """Requête de création d'un débat."""
    question: str = Field(
        description="La question à débattre",
        min_length=5, max_length=_MAX_QUESTION_LENGTH,
    )
    participants: List[ParticipantSpec] = Field(
        description="LLMs participants (2-5)", min_length=2, max_length=5
    )
    persona_overrides: Optional[Dict[str, str]] = Field(
        default=None,
        description="Overrides de personas {model_id: persona_id ou texte libre}",
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Surcharges de config (max_rounds, tools_enabled, synthesizer_model)",
    )


class DebateCreateResponse(BaseModel):
    """Réponse de création d'un débat."""
    debate_id: str
    question: str
    participants: int
    stream_url: str


class UserAnswerRequest(BaseModel):
    """Réponse utilisateur à une question LLM."""
    answer: str = Field(
        description="La réponse de l'utilisateur",
        min_length=1, max_length=_MAX_ANSWER_LENGTH,
    )


# ============================================================
# POST /debates — Créer et lancer un débat (write)
# ============================================================

@router.post("/debates", response_model=DebateCreateResponse)
async def create_debate(
    request: DebateCreateRequest,
    background_tasks: BackgroundTasks,
    _token: dict = Depends(require_write),  # V1-01 : auth write requise
):
    """
    Crée un nouveau débat et le lance en background.

    Requiert un token avec permission 'write' ou 'admin'.
    """
    orchestrator = get_orchestrator()

    # V1-03 : borner max_rounds
    config_overrides = request.config
    if config_overrides and "max_rounds" in config_overrides:
        config_overrides["max_rounds"] = min(
            max(int(config_overrides["max_rounds"]), 1), _MAX_ROUNDS
        )

    # Créer le débat
    debate = orchestrator.create_debate(
        question=request.question,
        participant_specs=[p.model_dump() for p in request.participants],
        persona_overrides=request.persona_overrides,
        config_overrides=config_overrides,
    )

    if len(debate.participants) < 2:
        raise HTTPException(
            status_code=400,
            detail="Au moins 2 participants valides sont requis.",
        )

    # Stocker le débat et créer la queue d'événements
    _active_debates[debate.id] = debate
    _debate_events[debate.id] = asyncio.Queue()
    _debate_events_history[debate.id] = []

    # Lancer le débat en background
    background_tasks.add_task(_run_debate_task, debate.id)

    logger.info(f"✓ Débat {debate.id} créé, {len(debate.participants)} participants")

    return DebateCreateResponse(
        debate_id=debate.id,
        question=debate.question,
        participants=len(debate.participants),
        stream_url=f"/api/v1/debates/{debate.id}/stream",
    )


async def _run_debate_task(debate_id: str) -> None:
    """Background task qui exécute le débat et publie les événements."""
    debate = _active_debates.get(debate_id)
    queue = _debate_events.get(debate_id)
    events_history = _debate_events_history.get(debate_id)
    if not debate or not queue:
        return

    orchestrator = get_orchestrator()

    try:
        async for event in orchestrator.run(debate):
            # Vérifier si le débat a été annulé
            if debate_id in _cancelled_debates:
                _cancelled_debates.discard(debate_id)
                debate.status = DebateStatus.ERROR
                debate.error = "Débat arrêté par l'utilisateur"
                cancel_event = {"type": "error", "debate_id": debate_id, "error": "Débat arrêté par l'utilisateur"}
                await queue.put(cancel_event)
                if events_history is not None:
                    events_history.append(cancel_event)
                logger.info(f"🛑 Débat {debate_id} arrêté par l'utilisateur")
                break
            await queue.put(event)
            if events_history is not None:
                events_history.append(event)
    except Exception as e:
        logger.error(f"✗ Erreur background task débat {debate_id}: {e}")
        error_event = {"type": "error", "error": "Erreur interne lors du débat"}
        await queue.put(error_event)
        if events_history is not None:
            events_history.append(error_event)
    finally:
        await queue.put(None)  # Sentinel fin de stream

        # Sauvegarder sur S3
        try:
            debate.completed_at = datetime.now(timezone.utc)
            debate_dict = serialize_debate_full(debate)
            store = get_debate_store()
            if store.available:
                store.save_debate(debate_dict)
                if events_history:
                    store.save_events(debate_id, events_history)
                logger.info(f"✓ Débat {debate_id} persisté sur S3")
        except Exception as e:
            logger.error(f"✗ Erreur persistence S3 débat {debate_id}: {e}")


# ============================================================
# GET /debates/active — Liste des débats actifs (read)
# IMPORTANT: déclaré AVANT /debates/{debate_id} pour éviter conflit
# ============================================================

@router.get("/debates/active")
async def list_active_debates(
    _token: dict = Depends(require_read),  # V1-01
):
    """Liste les débats actuellement en cours d'exécution."""
    active = []
    for d in _active_debates.values():
        if d.status in (DebateStatus.RUNNING, DebateStatus.PAUSED):
            active.append(_debate_snapshot(d))

    return {"active_debates": active, "total": len(active)}


# ============================================================
# GET /debates/:id/status — Snapshot temps réel (read)
# ============================================================

@router.get("/debates/{debate_id}/status")
async def debate_status(
    debate_id: str,
    _token: dict = Depends(require_read),  # V1-01
):
    """Snapshot temps réel d'un débat actif ou terminé."""
    _validate_debate_id(debate_id)  # V1-03

    debate = _active_debates.get(debate_id)
    if debate:
        return {"status": "ok", "debate": _debate_snapshot(debate)}

    store = get_debate_store()
    if store.available:
        data = store.load_debate(debate_id)
        if data:
            return {"status": "ok", "debate": _s3_debate_snapshot(data)}

    raise HTTPException(status_code=404, detail="Débat non trouvé")


# ============================================================
# GET /debates/:id/stream — Stream NDJSON (read)
# ============================================================

@router.get("/debates/{debate_id}/stream")
async def stream_debate(
    debate_id: str,
    _token: dict = Depends(require_read),  # V1-01
):
    """Stream NDJSON des événements du débat en temps réel."""
    _validate_debate_id(debate_id)  # V1-03

    if debate_id not in _debate_events:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    return StreamingResponse(
        _event_generator(debate_id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _event_generator(debate_id: str):
    """Générateur async qui lit la queue et produit des lignes NDJSON."""
    queue = _debate_events.get(debate_id)
    if not queue:
        return
    while True:
        event = await queue.get()
        if event is None:
            break
        yield json.dumps(event, ensure_ascii=False) + "\n"


# ============================================================
# GET /debates/:id — État complet (read)
# ============================================================

@router.get("/debates/{debate_id}")
async def get_debate(
    debate_id: str,
    _token: dict = Depends(require_read),  # V1-01
):
    """Retourne l'état complet d'un débat."""
    _validate_debate_id(debate_id)  # V1-03

    debate = _active_debates.get(debate_id)
    if debate:
        return serialize_debate_full(debate)

    store = get_debate_store()
    if store.available:
        data = store.load_debate(debate_id)
        if data:
            return data

    raise HTTPException(status_code=404, detail="Débat non trouvé")


# ============================================================
# GET /debates/:id/export — Export (read)
# ============================================================

@router.get("/debates/{debate_id}/export")
async def export_debate(
    debate_id: str,
    format: str = Query(default="markdown", description="Format: markdown, html, json"),
    _token: dict = Depends(require_read),  # V1-01
):
    """Exporte un débat dans le format demandé (markdown, html, json)."""
    _validate_debate_id(debate_id)  # V1-03

    # V1-03 : whitelist du format
    if format not in ("markdown", "html", "json"):
        raise HTTPException(
            status_code=400,
            detail="Format non supporté. Utilisez markdown, html, ou json.",
        )

    debate = _active_debates.get(debate_id)
    if debate:
        debate_dict = serialize_debate_full(debate)
    else:
        store = get_debate_store()
        debate_dict = store.load_debate(debate_id) if store.available else None

    if not debate_dict:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    if format == "markdown":
        md = export_debate_markdown(debate_dict)
        return PlainTextResponse(
            content=md,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="debate-{debate_id[:8]}.md"'},
        )
    elif format == "html":
        html = export_debate_html(debate_dict)
        return HTMLResponse(
            content=html,
            headers={"Content-Disposition": f'attachment; filename="debate-{debate_id[:8]}.html"'},
        )
    else:
        return debate_dict


# ============================================================
# GET /debates — Liste (read)
# ============================================================

@router.get("/debates")
async def list_debates(
    _token: dict = Depends(require_read),  # V1-01
):
    """Liste tous les débats (mémoire locale + S3)."""
    debates = []

    memory_ids = set()
    for d in _active_debates.values():
        memory_ids.add(d.id)
        debates.append({
            "id": d.id,
            "question": d.question[:100],
            "status": d.status.value,
            "phase": d.phase.value,
            "participants": len(d.participants),
            "rounds": len(d.rounds),
            "total_tokens": d.total_tokens,
            "created_at": d.created_at.isoformat(),
            "source": "memory",
        })

    store = get_debate_store()
    if store.available:
        for s3d in store.list_debates(limit=50):
            if s3d["id"] not in memory_ids:
                full = store.load_debate(s3d["id"])
                if full:
                    debates.append({
                        "id": full["id"],
                        "question": full.get("question", "")[:100],
                        "status": full.get("status", "unknown"),
                        "phase": full.get("phase", "unknown"),
                        "participants": len(full.get("participants", [])),
                        "rounds": len(full.get("rounds", [])),
                        "total_tokens": full.get("total_tokens", 0),
                        "created_at": full.get("created_at", ""),
                        "source": "s3",
                    })

    debates.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return {"debates": debates, "total": len(debates)}


# ============================================================
# DELETE /debates/:id — Supprimer (write)
# ============================================================

@router.delete("/debates/{debate_id}")
async def delete_debate(
    debate_id: str,
    _token: dict = Depends(require_write),  # V1-01
):
    """Supprime un débat (mémoire + S3)."""
    _validate_debate_id(debate_id)  # V1-03

    deleted_from = []

    if debate_id in _active_debates:
        del _active_debates[debate_id]
        deleted_from.append("memory")
    if debate_id in _debate_events:
        del _debate_events[debate_id]
    if debate_id in _debate_events_history:
        del _debate_events_history[debate_id]

    store = get_debate_store()
    if store.available:
        if store.delete_debate(debate_id):
            deleted_from.append("s3")

    if not deleted_from:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    return {"status": "ok", "debate_id": debate_id, "deleted_from": deleted_from}


# ============================================================
# POST /debates/:id/cancel — Arrêter (write)
# ============================================================

@router.post("/debates/{debate_id}/cancel")
async def cancel_debate(
    debate_id: str,
    _token: dict = Depends(require_write),  # V1-01
):
    """Arrête un débat en cours."""
    _validate_debate_id(debate_id)  # V1-03

    debate = _active_debates.get(debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    if debate.status not in (DebateStatus.RUNNING, DebateStatus.PAUSED):
        raise HTTPException(
            status_code=409,
            detail=f"Le débat n'est pas en cours (status={debate.status.value})",
        )

    _cancelled_debates.add(debate_id)
    logger.info(f"🛑 Demande d'arrêt du débat {debate_id}")

    return {"status": "ok", "message": "Demande d'arrêt envoyée"}


# ============================================================
# POST /debates/:id/answer — Réponse utilisateur (write)
# ============================================================

@router.post("/debates/{debate_id}/answer")
async def answer_question(
    debate_id: str,
    request: UserAnswerRequest,
    _token: dict = Depends(require_write),  # V1-01
):
    """Envoie la réponse de l'utilisateur à une question posée par un LLM."""
    _validate_debate_id(debate_id)  # V1-03

    debate = _active_debates.get(debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    if debate.status != DebateStatus.PAUSED:
        raise HTTPException(
            status_code=409,
            detail=f"Le débat n'attend pas de réponse (status={debate.status.value})",
        )

    answer = UserAnswer(
        question="",
        answer=request.answer,
        asked_by="",
        round_number=len(debate.rounds),
    )
    debate.user_answers.append(answer)

    return {"status": "ok", "message": "Réponse enregistrée"}


# ============================================================
# Helpers — Snapshots (inchangés)
# ============================================================

def _debate_snapshot(debate: Debate) -> Dict[str, Any]:
    """Snapshot léger d'un débat en mémoire (temps réel)."""
    participants_progress = []
    for p in debate.participants:
        turns_ok = 0
        turns_error = 0
        last_confidence = None
        last_thesis = None

        for t in debate.opening_turns:
            if t.participant_id == p.id:
                if t.error:
                    turns_error += 1
                else:
                    turns_ok += 1
                    if t.structured_position:
                        last_confidence = t.structured_position.confidence
                        last_thesis = t.structured_position.thesis

        for rnd in debate.rounds:
            for t in rnd.turns:
                if t.participant_id == p.id:
                    if t.error:
                        turns_error += 1
                    else:
                        turns_ok += 1
                        if t.structured_position:
                            last_confidence = t.structured_position.confidence
                            last_thesis = t.structured_position.thesis

        participants_progress.append({
            "id": p.id,
            "display_name": p.display_name,
            "provider": p.provider,
            "persona": p.persona_name,
            "icon": p.persona_icon,
            "active": p.active,
            "turns_ok": turns_ok,
            "turns_error": turns_error,
            "last_confidence": last_confidence,
            "last_thesis": (last_thesis[:100] if last_thesis else None),
        })

    last_stability = None
    if debate.rounds:
        last_round = debate.rounds[-1]
        if last_round.stability_score is not None:
            last_stability = last_round.stability_score

    verdict_info = None
    if debate.verdict:
        verdict_info = {
            "type": debate.verdict.type.value,
            "confidence": debate.verdict.confidence,
            "summary": debate.verdict.summary[:200] if debate.verdict.summary else None,
            "synthesizer_model": debate.verdict.synthesizer_model,
        }

    return {
        "id": debate.id,
        "question": debate.question,
        "status": debate.status.value,
        "phase": debate.phase.value,
        "current_round": len(debate.rounds),
        "max_rounds": 5,
        "total_tokens": debate.total_tokens,
        "participants": participants_progress,
        "last_stability": last_stability,
        "verdict": verdict_info,
        "created_at": debate.created_at.isoformat(),
        "error": debate.error,
    }


def _s3_debate_snapshot(data: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot d'un débat chargé depuis S3."""
    participants = []
    for p in data.get("participants", []):
        participants.append({
            "id": p.get("id", p.get("model_id", "?")),
            "display_name": p.get("display_name", "?"),
            "provider": p.get("provider", "?"),
            "persona": p.get("persona_name", "?"),
            "icon": p.get("persona_icon", ""),
            "active": True,
        })

    errors = []
    rounds = data.get("rounds", [])
    for rnd in rounds:
        for t in rnd.get("turns", []):
            if t.get("error"):
                errors.append({
                    "round": rnd.get("round_number", "?"),
                    "participant": t.get("participant_id", "?"),
                    "error": t.get("error", "?")[:120],
                })

    verdict = data.get("verdict", {})
    verdict_info = None
    if verdict:
        verdict_info = {
            "type": verdict.get("type"),
            "confidence": verdict.get("confidence"),
            "summary": verdict.get("summary", "")[:200],
            "synthesizer_model": verdict.get("synthesizer_model"),
        }

    return {
        "id": data.get("id"),
        "question": data.get("question"),
        "status": data.get("status", "completed"),
        "phase": data.get("phase", "completed"),
        "current_round": len(rounds),
        "total_tokens": data.get("total_tokens", 0),
        "participants": participants,
        "verdict": verdict_info,
        "errors": errors,
        "created_at": data.get("created_at"),
        "completed_at": data.get("completed_at"),
    }

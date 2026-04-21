"""
Debates Router — Endpoints REST pour la gestion des débats.

Endpoints :
- POST /debates           → Créer et lancer un débat (retourne l'ID)
- GET  /debates/:id/stream → Stream NDJSON du débat en temps réel
- GET  /debates/:id        → État / historique complet d'un débat
- GET  /debates/:id/export → Export Markdown / HTML / JSON
- GET  /debates            → Liste des débats (mémoire + S3)
- POST /debates/:id/answer → Réponse utilisateur à une question LLM

Le débat est créé puis exécuté en background task. Le client se connecte
au stream NDJSON pour recevoir les événements en temps réel.
Les débats terminés sont sauvegardés sur S3 Dell ECS.

Ref: DESIGN/architecture.md §4.2.1
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse
from pydantic import BaseModel, Field

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
# Pydantic schemas pour l'API
# ============================================================

class ParticipantSpec(BaseModel):
    """Spécification d'un participant pour la création de débat."""
    provider: str = Field(description="Provider LLM (llmaas, openai, anthropic, google)")
    model: str = Field(description="ID du modèle dans llm_models.yaml")


class DebateCreateRequest(BaseModel):
    """Requête de création d'un débat."""
    question: str = Field(description="La question à débattre")
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
    answer: str = Field(description="La réponse de l'utilisateur")


# ============================================================
# POST /debates — Créer et lancer un débat
# ============================================================

@router.post("/debates", response_model=DebateCreateResponse)
async def create_debate(
    request: DebateCreateRequest,
    background_tasks: BackgroundTasks,
):
    """
    Crée un nouveau débat et le lance en background.

    Le débat est exécuté de manière asynchrone. Le client doit se connecter
    au stream NDJSON pour recevoir les événements en temps réel.
    Les débats terminés sont automatiquement sauvegardés sur S3.

    Returns:
        debate_id et URL du stream.
    """
    orchestrator = get_orchestrator()

    # Créer le débat
    debate = orchestrator.create_debate(
        question=request.question,
        participant_specs=[p.model_dump() for p in request.participants],
        persona_overrides=request.persona_overrides,
        config_overrides=request.config,
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
    """
    Background task qui exécute le débat et publie les événements.

    Collecte aussi les événements pour la persistence S3.
    """
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
            # Historique pour S3
            if events_history is not None:
                events_history.append(event)
    except Exception as e:
        logger.error(f"✗ Erreur background task débat {debate_id}: {e}")
        error_event = {"type": "error", "error": str(e)}
        await queue.put(error_event)
        if events_history is not None:
            events_history.append(error_event)
    finally:
        # Sentinel pour signaler la fin du stream
        await queue.put(None)

        # Sauvegarder sur S3 (async dans un thread pour ne pas bloquer)
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
# GET /debates/active — Liste des débats actifs (temps réel)
# IMPORTANT: déclaré AVANT /debates/{debate_id} pour éviter conflit
# ============================================================

@router.get("/debates/active")
async def list_active_debates():
    """
    Liste les débats actuellement en cours d'exécution.

    Retourne un snapshot léger pour le dashboard temps réel :
    phase, round courant, participants, tokens, erreurs.
    """
    active = []
    for d in _active_debates.values():
        if d.status in (DebateStatus.RUNNING, DebateStatus.PAUSED):
            active.append(_debate_snapshot(d))

    return {
        "active_debates": active,
        "total": len(active),
    }


# ============================================================
# GET /debates/:id/status — Snapshot temps réel d'un débat
# ============================================================

@router.get("/debates/{debate_id}/status")
async def debate_status(debate_id: str):
    """
    Snapshot temps réel d'un débat actif ou terminé.

    Pour un débat actif : phase, round courant, progression par participant,
    tokens cumulés, erreurs, stabilité du dernier round.

    Pour un débat terminé : charge depuis S3 et retourne un résumé.
    """
    # 1. Débat en mémoire (actif ou récent)
    debate = _active_debates.get(debate_id)
    if debate:
        return {"status": "ok", "debate": _debate_snapshot(debate)}

    # 2. Débat sur S3 (terminé)
    store = get_debate_store()
    if store.available:
        data = store.load_debate(debate_id)
        if data:
            return {"status": "ok", "debate": _s3_debate_snapshot(data)}

    raise HTTPException(status_code=404, detail="Débat non trouvé")


# ============================================================
# GET /debates/:id/stream — Stream NDJSON en temps réel
# ============================================================

@router.get("/debates/{debate_id}/stream")
async def stream_debate(debate_id: str):
    """
    Stream NDJSON des événements du débat en temps réel.

    Chaque ligne est un objet JSON terminé par \\n.
    Le stream se termine quand le débat est terminé ou en erreur.
    """
    if debate_id not in _debate_events:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    return StreamingResponse(
        _event_generator(debate_id),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_generator(debate_id: str):
    """Générateur async qui lit la queue et produit des lignes NDJSON."""
    queue = _debate_events.get(debate_id)
    if not queue:
        return

    while True:
        event = await queue.get()
        if event is None:
            # Fin du stream
            break
        yield json.dumps(event, ensure_ascii=False) + "\n"


# ============================================================
# GET /debates/:id — État complet d'un débat
# ============================================================

@router.get("/debates/{debate_id}")
async def get_debate(debate_id: str):
    """
    Retourne l'état complet d'un débat.

    Cherche d'abord en mémoire, puis sur S3 si non trouvé.
    Inclut toutes les données : turns, positions, tools, verdict, stats.
    """
    # 1. Chercher en mémoire (débat en cours ou récent)
    debate = _active_debates.get(debate_id)
    if debate:
        return serialize_debate_full(debate)

    # 2. Chercher sur S3 (débat terminé/ancien)
    store = get_debate_store()
    if store.available:
        data = store.load_debate(debate_id)
        if data:
            return data

    raise HTTPException(status_code=404, detail="Débat non trouvé")


# ============================================================
# GET /debates/:id/export — Export Markdown / HTML / JSON
# ============================================================

@router.get("/debates/{debate_id}/export")
async def export_debate(
    debate_id: str,
    format: str = Query(default="markdown", description="Format: markdown, html, json"),
):
    """
    Exporte un débat dans le format demandé.

    Formats supportés :
    - markdown → Document Markdown complet
    - html → Page HTML autonome
    - json → JSON complet (identique à GET /debates/:id)
    """
    # Récupérer le débat (mémoire ou S3)
    debate = _active_debates.get(debate_id)
    if debate:
        debate_dict = serialize_debate_full(debate)
    else:
        store = get_debate_store()
        if store.available:
            debate_dict = store.load_debate(debate_id)
        else:
            debate_dict = None

    if not debate_dict:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    if format == "markdown":
        md = export_debate_markdown(debate_dict)
        return PlainTextResponse(
            content=md,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="debate-{debate_id[:8]}.md"'
            },
        )
    elif format == "html":
        html = export_debate_html(debate_dict)
        return HTMLResponse(
            content=html,
            headers={
                "Content-Disposition": f'attachment; filename="debate-{debate_id[:8]}.html"'
            },
        )
    elif format == "json":
        return debate_dict
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporté: {format}. Utilisez markdown, html, ou json.",
        )


# ============================================================
# GET /debates — Liste des débats (mémoire + S3)
# ============================================================

@router.get("/debates")
async def list_debates():
    """
    Liste tous les débats (mémoire locale + S3).

    Combine les débats actifs en mémoire avec ceux sauvegardés sur S3.
    """
    debates = []

    # 1. Débats en mémoire (actifs/récents)
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

    # 2. Débats sur S3 (non déjà en mémoire)
    store = get_debate_store()
    if store.available:
        s3_debates = store.list_debates(limit=50)
        for s3d in s3_debates:
            if s3d["id"] not in memory_ids:
                # Charger les métadonnées depuis S3
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

    # Trier par date (plus récent en premier)
    debates.sort(key=lambda d: d.get("created_at", ""), reverse=True)

    return {
        "debates": debates,
        "total": len(debates),
    }


# ============================================================
# DELETE /debates/:id — Supprimer un débat
# ============================================================

@router.delete("/debates/{debate_id}")
async def delete_debate(debate_id: str):
    """
    Supprime un débat (mémoire + S3).

    Supprime le JSON complet et les événements NDJSON associés.
    """
    deleted_from = []

    # 1. Supprimer de la mémoire
    if debate_id in _active_debates:
        del _active_debates[debate_id]
        deleted_from.append("memory")
    if debate_id in _debate_events:
        del _debate_events[debate_id]
    if debate_id in _debate_events_history:
        del _debate_events_history[debate_id]

    # 2. Supprimer de S3
    store = get_debate_store()
    if store.available:
        if store.delete_debate(debate_id):
            deleted_from.append("s3")

    if not deleted_from:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    return {
        "status": "ok",
        "debate_id": debate_id,
        "deleted_from": deleted_from,
    }


def _debate_snapshot(debate: Debate) -> Dict[str, Any]:
    """Snapshot léger d'un débat en mémoire (temps réel)."""
    # Progression par participant
    participants_progress = []
    for p in debate.participants:
        # Compter les turns réussis vs erreurs
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

    # Stabilité du dernier round
    last_stability = None
    if debate.rounds:
        last_round = debate.rounds[-1]
        if last_round.stability_score is not None:
            last_stability = last_round.stability_score

    # Verdict (si terminé)
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

    # Compter erreurs par round
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


# ============================================================
# POST /debates/:id/cancel — Arrêter un débat en cours
# ============================================================

@router.post("/debates/{debate_id}/cancel")
async def cancel_debate(debate_id: str):
    """
    Arrête un débat en cours. Le débat sera stoppé au prochain tour
    et sauvegardé sur S3 avec le statut error.
    """
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

    return {"status": "ok", "message": "Demande d'arrêt envoyée — le débat sera stoppé au prochain tour"}


# ============================================================
# POST /debates/:id/answer — Réponse utilisateur
# ============================================================

@router.post("/debates/{debate_id}/answer")
async def answer_question(debate_id: str, request: UserAnswerRequest):
    """
    Envoie la réponse de l'utilisateur à une question posée par un LLM.

    Le débat reprend automatiquement après réception de la réponse.
    """
    debate = _active_debates.get(debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    if debate.status != DebateStatus.PAUSED:
        raise HTTPException(
            status_code=409,
            detail=f"Le débat n'attend pas de réponse (status={debate.status.value})",
        )

    # Ajouter la réponse au débat
    answer = UserAnswer(
        question="",
        answer=request.answer,
        asked_by="",
        round_number=len(debate.rounds),
    )
    debate.user_answers.append(answer)

    return {"status": "ok", "message": "Réponse enregistrée"}

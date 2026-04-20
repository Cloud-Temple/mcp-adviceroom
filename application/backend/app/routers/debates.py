"""
Debates Router — Endpoints REST pour la gestion des débats.

Endpoints :
- POST /debates           → Créer et lancer un débat (retourne l'ID)
- GET  /debates/:id/stream → Stream NDJSON du débat en temps réel
- GET  /debates/:id        → État / historique d'un débat
- GET  /debates            → Liste des débats
- POST /debates/:id/answer → Réponse utilisateur à une question LLM

Le débat est créé puis exécuté en background task. Le client se connecte
au stream NDJSON pour recevoir les événements en temps réel.

Ref: DESIGN/architecture.md §4.2.1
"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.debate.orchestrator import DebateOrchestrator
from ..services.debate.models import Debate, DebateStatus, UserAnswer

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# Store en mémoire des débats actifs (v1 — remplacé par S3 en v2)
# ============================================================

_active_debates: Dict[str, Debate] = {}
_debate_events: Dict[str, asyncio.Queue] = {}
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
    if not debate or not queue:
        return

    orchestrator = get_orchestrator()

    try:
        async for event in orchestrator.run(debate):
            await queue.put(event)
    except Exception as e:
        logger.error(f"✗ Erreur background task débat {debate_id}: {e}")
        await queue.put({"type": "error", "error": str(e)})
    finally:
        # Sentinel pour signaler la fin du stream
        await queue.put(None)


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
# GET /debates/:id — État d'un débat
# ============================================================

@router.get("/debates/{debate_id}")
async def get_debate(debate_id: str):
    """
    Retourne l'état actuel d'un débat.

    Inclut les métadonnées, le statut, les participants,
    et le verdict (si terminé).
    """
    debate = _active_debates.get(debate_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Débat non trouvé")

    return _serialize_debate(debate)


# ============================================================
# GET /debates — Liste des débats
# ============================================================

@router.get("/debates")
async def list_debates():
    """
    Liste tous les débats (mémoire locale en v1).

    En v2, filtré par API key hash pour l'isolation multi-tenant.
    """
    return {
        "debates": [
            {
                "id": d.id,
                "question": d.question[:100],
                "status": d.status.value,
                "phase": d.phase.value,
                "participants": len(d.participants),
                "rounds": len(d.rounds),
                "created_at": d.created_at.isoformat(),
            }
            for d in _active_debates.values()
        ],
        "total": len(_active_debates),
    }


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
    # Note: l'intégration complète pause/resume sera faite en v2
    answer = UserAnswer(
        question="",  # TODO: récupérer la question en attente
        answer=request.answer,
        asked_by="",  # TODO: récupérer le participant qui a posé la question
        round_number=len(debate.rounds),
    )
    debate.user_answers.append(answer)

    return {"status": "ok", "message": "Réponse enregistrée"}


# ============================================================
# Helpers
# ============================================================

def _serialize_debate(debate: Debate) -> dict:
    """Sérialise un Debate pour l'API REST."""
    result = {
        "id": debate.id,
        "question": debate.question,
        "status": debate.status.value,
        "phase": debate.phase.value,
        "participants": [
            {
                "id": p.id,
                "model_id": p.model_id,
                "provider": p.provider,
                "display_name": p.display_name,
                "persona_name": p.persona_name,
                "persona_icon": p.persona_icon,
                "active": p.active,
            }
            for p in debate.participants
        ],
        "rounds_count": len(debate.rounds),
        "total_tokens": debate.total_tokens,
        "created_at": debate.created_at.isoformat(),
    }

    if debate.verdict:
        result["verdict"] = {
            "type": debate.verdict.type.value,
            "confidence": debate.verdict.confidence,
            "summary": debate.verdict.summary,
            "agreement_points": debate.verdict.agreement_points,
            "recommendation": debate.verdict.recommendation,
        }

    return result

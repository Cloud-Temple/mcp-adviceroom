"""
Providers Router — Endpoints REST pour les modèles LLM.

Endpoints (authentifiés — V1-01 fix) :
- GET /providers          → Liste des modèles groupés par catégorie (read)
- GET /providers/:id/status → Test de connectivité d'un provider (read)

Ref: DESIGN/architecture.md §4.2.1
Sécurité: DESIGN/SECURITY_AUDIT_V1.md V1-01, V1-03
"""
import re
import logging

from fastapi import APIRouter, Depends, HTTPException

from ..auth.context import require_read
from ..services.llm.router import get_llm_router

logger = logging.getLogger(__name__)

router = APIRouter()

# V1-03 : validation du nom de provider (alphanum + tirets)
_PROVIDER_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


# ============================================================
# GET /providers — Liste des modèles LLM disponibles (read)
# ============================================================

@router.get("/providers")
async def list_providers(
    _token: dict = Depends(require_read),  # V1-01
):
    """Liste tous les modèles LLM disponibles, groupés par catégorie."""
    llm_router = get_llm_router()
    if not llm_router.loaded:
        raise HTTPException(status_code=503, detail="LLM Router non initialisé")

    return llm_router.get_models_by_category()


# ============================================================
# GET /providers/:id/status — Statut d'un provider (read)
# ============================================================

@router.get("/providers/{provider_name}/status")
async def provider_status(
    provider_name: str,
    _token: dict = Depends(require_read),  # V1-01
):
    """Teste la connectivité d'un provider LLM."""
    # V1-03 : validation du nom de provider
    if not _PROVIDER_NAME_RE.match(provider_name):
        raise HTTPException(status_code=400, detail="Nom de provider invalide")

    llm_router = get_llm_router()
    provider = llm_router.get_provider(provider_name)

    if not provider:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_name}' non trouvé",
        )

    result = await provider.test_connectivity()
    return {"provider": provider_name, **result}

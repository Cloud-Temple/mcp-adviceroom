"""
Providers Router — Endpoints REST pour les modèles LLM.

Endpoints :
- GET /providers          → Liste des modèles groupés par catégorie
- GET /providers/:id/status → Test de connectivité d'un provider

Ref: DESIGN/architecture.md §4.2.1
"""
import logging

from fastapi import APIRouter, HTTPException

from ..services.llm.router import get_llm_router

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# GET /providers — Liste des modèles LLM disponibles
# ============================================================

@router.get("/providers")
async def list_providers():
    """
    Liste tous les modèles LLM disponibles, groupés par catégorie.

    Retourne les catégories (snc, openai, anthropic, google) avec
    les modèles actifs de chaque catégorie.
    """
    llm_router = get_llm_router()
    if not llm_router.loaded:
        raise HTTPException(status_code=503, detail="LLM Router non initialisé")

    return llm_router.get_models_by_category()


# ============================================================
# GET /providers/:id/status — Statut d'un provider
# ============================================================

@router.get("/providers/{provider_name}/status")
async def provider_status(provider_name: str):
    """
    Teste la connectivité d'un provider LLM.

    Args:
        provider_name: Nom du provider (llmaas, openai, anthropic, google).

    Returns:
        Statut de la connexion avec les modèles disponibles.
    """
    llm_router = get_llm_router()
    provider = llm_router.get_provider(provider_name)

    if not provider:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_name}' non trouvé. "
                   f"Disponibles : {list(llm_router._providers.keys())}",
        )

    result = await provider.test_connectivity()
    return {
        "provider": provider_name,
        **result,
    }

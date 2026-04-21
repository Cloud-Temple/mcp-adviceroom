# -*- coding: utf-8 -*-
"""
Helpers d'authentification basés sur contextvars.

Le middleware ASGI injecte les infos du token dans les contextvars.
Les outils MCP appellent check_access() et check_write_permission()
pour vérifier les permissions sans dépendre du framework HTTP.

Pattern identique au starter-kit Cloud Temple.
"""

from contextvars import ContextVar
from typing import Optional

# --- Context variable injectée par AuthMiddleware ---
current_token_info: ContextVar[Optional[dict]] = ContextVar(
    "current_token_info", default=None
)


def check_access(resource_id: str) -> Optional[dict]:
    """
    Vérifie que le token courant a accès à la ressource.

    Args:
        resource_id: ID de la ressource à vérifier

    Returns:
        None si OK, dict {"status": "error", ...} si refusé
    """
    token_info = current_token_info.get()

    # Pas de token → accès refusé
    if token_info is None:
        return {"status": "error", "message": "Authentification requise"}

    # Admin → accès total
    if "admin" in token_info.get("permissions", []):
        return None

    # Vérifier que la ressource est dans la liste autorisée
    allowed = token_info.get("allowed_resources", [])
    if allowed and resource_id not in allowed:
        return {
            "status": "error",
            "message": f"Accès refusé à la ressource '{resource_id}'",
        }

    return None  # OK


def check_write_permission() -> Optional[dict]:
    """
    Vérifie que le token courant a la permission d'écriture.

    Returns:
        None si OK, dict {"status": "error", ...} si refusé
    """
    token_info = current_token_info.get()

    if token_info is None:
        return {"status": "error", "message": "Authentification requise"}

    permissions = token_info.get("permissions", [])
    if "write" in permissions or "admin" in permissions:
        return None

    return {
        "status": "error",
        "message": "Permission 'write' requise pour cette opération",
    }


# =============================================================================
# Helpers d'identité (utiles pour le multi-tenant et la traçabilité)
# =============================================================================


def get_current_client_name() -> str:
    """
    Retourne le client_name du token courant.

    Returns:
        Nom du client, ou "anonymous" si pas d'auth
    """
    info = current_token_info.get()
    if info is None:
        return "anonymous"
    return info.get("client_name", "anonymous")


def is_admin() -> bool:
    """
    Vérifie si le token courant a la permission admin.

    Returns:
        True si admin, False sinon
    """
    info = current_token_info.get()
    if info is None:
        return False
    return "admin" in info.get("permissions", [])

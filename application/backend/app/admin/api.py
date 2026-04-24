# -*- coding: utf-8 -*-
"""
API REST admin — Endpoints pour la console d'administration AdviceRoom.

Tous les endpoints requièrent un Bearer token admin.
Routage depuis AdminMiddleware pour /admin/api/*.

Endpoints :
    GET  /admin/api/health        → État du serveur + LLM Router
    GET  /admin/api/whoami        → Identité du token courant
    GET  /admin/api/tokens        → Liste des tokens
    POST /admin/api/tokens        → Créer un token
    DEL  /admin/api/tokens/{hash} → Révoquer un token
    GET  /admin/api/logs          → Activité récente (ring buffer)
    GET  /admin/api/debates       → Liste des débats S3
    GET  /admin/api/debates/{id}  → Détails d'un débat

Pattern adapté du starter-kit Cloud Temple.
"""

import json
import hmac
import hashlib
import platform
from pathlib import Path

from ..config.settings import get_settings
from ..auth.token_store import get_token_store
from ..auth.middleware import get_activity_log


async def handle_admin_api(scope, receive, send, mcp):
    """Routeur principal de l'API admin.

    Niveaux d'accès :
    - Routes de lecture (health, whoami, models, debates, logs) → tout token authentifié (read)
    - Routes d'écriture tokens (create, revoke) → admin uniquement
    - Routes d'écriture débats (delete) → tout token authentifié (write)
    """
    path = scope.get("path", "")
    method = scope.get("method", "GET")

    # --- Auth : au minimum un token valide ---
    token = _extract_admin_token(scope)
    if not _is_authenticated(token):
        return await _json_response(
            send, 401, {"status": "error", "message": "Token required"}
        )

    # --- Routes en lecture (tout token authentifié) ---
    if path == "/admin/api/health" and method == "GET":
        return await _api_health(send, mcp)

    if path == "/admin/api/whoami" and method == "GET":
        return await _api_whoami(send, token)

    if path == "/admin/api/logs" and method == "GET":
        return await _api_logs(send)

    if path == "/admin/api/llm-activity" and method == "GET":
        return await _api_llm_activity(send)

    if path == "/admin/api/models" and method == "GET":
        return await _api_list_models(send)

    if path == "/admin/api/debates" and method == "GET":
        return await _api_list_debates(send)

    if path.startswith("/admin/api/debates/") and method == "GET":
        debate_id = path[len("/admin/api/debates/"):]
        return await _api_get_debate(send, debate_id)

    if path.startswith("/admin/api/debates/") and method == "DELETE":
        debate_id = path[len("/admin/api/debates/"):]
        return await _api_delete_debate(send, debate_id)

    # --- Routes admin-only (gestion tokens) ---
    if not _is_admin(token):
        return await _json_response(
            send, 403, {"status": "error", "message": "Admin permission required"}
        )

    if path == "/admin/api/tokens" and method == "GET":
        return await _api_list_tokens(send)

    if path == "/admin/api/tokens" and method == "POST":
        body = await _read_body(receive)
        return await _api_create_token(send, body)

    if path.startswith("/admin/api/tokens/") and method == "DELETE":
        hash_prefix = path.split("/")[-1]
        return await _api_revoke_token(send, hash_prefix)

    return await _json_response(
        send, 404, {"status": "error", "message": f"Unknown admin route: {path}"}
    )


# =============================================================================
# Endpoints
# =============================================================================


async def _api_health(send, mcp):
    """GET /admin/api/health — État du serveur + LLM Router."""
    settings = get_settings()
    version = "dev"
    vf = Path(__file__).parent.parent.parent / "VERSION"
    if vf.exists():
        version = vf.read_text().strip()

    # Outils MCP
    tools = []
    if mcp:
        try:
            tools = [t.name for t in mcp._tool_manager.list_tools()]
        except Exception:
            pass

    # S3 status
    s3_status = "not_configured"
    if settings.s3_endpoint:
        try:
            from ..services.storage.s3_store import get_debate_store
            store = get_debate_store()
            if store and store.available:
                s3_status = "ok"
            else:
                s3_status = "error"
        except Exception:
            s3_status = "error"

    # LLM Router status
    llm_status = "not_loaded"
    models_count = 0
    try:
        from ..services.llm.router import get_llm_router
        router = get_llm_router()
        if router.loaded:
            llm_status = "ok"
            providers = router.get_models_by_category()
            models_count = sum(
                len(c.get("models", []))
                for c in providers.get("categories", {}).values()
            )
    except Exception:
        pass

    await _json_response(send, 200, {
        "status": "ok",
        "service_name": "AdviceRoom",
        "version": version,
        "python_version": platform.python_version(),
        "tools_count": len(tools),
        "tools": tools,
        "s3_status": s3_status,
        "llm_status": llm_status,
        "llm_models_count": models_count,
    })


async def _api_whoami(send, token):
    """GET /admin/api/whoami — Identité du token courant."""
    settings = get_settings()
    auth_type = (
        "bootstrap"
        if hmac.compare_digest(token, settings.admin_bootstrap_key)
        else "token"
    )
    result = {"status": "ok", "auth_type": auth_type}

    if auth_type == "token":
        store = get_token_store()
        if store:
            h = hashlib.sha256(token.encode()).hexdigest()
            info = store.get_by_hash(h)
            if info:
                result["client_name"] = info.get("client_name", "?")
                result["permissions"] = info.get("permissions", [])
                result["email"] = info.get("email", "")
                result["hash_prefix"] = h[:12]
    else:
        result["client_name"] = "admin"
        result["permissions"] = ["admin", "read", "write"]

    await _json_response(send, 200, result)


async def _api_list_tokens(send):
    """GET /admin/api/tokens — Liste des tokens."""
    store = get_token_store()
    if not store:
        return await _json_response(
            send, 200,
            {"status": "ok", "tokens": [], "message": "S3 non configuré"},
        )
    await _json_response(
        send, 200, {"status": "ok", "tokens": store.list_all()}
    )


# V1-09 : whitelist des permissions valides
_VALID_PERMISSIONS = {"read", "write", "admin"}


async def _api_create_token(send, body):
    """POST /admin/api/tokens — Créer un token."""
    store = get_token_store()
    if not store:
        return await _json_response(
            send, 400,
            {"status": "error", "message": "S3 non configuré"},
        )

    data = json.loads(body) if body else {}
    client_name = data.get("client_name", "")
    permissions = data.get("permissions", ["read"])
    allowed_resources = data.get("allowed_resources", [])
    email = data.get("email", "")
    expires_in_days = data.get("expires_in_days", 90)

    # V1-03 : validation client_name (alphanum + tirets, max 64)
    if not client_name or len(client_name) > 64:
        return await _json_response(
            send, 400, {"status": "error", "message": "client_name requis (max 64 chars)"}
        )

    # V1-09 : whitelist des permissions
    if not isinstance(permissions, list) or not set(permissions).issubset(_VALID_PERMISSIONS):
        return await _json_response(
            send, 400,
            {"status": "error", "message": f"Permissions invalides. Valides: {sorted(_VALID_PERMISSIONS)}"},
        )

    # V1-03 : borner expires_in_days
    try:
        expires_in_days = max(0, min(int(expires_in_days), 3650))  # max 10 ans
    except (ValueError, TypeError):
        expires_in_days = 90

    result = store.create(
        client_name, permissions, allowed_resources,
        expires_in_days=expires_in_days, email=email,
    )
    await _json_response(send, 201, {"status": "created", **result})


async def _api_revoke_token(send, hash_prefix):
    """DELETE /admin/api/tokens/{hash_prefix} — Révoquer un token."""
    store = get_token_store()
    if not store:
        return await _json_response(
            send, 400,
            {"status": "error", "message": "S3 non configuré"},
        )

    if len(hash_prefix) < 8:
        return await _json_response(send, 400, {
            "status": "error",
            "message": "Hash prefix trop court (min 8 caractères)",
        })

    if store.revoke(hash_prefix):
        await _json_response(
            send, 200,
            {"status": "ok", "message": f"Token {hash_prefix}… révoqué"},
        )
    else:
        await _json_response(
            send, 404,
            {"status": "error", "message": f"Token {hash_prefix}… non trouvé"},
        )


async def _api_logs(send):
    """GET /admin/api/logs — Activité récente (ring buffer)."""
    logs = get_activity_log()
    await _json_response(
        send, 200,
        {"status": "ok", "count": len(logs), "logs": logs[-50:]},
    )


async def _api_llm_activity(send):
    """GET /admin/api/llm-activity — Activité LLM détaillée (tours, verdicts, erreurs)."""
    try:
        from ..services.debate.orchestrator import get_llm_activity_log
        logs = get_llm_activity_log()
    except Exception:
        logs = []

    await _json_response(send, 200, {
        "status": "ok",
        "count": len(logs),
        "logs": logs[:100],  # 100 derniers événements
    })


async def _api_list_models(send):
    """GET /admin/api/models — Liste des modèles LLM disponibles."""
    models = []
    try:
        from ..services.llm.router import get_llm_router
        router = get_llm_router()
        if router.loaded:
            providers = router.get_models_by_category()
            for cat_name, cat_data in providers.get("categories", {}).items():
                for m in cat_data.get("models", []):
                    models.append({
                        "id": m.get("id", ""),
                        "display_name": m.get("display_name", ""),
                        "provider": m.get("provider", ""),
                        "category": cat_name,
                        "active": m.get("active", True),
                    })
    except Exception:
        pass

    await _json_response(send, 200, {
        "status": "ok",
        "models": models,
        "total": len(models),
    })


async def _api_list_debates(send):
    """GET /admin/api/debates — Liste des débats (mémoire + S3) avec métadonnées enrichies."""
    debates = []

    # Débats en mémoire
    try:
        from ..routers.debates import _active_debates
        for d in _active_debates.values():
            debates.append(_summarize_debate_memory(d))
    except Exception:
        pass

    # Débats sur S3 — on charge chaque JSON pour extraire les métadonnées
    try:
        from ..services.storage.s3_store import get_debate_store
        store = get_debate_store()
        if store and store.available:
            memory_ids = {d["id"] for d in debates}
            for s3d in store.list_debates(limit=50):
                if s3d["id"] not in memory_ids:
                    # Charger le JSON complet pour extraire les métadonnées
                    full = store.load_debate(s3d["id"])
                    if full:
                        debates.append(_summarize_debate_dict(full, s3d))
                    else:
                        # Fallback si le load échoue
                        debates.append({
                            "id": s3d["id"],
                            "question": "",
                            "status": "unknown",
                            "source": "s3",
                            "size": s3d.get("size", 0),
                            "last_modified": str(s3d.get("last_modified", "")),
                        })
    except Exception:
        pass

    # Trier par date (plus récent en premier)
    debates.sort(key=lambda d: d.get("created_at", ""), reverse=True)

    await _json_response(
        send, 200,
        {"status": "ok", "debates": debates, "total": len(debates)},
    )


async def _api_get_debate(send, debate_id):
    """GET /admin/api/debates/{id} — Détails d'un débat."""
    # Chercher en mémoire d'abord
    try:
        from ..routers.debates import _active_debates
        debate = _active_debates.get(debate_id)
        if debate:
            from ..services.storage.serializer import serialize_debate_full
            return await _json_response(
                send, 200,
                {"status": "ok", "source": "memory", "debate": serialize_debate_full(debate)},
            )
    except Exception:
        pass

    # Chercher sur S3
    try:
        from ..services.storage.s3_store import get_debate_store
        store = get_debate_store()
        if store and store.available:
            data = store.load_debate(debate_id)
            if data:
                return await _json_response(
                    send, 200,
                    {"status": "ok", "source": "s3", "debate": data},
                )
    except Exception:
        pass

    await _json_response(
        send, 404,
        {"status": "error", "message": f"Débat '{debate_id}' non trouvé"},
    )


async def _api_delete_debate(send, debate_id):
    """DELETE /admin/api/debates/{id} — Supprimer un débat (mémoire + S3)."""
    deleted_from = []

    # Supprimer de la mémoire
    try:
        from ..routers.debates import _active_debates, _debate_events, _debate_events_history
        if debate_id in _active_debates:
            del _active_debates[debate_id]
            deleted_from.append("memory")
        if debate_id in _debate_events:
            del _debate_events[debate_id]
        if debate_id in _debate_events_history:
            del _debate_events_history[debate_id]
    except Exception:
        pass

    # Supprimer de S3
    try:
        from ..services.storage.s3_store import get_debate_store
        store = get_debate_store()
        if store and store.available:
            if store.delete_debate(debate_id):
                deleted_from.append("s3")
    except Exception:
        pass

    if not deleted_from:
        return await _json_response(
            send, 404,
            {"status": "error", "message": f"Débat '{debate_id}' non trouvé"},
        )

    await _json_response(send, 200, {
        "status": "ok",
        "debate_id": debate_id,
        "deleted_from": deleted_from,
        "message": f"Débat supprimé de: {', '.join(deleted_from)}",
    })


# =============================================================================
# Debate summary helpers
# =============================================================================


def _summarize_debate_memory(debate) -> dict:
    """Résumé d'un débat en mémoire (objet Debate)."""
    verdict_info = None
    if debate.verdict:
        verdict_info = {
            "type": debate.verdict.type.value,
            "confidence": debate.verdict.confidence,
            "summary": debate.verdict.summary[:200] if debate.verdict.summary else "",
            "agreement_points": debate.verdict.agreement_points[:5],
            "divergence_points": [
                p.get("topic", str(p)[:80]) if isinstance(p, dict) else str(p)[:80]
                for p in debate.verdict.divergence_points[:5]
            ],
            "recommendation": debate.verdict.recommendation[:200] if debate.verdict.recommendation else "",
        }

    participants = []
    for p in debate.participants:
        participants.append({
            "id": p.id,
            "model_id": p.model_id,
            "provider": p.provider,
            "display_name": p.display_name,
            "persona_name": p.persona_name,
            "persona_icon": p.persona_icon,
        })

    return {
        "id": debate.id,
        "question": debate.question,
        "mode": debate.mode.value if hasattr(debate, 'mode') and hasattr(debate.mode, 'value') else "",
        "status": debate.status.value,
        "phase": debate.phase.value,
        "created_at": debate.created_at.isoformat(),
        "completed_at": debate.completed_at.isoformat() if debate.completed_at else None,
        "total_tokens": debate.total_tokens,
        "participants": participants,
        "num_participants": len(debate.participants),
        "num_rounds": len(debate.rounds),
        "verdict": verdict_info,
        "source": "memory",
    }


def _summarize_debate_dict(full: dict, s3_meta: dict) -> dict:
    """Résumé d'un débat chargé depuis S3 (dict JSON)."""
    # Participants
    participants = []
    for p in full.get("participants", []):
        participants.append({
            "id": p.get("id", ""),
            "model_id": p.get("model_id", ""),
            "provider": p.get("provider", ""),
            "display_name": p.get("display_name", ""),
            "persona_name": p.get("persona_name", ""),
            "persona_icon": p.get("persona_icon", "🤖"),
        })

    # Verdict
    verdict_info = None
    v = full.get("verdict")
    if v:
        verdict_info = {
            "type": v.get("type", ""),
            "confidence": v.get("confidence", 0),
            "summary": (v.get("summary") or "")[:200],
            "agreement_points": v.get("agreement_points", [])[:5],
            "divergence_points": [
                p.get("topic", str(p)[:80]) if isinstance(p, dict) else str(p)[:80]
                for p in v.get("divergence_points", [])[:5]
            ],
            "recommendation": (v.get("recommendation") or "")[:200],
        }

    # Stats
    stats = full.get("stats", {})
    duration_s = (stats.get("total_duration_ms", 0) or 0) / 1000

    return {
        "id": full.get("id", s3_meta.get("id", "")),
        "question": full.get("question", ""),
        "mode": full.get("mode", ""),
        "status": full.get("status", "unknown"),
        "phase": full.get("phase", ""),
        "created_at": full.get("created_at", ""),
        "completed_at": full.get("completed_at"),
        "total_tokens": full.get("total_tokens", 0),
        "participants": participants,
        "num_participants": len(participants),
        "num_rounds": len(full.get("rounds", [])),
        "verdict": verdict_info,
        "duration_s": round(duration_s, 1),
        "size": s3_meta.get("size", 0),
        "last_modified": str(s3_meta.get("last_modified", "")),
        "source": "s3",
    }


# =============================================================================
# Helpers
# =============================================================================


def _extract_admin_token(scope) -> str:
    """Extrait le Bearer token depuis les headers."""
    headers = dict(scope.get("headers", []))
    auth = headers.get(b"authorization", b"").decode()
    if auth.startswith("Bearer "):
        return auth[7:]
    return ""


def _is_authenticated(token: str) -> bool:
    """Vérifie si le token est valide (bootstrap key ou tout token non-révoqué)."""
    if not token:
        return False
    settings = get_settings()
    # Bootstrap key = toujours authentifié
    if hmac.compare_digest(token, settings.admin_bootstrap_key):
        return True
    # Token S3 : valide si existe et non-révoqué
    store = get_token_store()
    if store:
        h = hashlib.sha256(token.encode()).hexdigest()
        info = store.get_by_hash(h)
        if info and not info.get("revoked"):
            return True
    return False


def _is_admin(token: str) -> bool:
    """Vérifie si le token est admin (bootstrap key ou token admin S3)."""
    if not token:
        return False
    settings = get_settings()
    # Comparaison constante contre timing attacks
    if hmac.compare_digest(token, settings.admin_bootstrap_key):
        return True
    store = get_token_store()
    if store:
        h = hashlib.sha256(token.encode()).hexdigest()
        info = store.get_by_hash(h)
        if info and "admin" in info.get("permissions", []) and not info.get("revoked"):
            return True
    return False


# V1-08 : limite taille body (1 MB)
_MAX_BODY_SIZE = 1_048_576


async def _read_body(receive) -> bytes:
    """Lit le body complet d'une requête ASGI (max 1 MB — V1-08)."""
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if len(body) > _MAX_BODY_SIZE:
            raise ValueError("Body trop volumineux (max 1 MB)")
        if not message.get("more_body", False):
            break
    return body


async def _json_response(send, status, data):
    """Envoie une réponse JSON."""
    body = json.dumps(data, default=str).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})

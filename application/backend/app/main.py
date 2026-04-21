"""
AdviceRoom — Point d'entrée principal.

Assemble la pile de 5 middlewares ASGI Cloud Temple :
    LoggingMiddleware → AdminMiddleware → HealthCheckMiddleware → AuthMiddleware → FastAPI+FastMCP

Architecture hybride : FastAPI pour les routes REST (débats, providers, export)
+ FastMCP pour les outils MCP (agents IA) + Admin pour la console web.

Ref: starter-kit/README.md §2 (Architecture — La règle des 3 couches + 5 middlewares)
"""
import sys
import json
import unicodedata
from pathlib import Path

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from .config.settings import get_settings
from .routers.debates import router as debates_router
from .routers.providers import router as providers_router

# =============================================================================
# Settings
# =============================================================================

settings = get_settings()

# =============================================================================
# FastMCP instance (outils MCP pour les agents IA)
# =============================================================================

mcp = FastMCP(
    name="adviceroom",
    host=settings.backend_host,
    port=settings.backend_port,
)

# Importer les outils MCP (ils s'auto-enregistrent via @mcp.tool())
from .mcp.tools import register_tools  # noqa: E402
register_tools(mcp)

# =============================================================================
# FastAPI instance (routes REST pour la web UI + API)
# =============================================================================

_version = "dev"
_vf = Path(__file__).parent.parent / "VERSION"
if _vf.exists():
    _version = _vf.read_text().strip()

fastapi_app = FastAPI(
    title="AdviceRoom",
    version=_version,
    docs_url=None,  # Pas de Swagger en prod
    redoc_url=None,
)

# Routes REST
fastapi_app.include_router(debates_router, prefix="/api/v1")
fastapi_app.include_router(providers_router, prefix="/api/v1")

# Monter FastMCP sur /mcp
fastapi_app.mount("/mcp", mcp.streamable_http_app())


# =============================================================================
# HealthCheckMiddleware — /health, /healthz, /ready (sans auth)
# =============================================================================

class HealthCheckMiddleware:
    """Intercepte les health checks AVANT toute auth."""

    HEALTH_PATHS = {"/health", "/healthz", "/ready"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") in self.HEALTH_PATHS:
            body = json.dumps({
                "status": "ok",
                "version": _version,
                "service": "adviceroom",
            }).encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


# =============================================================================
# Assemblage ASGI — Chaîne de 5 middlewares (pattern Cloud Temple)
# =============================================================================

def create_app():
    """
    Crée l'application ASGI complète avec les middlewares.

    Pile d'exécution (ext → int) :
        LoggingMiddleware → AdminMiddleware → HealthCheckMiddleware → AuthMiddleware → FastAPI+FastMCP

    FastAPI est l'innermost app (gère /api/v1/* et /mcp).
    Les middlewares interceptent /admin, /health, et injectent l'auth.
    """
    from .auth.middleware import AuthMiddleware, LoggingMiddleware
    from .admin.middleware import AdminMiddleware
    from .auth.token_store import init_token_store

    # Initialiser le Token Store S3 (doit être fait AVANT le premier request)
    init_token_store()

    # Initialiser le LLM Router (charge les modèles depuis llm_models.yaml)
    from .services.llm.router import init_llm_router
    try:
        init_llm_router()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"⚠ LLM Router init échoué : {e}")

    # L'app de base = FastAPI (qui inclut les routes REST + le mount MCP)
    app = fastapi_app

    # Empiler les middlewares (dernier ajouté = premier exécuté)
    app = AuthMiddleware(app)                    # Auth Bearer + ContextVar
    app = HealthCheckMiddleware(app)             # /health, /healthz, /ready
    app = AdminMiddleware(app, mcp)              # /admin (console web CT)
    app = LoggingMiddleware(app)                 # Logging + ring buffer (outermost)

    return app


# =============================================================================
# Bannière de démarrage (dynamique)
# =============================================================================

def _display_width(text: str) -> int:
    """Largeur d'affichage terminal."""
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)


def _build_banner() -> str:
    """Bannière avec liste dynamique des outils MCP."""
    tools_list = mcp._tool_manager.list_tools()

    W = 56
    IW = W - 2

    top    = "╔" + "═" * IW + "╗"
    sep    = "╠" + "═" * IW + "╣"
    bottom = "╚" + "═" * IW + "╝"
    empty  = "║" + " " * IW + "║"

    def pad(text: str) -> str:
        dw = _display_width(text)
        return "║" + text + " " * max(0, IW - dw) + "║"

    def center(text: str) -> str:
        dw = _display_width(text)
        total_pad = IW - dw
        left = total_pad // 2
        right = total_pad - left
        return "║" + " " * left + text + " " * right + "║"

    lines = [top]
    lines.append(center("🏛️  AdviceRoom — Débats Multi-LLM"))
    lines.append(center(f"v{_version}"))
    lines.append(sep)
    lines.append(empty)

    lines.append(pad(f"  🔧 Outils MCP ({len(tools_list)}) :"))
    for t in tools_list:
        lines.append(pad(f"     • {t.name}"))
    lines.append(empty)

    hp = f"{settings.backend_host}:{settings.backend_port}"
    lines.append(pad(f"  🌐 http://{hp}"))
    lines.append(pad(f"  🔗 http://{hp}/mcp"))
    lines.append(pad(f"  📡 http://{hp}/api/v1"))
    lines.append(pad(f"  🛠️  http://{hp}/admin"))
    lines.append(empty)
    lines.append(bottom)

    return "\n".join(lines)


# =============================================================================
# Application ASGI (pour uvicorn)
# =============================================================================

# L'objet `app` est utilisé par uvicorn dans le Dockerfile :
#   uvicorn app.main:app --host 0.0.0.0 --port 8000
app = create_app()


# =============================================================================
# Point d'entrée direct (python -m app)
# =============================================================================

def main():
    """Démarre le serveur AdviceRoom."""
    import uvicorn

    # Bannière
    print("\n" + _build_banner() + "\n", file=sys.stderr)

    # Warning bootstrap key par défaut
    if settings.admin_bootstrap_key == "changeme-in-production":
        print(
            "⚠️  ATTENTION : ADMIN_BOOTSTRAP_KEY est la valeur par défaut !\n"
            "   → Changez-la dans .env AVANT tout déploiement en production.\n",
            file=sys.stderr,
        )

    # V1-13 : init_token_store() supprimé ici (déjà fait dans create_app())

    uvicorn.run(
        app,
        host=settings.backend_host,
        port=settings.backend_port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()

"""
AdviceRoom — Point d'entrée principal.

Assemble la pile de 5 middlewares ASGI Cloud Temple :
    LoggingMiddleware → AdminMiddleware → HealthCheckMiddleware → AuthMiddleware → FastAPI+MCPServer

Architecture hybride : FastAPI pour les routes REST (débats, providers, export)
+ MCPServer pour les outils MCP (agents IA) + Admin pour la console web.

Ref: starter-kit/README.md §2 (Architecture — La règle des 3 couches + 5 middlewares)
"""
import sys
import json
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer

from .config.settings import get_settings
from .routers.debates import router as debates_router
from .routers.providers import router as providers_router

# =============================================================================
# Settings
# =============================================================================

settings = get_settings()

# =============================================================================
# MCPServer instance (outils MCP pour les agents IA)
# =============================================================================

# SDK MCP v2 : la classe FastMCP a été renommée MCPServer, et les paramètres de
# transport (host, port, streamable_http_path) ne sont plus acceptés par le
# constructeur. Ils sont désormais passés à streamable_http_app() — voir
# _new_streamable_http_app() ci-dessous.
mcp = MCPServer(name="adviceroom")

# Importer les outils MCP (ils s'auto-enregistrent via @mcp.tool())
from .mcp.tools import register_tools  # noqa: E402
register_tools(mcp)

class StreamableHTTPAppProxy:
    """
    Stable mounted ASGI app that can swap its MCP sub-app at startup.

    A StreamableHTTPSessionManager can only be run once. Rebuilding the
    sub-app for each parent lifespan keeps production startup correct and
    avoids brittle ASGI restart/test-client cycles.
    """

    def __init__(self, app_factory):
        self._app_factory = app_factory
        self._app = app_factory()

    def reset(self):
        self._app = self._app_factory()
        return self._app

    async def __call__(self, scope, receive, send):
        await self._app(scope, receive, send)


def _new_streamable_http_app():
    # SDK MCP v2 : streamable_http_app() construit un NOUVEAU
    # StreamableHTTPSessionManager à chaque appel et l'attache au lifespan du
    # Starlette retourné. Le contournement v1 — remettre le manager mis en cache
    # à None avant de reconstruire l'app — n'a donc plus d'objet.
    #
    # streamable_http_path="/" évite le double préfixe /mcp/mcp : le défaut du
    # SDK est "/mcp", et l'app est déjà montée sur "/mcp" plus bas.
    return mcp.streamable_http_app(
        streamable_http_path="/",
        host=settings.backend_host,
    )


# The streamable HTTP app owns a lifespan that initializes the session
# manager task group. Starlette does not run mounted sub-app lifespans, so the
# parent FastAPI app must enter it explicitly.
mcp_app = StreamableHTTPAppProxy(_new_streamable_http_app)


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def _mcp_lifespan_context():
    reset = getattr(mcp_app, "reset", None)
    streamable_app = reset() if reset is not None else mcp_app

    lifespan_context = getattr(streamable_app, "lifespan", None)
    if lifespan_context is not None:
        return lifespan_context(streamable_app)

    router = getattr(streamable_app, "router", None)
    lifespan_context = getattr(router, "lifespan_context", None)
    if lifespan_context is not None:
        return lifespan_context(streamable_app)

    return _noop_lifespan(streamable_app)

# =============================================================================
# FastAPI instance (routes REST de compatibilité + MCP)
# =============================================================================

_version = "dev"
_vf = Path(__file__).parent.parent / "VERSION"
if _vf.exists():
    _version = _vf.read_text().strip()


@asynccontextmanager
async def lifespan(app):
    async with _mcp_lifespan_context():
        yield


fastapi_app = FastAPI(
    title="AdviceRoom",
    version=_version,
    docs_url=None,  # Pas de Swagger en prod
    redoc_url=None,
    lifespan=lifespan,
)

# Routes REST
fastapi_app.include_router(debates_router, prefix="/api/v1")
fastapi_app.include_router(providers_router, prefix="/api/v1")

# Monter l'app MCP sur /mcp
# Le streamable_http_path="/" passé à streamable_http_app() ci-dessus
# évite le double préfixe /mcp/mcp (le défaut du SDK est "/mcp")
fastapi_app.mount("/mcp", mcp_app)


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
        LoggingMiddleware → AdminMiddleware → HealthCheckMiddleware → AuthMiddleware → FastAPI+MCPServer

    FastAPI est l'innermost app (gère /api/v1/* et /mcp).
    Les middlewares interceptent /admin, /health, et injectent l'auth.
    """
    from .auth.middleware import AuthMiddleware, LoggingMiddleware
    from .admin.middleware import AdminMiddleware
    from .auth.token_store import init_token_store

    # Avertissement bootstrap admin. Placé ICI et non dans main() : le
    # Dockerfile démarre `uvicorn app.main:app`, donc main() n'est jamais
    # exécuté en production et l'avertissement qui s'y trouvait ne s'affichait
    # jamais là où il comptait.
    if not settings.bootstrap_enabled:
        import logging
        logging.getLogger(__name__).warning(
            "⚠ ADMIN_BOOTSTRAP_KEY non définie — bootstrap admin DÉSACTIVÉ. "
            "L'accès admin repose uniquement sur les tokens du Token Store S3."
        )

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

    # L'avertissement sur le bootstrap admin est émis par create_app(), qui est
    # le seul chemin commun aux deux modes de démarrage (uvicorn et python -m app).

    # V1-13 : init_token_store() supprimé ici (déjà fait dans create_app())

    uvicorn.run(
        app,
        host=settings.backend_host,
        port=settings.backend_port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()

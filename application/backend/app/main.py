"""
AdviceRoom — FastAPI Entry Point.

Sert à la fois :
- L'API REST sous /api/v1/ (pour le frontend web)
- Le serveur MCP sous /mcp (pour les agents IA)
- Le health check sous /health (pour le WAF/load balancer)

Architecture : un seul processus, deux interfaces (§4.2.5).
Le Debate Engine est partagé entre REST et MCP — pas d'indirection réseau.

Ref: DESIGN/architecture.md §4.2.5
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config.settings import get_settings
from .services.llm.router import init_llm_router

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown du serveur."""
    # --- Startup ---
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(f"🚀 AdviceRoom v{settings.version} démarrage...")

    # Initialiser le LLM Router
    llm_router = init_llm_router()
    logger.info("✓ LLM Router initialisé")

    # Monter le serveur MCP (après le démarrage du LLM Router)
    from .mcp.tools import setup_mcp
    setup_mcp(app)
    logger.info("✓ MCP Server monté sous /mcp")

    logger.info(f"✓ AdviceRoom prêt sur {settings.backend_host}:{settings.backend_port}")

    yield

    # --- Shutdown ---
    logger.info("👋 AdviceRoom arrêt...")


app = FastAPI(
    title="AdviceRoom",
    description="Débats structurés entre LLMs hétérogènes",
    version=settings.version,
    lifespan=lifespan,
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers REST ---
from .routers.debates import router as debates_router
from .routers.providers import router as providers_router

app.include_router(debates_router, prefix="/api/v1", tags=["debates"])
app.include_router(providers_router, prefix="/api/v1", tags=["providers"])


# --- Health Check ---
@app.get("/health")
async def health():
    """Health check endpoint (pas d'auth, pour le WAF)."""
    return {
        "status": "ok",
        "version": settings.version,
        "service": "adviceroom",
    }


# --- Info ---
@app.get("/api/v1/info")
async def info():
    """Informations sur le service."""
    from .services.llm.router import get_llm_router

    llm_router = get_llm_router()
    return {
        "service": "adviceroom",
        "version": settings.version,
        "llm_router": llm_router.get_status() if llm_router.loaded else {"loaded": False},
    }

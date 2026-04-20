# AdviceRoom

> Débats structurés entre LLMs hétérogènes — Serveur MCP + Application Web

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Vision

AdviceRoom orchestre des **débats structurés entre LLMs hétérogènes**. L'utilisateur pose une question complexe, invite jusqu'à 5 LLMs (mix SecNumCloud + cloud public), et ils débattent en temps réel selon un protocole fondé sur la recherche académique, jusqu'à convergence ou divergence structurée.

**Produit interne [Cloud Temple](https://www.cloud-temple.com)**, publié en open-source Apache 2.0.

## Fonctionnalités

- 🎯 **Débats multi-LLM** : jusqu'à 5 participants + 1 synthétiseur
- 🛡️ **Multi-provider** : LLMaaS SecNumCloud, OpenAI, Anthropic, Google Gemini
- 🔬 **Protocole académique** : anti-ancrage, anti-conformité, arrêt adaptatif
- 🤖 **Double interface** : MCP (agents IA) + Web UI (humains)
- ⚡ **Streaming temps réel** : NDJSON avec événements granulaires
- 🧑‍💬 **User-in-the-loop** : les LLMs peuvent poser des questions à l'utilisateur

## Architecture

```
WAF (Caddy+Coraza)
  └─ Backend (FastAPI + FastMCP)
       ├─ API REST /api/v1/ (Web UI)
       ├─ MCP /mcp (Agents IA)
       └─ Debate Engine
            ├─ LLM Router (multi-provider)
            ├─ DebateOrchestrator (3 phases)
            ├─ StabilityDetector
            └─ VerdictSynthesizer
  └─ Frontend (React 18 + Vite)
  └─ Auth (JWT RS256)
  └─ Redis (cache JWKS)
```

## Démarrage rapide

```bash
# Cloner
git clone https://github.com/cloudtemple/mcp-adviceroom.git
cd mcp-adviceroom

# Configurer
cp .env.example .env
# Éditer .env avec vos clés API

# Lancer
docker compose up -d

# Vérifier
curl http://localhost:8000/health
```

## Développement

```bash
cd application/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Documentation

- [Architecture v1.0](DESIGN/architecture.md) — Document de référence complet (17 sections)

## Licence

Apache 2.0 — voir [LICENSE](LICENSE)

---

*Cloud Temple — Cloud souverain français SecNumCloud*

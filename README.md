# AdviceRoom

> Débats structurés entre LLMs hétérogènes — Serveur MCP + Application Web

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-135%2F135-brightgreen)]()
[![Version](https://img.shields.io/badge/Version-0.1.3-blue)]()

[🇬🇧 English version](README.en.md)

---

## Vision

AdviceRoom orchestre des **débats structurés entre LLMs hétérogènes**. L'utilisateur pose une question complexe, invite jusqu'à 5 LLMs (mix SecNumCloud + cloud public), et ils débattent en temps réel selon un protocole fondé sur la recherche académique (9 papiers, 7 principes), jusqu'à convergence ou divergence structurée.

**Produit interne [Cloud Temple](https://www.cloud-temple.com)**, publié en open-source Apache 2.0.

## Fonctionnalités

|         | Fonctionnalité           | Description                                                  |
| ------- | ------------------------ | ------------------------------------------------------------ |
| 🎯     | **Débats multi-LLM**     | Jusqu'à 5 participants + 1 synthétiseur dédié                |
| 🛡️   | **Multi-provider**       | LLMaaS SecNumCloud, OpenAI, Anthropic, Google Gemini         |
| 🔬     | **Protocole académique** | Anti-ancrage, anti-conformité, arrêt adaptatif par stabilité |
| 🤖     | **Double interface**     | MCP (agents IA) + Web UI (humains)                           |
| ⚡      | **Streaming temps réel** | NDJSON avec événements granulaires                           |
| 🧑‍💬 | **User-in-the-loop**     | Les LLMs peuvent poser des questions à l'utilisateur         |
| 🔧     | **Outils LLM**           | web_search, calculator, datetime via MCP Tools               |
| 🎭     | **Personas**             | 5 rôles (Pragmatique, Avocat du diable, Analyste risques…)   |
| 🔀     | **3 modes de débat**     | Standard (Within-Round), Parallel (Cross-Round, défaut), Blitz (~1 min) |
| 📊     | **Dashboard admin**      | Monitoring live, graphes confiance/stabilité, export HTML    |
| 🔒     | **Sécurité**             | Auth Bearer, WAF Caddy+Coraza, audit V1.1 (19/22 corrigés)   |

## Architecture

```
WAF (Caddy + Coraza)
  └── Backend (FastAPI + FastMCP) — Un seul processus
       ├── API REST /api/v1/     (Web UI, CLI)
       ├── MCP /mcp              (Agents IA)
       ├── Admin /admin          (Console web SPA)
       └── Debate Engine
            ├── LLM Router       (4 providers, 6 modèles)
            ├── DebateOrchestrator (3 phases : OPENING → DEBATE → VERDICT)
            ├── StabilityDetector (arrêt adaptatif)
            ├── VerdictSynthesizer (consensus / partiel / dissensus)
            └── MCP Tools Bridge  (web_search, calc, datetime)
  └── Frontend (React 18 + Vite + Tailwind)
  └── Redis (cache)
```

## Fondements académiques

L'architecture d'AdviceRoom s'appuie sur **9 papiers de recherche** (2024-2025) qui identifient les problèmes fondamentaux du débat multi-LLM et proposent des solutions validées expérimentalement.

### Le problème central : le conformisme des LLMs

Les LLMs tendent à converger vers la position majoritaire, même quand elle est incorrecte [[5]](#références). Ce biais majoritaire est le **défi #1** du débat multi-LLM — le vote majoritaire seul explique l'essentiel des gains attribués au débat. De plus, quand les modèles partagent des données d'entraînement corrélées, le débat converge vers une "echo chamber" [[1]](#références).

**AdviceRoom résout ce problème** avec un protocole qui force la diversité à chaque étape.

### 7 principes extraits de la recherche

| # | Principe | Mécanisme | Papiers |
|---|----------|-----------|---------|
| 1 | **Anti-ancrage** | Positions initiales en parallèle (`asyncio.gather`), pas séquentielles | [[1]](#références) |
| 2 | **Anti-conformité** | Challenge obligatoire ≥1 argument par round + validation post-tour + retry | [[2]](#références), [[5]](#références) |
| 3 | **Personas diversifiées** | 5 rôles attribués automatiquement (Pragmatique, Avocat du diable, Analyste risques, Expert technique, Innovateur) | [[7]](#références) |
| 4 | **Pas de consensus forcé** | Le dissensus structuré est un résultat valide, pas un échec | [[2]](#références), [[6]](#références) |
| 5 | **Arrêt adaptatif** | 3 métriques de stabilité (position delta, confidence delta, argument novelty) | [[3]](#références) |
| 6 | **Verdict par trajectoire** | Analyse du débat entier par un synthétiseur dédié, pas du dernier round | [[2]](#références) |
| 7 | **Outils pour tous** | Chaque LLM a accès aux mêmes outils (web_search, calc, datetime) | [[9]](#références) |

### Protocole en 3 phases

```
Phase 1: OPENING (parallèle)
  Tous les LLMs produisent leur position initiale EN MÊME TEMPS
  → Évite le biais d'ancrage [1]
  Chaque LLM reçoit un persona [7] + accès aux outils [9]

Phase 2: DEBATE (round-robin, max N rounds)
  Chaque LLM à son tour :
    1. Voit les positions des autres
    2. DOIT challenger ≥1 argument (anti-conformité [2, 5])
    3. Peut utiliser des outils (recherche, calcul)
    4. Peut poser une question à l'utilisateur → PAUSE
    5. Met à jour sa position + confidence
  → Détection de stabilité après chaque round [3]
  → Si stable → Phase 3

Phase 3: VERDICT (LLM synthétiseur dédié)
  Analyse la trajectoire ENTIÈRE du débat [2]
  Produit : consensus | consensus_partiel | dissensus [6]
  + points d'accord/divergence + recommandation + confidence
```

### 3 modes de débat [[4]](#références)

| Mode | Protocole | Visibilité | Durée typique | Usage |
|------|-----------|------------|---------------|-------|
| ⚙️ **standard** | Within-Round (WR) | Chaque agent voit les tours **du même round** | 15-25 min | Interaction maximale, peer-referencing |
| 🔄 **parallel** *(défaut)* | Cross-Round (CR) | Agents ne voient que les **rounds précédents** | 3-8 min | Compromis vitesse/qualité (3× plus rapide) |
| ⚡ **blitz** | No-Interaction + 1 round | Opening parallèle + 1 round de réaction croisée | 1-2 min | Réponse rapide, exploration initiale |

### Références

| # | Papier | Venue | Contribution clé |
|---|--------|-------|-----------------|
| [1] | **Multi-LLM Debate: Framework, Principals, and Interventions** — Estornell & Liu | NeurIPS 2024 | Framework bayésien, echo chamber theorem, justifie les LLMs hétérogènes |
| [2] | **Free-MAD: Consensus-Free Multi-Agent Debate** | arXiv 2509.11035 | Paradigme consensus-free, verdict par trajectoire, anti-conformité |
| [3] | **Multi-Agent Debate with Adaptive Stability Detection** | arXiv 2510.12697 | Arrêt adaptatif Beta-Binomial + KS test |
| [4] | **The Impact of Multi-Agent Debate Protocols on Debate Quality** | arXiv 2603.28813 | Comparaison protocoles (WR, CR, RA-CR), trade-off interaction/convergence |
| [5] | **Can LLM Agents Really Debate?** | arXiv 2511.07784 | Preuve du biais conformiste, défi #1 du débat multi-LLM |
| [6] | **Consensus-Diversity Trade-off in Adaptive Multi-Agent Systems** | EMNLP 2025 | Le consensus implicite surpasse l'explicite, diversité = robustesse |
| [7] | **Debate-to-Write: Persona-Driven Multi-Agent Framework** | COLING 2025 | Personas diversifiées maximisent qualité et persuasion des arguments |
| [8] | **Society of Thought** | arXiv 2601.10825 | Les LLMs simulent déjà un débat interne — valide le concept |
| [9] | **Tool-MAD: Multi-Agent Debate with Tool Augmentation** | arXiv 2601.04742 | Outils hétérogènes pendant le débat, +5.5% précision fact-checking |

> Les papiers sont disponibles dans [`DESIGN/research/`](DESIGN/research/) avec un [index détaillé](DESIGN/research/README.md).

## Démarrage rapide

### Prérequis

- Docker & Docker Compose
- Au moins 2 clés API LLM parmi : LLMaaS, OpenAI, Anthropic, Google

### Installation

```bash
# Cloner
git clone https://github.com/cloud-temple/mcp-adviceroom.git
cd mcp-adviceroom

# Configurer
cp .env.example .env
# Éditer .env avec vos clés API LLM et S3

# Lancer
docker compose up -d

# Vérifier
docker compose exec backend curl -sf http://localhost:8000/health
```

### Développement local

```bash
cd application/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Tests
pytest tests/ -v
```

## CLI

La CLI est alignée 1:1 avec l'API admin :

```bash
# Variables d'environnement
export ADVICEROOM_URL=http://localhost:8000
export ADVICEROOM_TOKEN=votre-token

# Commandes
python scripts/adviceroom_cli.py health          # État du serveur
python scripts/adviceroom_cli.py models          # Modèles LLM disponibles
python scripts/adviceroom_cli.py debate list     # Lister les débats
python scripts/adviceroom_cli.py debate start "Votre question" -m gpt-52,claude-opus-46
python scripts/adviceroom_cli.py shell           # Shell interactif
```

## Modèles LLM supportés

| Provider              | Modèle          | Type         | Statut |
| --------------------- | --------------- | ------------ | ------ |
| LLMaaS (Cloud Temple) | GPT-OSS 120B    | SecNumCloud  | ✅     |
| LLMaaS (Cloud Temple) | Qwen 3.5 27B    | SecNumCloud  | ✅     |
| LLMaaS (Cloud Temple) | Gemma 4 31B     | SecNumCloud  | ✅     |
| OpenAI                | GPT-5.2         | Cloud public | ✅     |
| Anthropic             | Claude Opus 4-6 | Cloud public | ✅     |
| Google                | Gemini 3.1 Pro  | Cloud public | ✅     |

## Sécurité

- **Audit V1.1** : 22 findings identifiés, 19 corrigés, 2 partiels mineurs, 0 ouvert ([rapport](DESIGN/SECURITY_AUDIT_V1.md))
- **Auth** : Bearer Token + ContextVar sur toutes les routes REST et MCP
- **Validation** : UUID regex, longueurs, bornes, whitelists
- **Infra** : Dockerfile non-root (UID 1001), ports internes only, HSTS, security headers
- **WAF** : Caddy + Coraza activé (OWASP CRS v4.8.0, `SecRuleEngine On`)
- **Supply chain** : fastmcp≥3.2.0 (4 CVE corrigées), requirements.lock disponible

## Documentation

- [Architecture v1.1](DESIGN/architecture.md) — Document de référence (17 sections)
- [Audit sécurité V1.1](DESIGN/SECURITY_AUDIT_V1.md) — Rapport complet (22 findings, 19 corrigés)
- [Papiers de recherche](DESIGN/research/README.md) — 9 papiers fondateurs

## Structure du projet

```
mcp-adviceroom/
├── application/
│   ├── backend/           # FastAPI + FastMCP
│   │   ├── app/
│   │   │   ├── admin/     # Console admin (middleware + API)
│   │   │   ├── auth/      # Auth Bearer (middleware + context + token store)
│   │   │   ├── config/    # YAML configs (debate, llm_models, personas, prompts, tools)
│   │   │   ├── mcp/       # 6 outils MCP
│   │   │   ├── routers/   # REST API (debates, providers)
│   │   │   ├── services/  # Debate engine, LLM providers, S3 storage, MCP Tools
│   │   │   └── static/    # Admin SPA (admin.html)
│   │   └── tests/         # 135 tests (pytest)
│   └── frontend/          # React 18 + Vite + Tailwind
├── scripts/
│   ├── adviceroom_cli.py  # Point d'entrée CLI
│   ├── cli/               # Module CLI (client, commands, display, shell)
│   └── test_llm_providers.py  # Test connectivité providers
├── waf/                   # Caddy + Coraza
├── DESIGN/                # Architecture, audit sécurité, recherche académique
├── docker-compose.yml
└── .env.example
```

## Licence

[Apache 2.0](LICENSE) — Cloud Temple

---

*[Cloud Temple](https://www.cloud-temple.com) — Cloud souverain français SecNumCloud*

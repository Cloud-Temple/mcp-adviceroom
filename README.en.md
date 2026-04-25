# AdviceRoom

> Structured debates between heterogeneous LLMs — MCP Server + Web Application

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-135%2F135-brightgreen)]()
[![Version](https://img.shields.io/badge/Version-0.1.6-blue)]()

[🇫🇷 Version française](README.md)

---

## Vision

AdviceRoom orchestrates **structured debates between heterogeneous LLMs**. Users ask complex questions, invite up to 5 LLMs (mix of SecNumCloud sovereign + public cloud), and they debate in real-time following a research-backed protocol (9 papers, 7 principles), until convergence or structured divergence.

**Internal product by [Cloud Temple](https://www.cloud-temple.com)**, published as open-source under Apache 2.0.

## Features

|         | Feature                 | Description                                                  |
| ------- | ----------------------- | ------------------------------------------------------------ |
| 🎯     | **Multi-LLM debates**   | Up to 5 participants + 1 dedicated synthesizer               |
| 🛡️   | **Multi-provider**      | LLMaaS SecNumCloud, OpenAI, Anthropic, Google Gemini         |
| 🔬     | **Academic protocol**   | Anti-anchoring, anti-conformity, adaptive stability stopping |
| 🤖     | **Dual interface**      | MCP (AI agents) + Web UI (humans)                            |
| ⚡      | **Real-time streaming** | NDJSON with granular events                                  |
| 🧑‍💬 | **User-in-the-loop**    | LLMs can ask questions to the user mid-debate                |
| 🔧     | **LLM tools**           | web_search, calculator, datetime via MCP Tools               |
| 🎭     | **Personas**            | 5 roles (Pragmatic, Devil's advocate, Risk analyst…)         |
| 🔀     | **3 debate modes**      | Standard (Within-Round), Parallel (Cross-Round, default), Blitz (~1 min) |
| 📊     | **Admin dashboard**     | Live monitoring, confidence/stability charts, HTML export    |
| 🔒     | **Security**            | Bearer auth, WAF Caddy+Coraza, V1.1 audit (19/22 fixed)      |

## Architecture

```
WAF (Caddy + Coraza)
  └── Backend (FastAPI + FastMCP) — Single process
       ├── REST API /api/v1/     (Web UI, CLI)
       ├── MCP /mcp              (AI Agents)
       ├── Admin /admin          (Web console SPA)
       └── Debate Engine
            ├── LLM Router       (4 providers, 6 models)
            ├── DebateOrchestrator (3 phases: OPENING → DEBATE → VERDICT)
            ├── StabilityDetector (adaptive stopping)
            ├── VerdictSynthesizer (consensus / partial / dissensus)
            └── MCP Tools Bridge  (web_search, calc, datetime)
  └── Frontend (React 18 + Vite + Tailwind)
  └── Redis (cache)
```

## Academic Foundations

AdviceRoom's architecture builds on **9 research papers** (2024-2025) that identify the fundamental problems of multi-LLM debate and propose experimentally validated solutions.

### The core problem: LLM conformism

LLMs tend to converge toward the majority position, even when it's incorrect [[5]](#references). This majority bias is the **#1 challenge** of multi-LLM debate — majority voting alone explains most of the performance gains attributed to debate. Furthermore, when models share correlated training data, debate converges into an "echo chamber" [[1]](#references).

**AdviceRoom solves this** with a protocol that forces diversity at every step.

### 7 principles from the research

| #   | Principle                    | Mechanism                                                                                      | Papers                                 |
| --- | ---------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------- |
| 1   | **Anti-anchoring**           | Initial positions generated in parallel (`asyncio.gather`), not sequentially                   | [[1]](#references)                     |
| 2   | **Anti-conformity**          | Mandatory challenge ≥1 argument per round + post-turn validation + retry                       | [[2]](#references), [[5]](#references) |
| 3   | **Diverse personas**         | 5 roles auto-assigned (Pragmatic, Devil's advocate, Risk analyst, Technical expert, Innovator) | [[7]](#references)                     |
| 4   | **No forced consensus**      | Structured dissensus is a valid outcome, not a failure                                         | [[2]](#references), [[6]](#references) |
| 5   | **Adaptive stopping**        | 3 stability metrics (position delta, confidence delta, argument novelty)                       | [[3]](#references)                     |
| 6   | **Trajectory-based verdict** | Full debate analysis by a dedicated synthesizer, not just the last round                       | [[2]](#references)                     |
| 7   | **Tools for all**            | Every LLM has access to the same tools (web_search, calc, datetime)                            | [[9]](#references)                     |

### 3-phase protocol

```
Phase 1: OPENING (parallel)
  All LLMs produce their initial position AT THE SAME TIME
  → Avoids anchoring bias [1]
  Each LLM receives a persona [7] + tool access [9]

Phase 2: DEBATE (round-robin, max N rounds)
  Each LLM in turn:
    1. Sees other positions
    2. MUST challenge ≥1 argument (anti-conformity [2, 5])
    3. Can use tools (search, calculation)
    4. Can ask the user a question → PAUSE
    5. Updates position + confidence
  → Stability detection after each round [3]
  → If stable → Phase 3

Phase 3: VERDICT (dedicated synthesizer LLM)
  Analyzes the ENTIRE debate trajectory [2]
  Produces: consensus | partial_consensus | dissensus [6]
  + agreement/divergence points + recommendation + confidence
```

### 3 debate modes [[4]](#references)

| Mode | Protocol | Visibility | Typical duration | Use case |
|------|----------|------------|-----------------|----------|
| ⚙️ **standard** | Within-Round (WR) | Each agent sees turns **from the same round** | 15-25 min | Maximum interaction, peer-referencing |
| 🔄 **parallel** *(default)* | Cross-Round (CR) | Agents only see **previous rounds** | 3-8 min | Speed/quality trade-off (3× faster) |
| ⚡ **blitz** | No-Interaction + 1 round | Parallel opening + 1 cross-reaction round | 1-2 min | Quick answer, initial exploration |

### References

| #   | Paper                                                                            | Venue            | Key contribution                                                       |
| --- | -------------------------------------------------------------------------------- | ---------------- | ---------------------------------------------------------------------- |
| [1] | **Multi-LLM Debate: Framework, Principals, and Interventions** — Estornell & Liu | NeurIPS 2024     | Bayesian framework, echo chamber theorem, justifies heterogeneous LLMs |
| [2] | **Free-MAD: Consensus-Free Multi-Agent Debate**                                  | arXiv 2509.11035 | Consensus-free paradigm, trajectory-based verdict, anti-conformity     |
| [3] | **Multi-Agent Debate with Adaptive Stability Detection**                         | arXiv 2510.12697 | Adaptive stopping via Beta-Binomial + KS test                          |
| [4] | **The Impact of Multi-Agent Debate Protocols on Debate Quality**                 | arXiv 2603.28813 | Protocol comparison (WR, CR, RA-CR), interaction/convergence trade-off |
| [5] | **Can LLM Agents Really Debate?**                                                | arXiv 2511.07784 | Proof of conformist bias, #1 challenge of multi-LLM debate             |
| [6] | **Consensus-Diversity Trade-off in Adaptive Multi-Agent Systems**                | EMNLP 2025       | Implicit consensus outperforms explicit, diversity = robustness        |
| [7] | **Debate-to-Write: Persona-Driven Multi-Agent Framework**                        | COLING 2025      | Diverse personas maximize argument quality and persuasiveness          |
| [8] | **Society of Thought**                                                           | arXiv 2601.10825 | LLMs already simulate internal debates — validates the concept         |
| [9] | **Tool-MAD: Multi-Agent Debate with Tool Augmentation**                          | arXiv 2601.04742 | Heterogeneous tools during debate, +5.5% fact-checking accuracy        |

> Papers are available in [`DESIGN/research/`](DESIGN/research/) with a [detailed index](DESIGN/research/README.md).

## Quick Start

### Prerequisites

- Docker & Docker Compose
- At least 2 LLM API keys from: LLMaaS, OpenAI, Anthropic, Google

### Installation

```bash
# Clone
git clone https://github.com/cloud-temple/mcp-adviceroom.git
cd mcp-adviceroom

# Configure
cp .env.example .env
# Edit .env with your LLM and S3 API keys

# Launch
docker compose up -d

# Verify
docker compose exec backend curl -sf http://localhost:8000/health
```

### Local Development

```bash
cd application/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Tests
pytest tests/ -v
```

## CLI

The CLI is aligned 1:1 with the admin API:

```bash
# Environment variables
export ADVICEROOM_URL=http://localhost:8000
export ADVICEROOM_TOKEN=your-token

# Commands
python scripts/adviceroom_cli.py health          # Server status
python scripts/adviceroom_cli.py models          # Available LLM models
python scripts/adviceroom_cli.py debate list     # List debates
python scripts/adviceroom_cli.py debate start "Your question" -m gpt-52,claude-opus-46
python scripts/adviceroom_cli.py shell           # Interactive shell
```

## Supported LLM Models

| Provider              | Model           | Type         | Status |
| --------------------- | --------------- | ------------ | ------ |
| LLMaaS (Cloud Temple) | GPT-OSS 120B    | SecNumCloud  | ✅     |
| LLMaaS (Cloud Temple) | Qwen 3.5 27B    | SecNumCloud  | ✅     |
| LLMaaS (Cloud Temple) | Gemma 4 31B     | SecNumCloud  | ✅     |
| OpenAI                | GPT-5.2         | Public cloud | ✅     |
| Anthropic             | Claude Opus 4-6 | Public cloud | ✅     |
| Google                | Gemini 3.1 Pro  | Public cloud | ✅     |

## Security

- **V1.1 audit**: 22 findings identified, 19 fixed, 2 minor partials, 0 open ([report](DESIGN/SECURITY_AUDIT_V1.md))
- **Auth**: Bearer Token + ContextVar on all REST and MCP routes
- **Validation**: UUID regex, length limits, bounds, whitelists
- **Infra**: Non-root Dockerfile (UID 1001), internal ports only, HSTS, security headers
- **WAF**: Caddy + Coraza enabled (OWASP CRS v4.8.0, `SecRuleEngine On`)
- **Supply chain**: fastmcp≥3.2.0 (4 CVEs fixed), requirements.lock available

## Documentation

- [Architecture v1.1](DESIGN/architecture.md) — Reference document (17 sections)
- [Security Audit V1.1](DESIGN/SECURITY_AUDIT_V1.md) — Full report (22 findings, 19 fixed)
- [Research Papers](DESIGN/research/README.md) — 9 foundational papers

## Project Structure

```
mcp-adviceroom/
├── application/
│   ├── backend/           # FastAPI + FastMCP
│   │   ├── app/
│   │   │   ├── admin/     # Admin console (middleware + API)
│   │   │   ├── auth/      # Bearer auth (middleware + context + token store)
│   │   │   ├── config/    # YAML configs (debate, llm_models, personas, prompts, tools)
│   │   │   ├── mcp/       # 6 MCP tools
│   │   │   ├── routers/   # REST API (debates, providers)
│   │   │   ├── services/  # Debate engine, LLM providers, S3 storage, MCP Tools
│   │   │   └── static/    # Admin SPA (admin.html)
│   │   └── tests/         # 140 tests (pytest)
│   └── frontend/          # React 18 + Vite + Tailwind
├── scripts/
│   ├── adviceroom_cli.py  # CLI entry point
│   ├── cli/               # CLI module (client, commands, display, shell)
│   └── test_llm_providers.py  # Provider connectivity test
├── waf/                   # Caddy + Coraza
├── DESIGN/                # Architecture, security audit, academic research
├── docker-compose.yml
└── .env.example
```

## License

[Apache 2.0](LICENSE) — Cloud Temple

---

*[Cloud Temple](https://www.cloud-temple.com) — French sovereign cloud SecNumCloud*

# AdviceRoom

> Structured debates between heterogeneous LLMs — MCP Server + Web Application

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-244-brightgreen)]()
[![Version](https://img.shields.io/badge/Version-0.3.1-blue)]()

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
| 🤖     | **Dual interface**      | MCP (AI agents) + `/admin` console/CLI (humans)              |
| ⚡      | **Real-time streaming** | NDJSON with granular events                                  |
| 🧑‍💬 | **User-in-the-loop**    | LLMs can ask questions to the user mid-debate                |
| 🔧     | **LLM tools**           | web_search, calculator, datetime via MCP Tools               |
| 🎭     | **Personas**            | 5 roles (Pragmatic, Devil's advocate, Risk analyst…)         |
| 🔀     | **3 debate modes**      | Standard (Within-Round), Parallel (Cross-Round, default), Blitz (~1 min) |
| 📊     | **Admin dashboard**     | Live monitoring, confidence/stability charts, HTML export    |
| 🔒     | **Security**            | Bearer auth, owner isolation, rate limiting, WAF Caddy+Coraza |

## Architecture

```
WAF (Caddy + Coraza)
  └── Backend (FastAPI + MCP SDK v2) — Single process
       ├── Admin API /admin/api/ (Web console, CLI)
       ├── REST API /api/v1/     (REST compatibility/internal MCP)
       ├── MCP /mcp              (AI Agents)
       ├── Admin /admin          (Web console SPA)
       └── Debate Engine
            ├── LLM Router       (4 providers, 8 models)
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

**Use a virtual environment dedicated to this project**, created at the repository
root. A venv shared across projects eventually breaks them: when two projects
require incompatible versions of the same dependency, `pip` installs whichever was
requested last and the other silently stops working. AdviceRoom requires
`mcp>=2.1.1,<3`, a constraint other tools may not share.

```bash
# From the repository root — venv on Python 3.13 (production runs 3.12)
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r application/backend/requirements.txt
```

```bash
# Development server
cd application/backend
uvicorn app.main:app --reload --port 8000
```

```bash
# Tests (from application/backend, with the venv active)
pytest tests/ -v
```

Live integration tests are skipped by default and only run when the matching API
keys are present in the environment — a plain `pytest` triggers no network calls
and no accidental cost.

> Check you are on the right interpreter: `which python` should point at the
> repository's `.venv/bin/python`. If your shell activates a global venv at
> startup, activate the project's one **afterwards**.

## Web Interface

AdviceRoom's main interface is the **admin console**, a Cloud Temple dark-themed SPA available at `/admin`.

### Access

| Environment | URL | Notes |
|-------------|-----|-------|
| **Production** (WAF) | `https://your-domain/admin` | Via Caddy WAF (port 8088) |
| **Local dev** (WAF) | `http://localhost:8088/admin` | Via WAF |
| **Local dev** (direct) | `http://localhost:8000/admin` | Bypass WAF (uncomment backend port in `docker-compose.yml`) |

> **💡** The root `/` automatically redirects to `/admin`.

### Authentication

The console requires a **Bearer token** (the same one used for the REST API and CLI). On first connection, enter your token in the login form.

- **`read,write` tokens**: access to dashboard, debate creation/monitoring
- **`admin` tokens**: full access including token management (create, revoke)

### Console Features

| Feature | Description |
|---------|-------------|
| 🏠 **Dashboard** | Real-time monitoring of ongoing debates (KPIs, confidence/stability charts, timeline) |
| ➕ **Create debate** | Form with LLM model selection, personas, debate mode and round count |
| 📋 **Debate list** | Full history with status, mode, duration, round count |
| 🔍 **Detail viewer** | Complete debate analysis (positions, arguments, challenges, verdict, HTML export) |
| 🔑 **Token management** | Create and revoke access tokens (admin only) |
| 📊 **LLM activity** | Real-time LLM call activity logs |

> **🔒 Security**: the React frontend (port 3000) is **not publicly exposed** through the WAF. Only the `/admin` console, protected by Bearer authentication, is accessible from outside. Any unknown URL returns a 404.

### Admin REST API

The console uses a dedicated REST API under `/admin/api/`:

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/admin/api/health` | read | Server status + LLM Router |
| GET | `/admin/api/whoami` | read | Current token identity |
| GET | `/admin/api/models` | read | Available LLM models |
| GET | `/admin/api/model-health` | read | LLM provider availability |
| GET | `/admin/api/debates` | read | List debates |
| POST | `/admin/api/debates` | write | Create and start a debate |
| GET | `/admin/api/debates/{id}/stream` | read | Real-time NDJSON stream |
| POST | `/admin/api/debates/{id}/cancel` | write | Stop a running debate |
| GET | `/admin/api/debates/{id}` | read | Debate details |
| GET | `/admin/api/logs` | read | Recent activity |
| GET | `/admin/api/llm-activity` | read | LLM activity log |
| POST | `/admin/api/tokens` | admin | Create a token |
| GET | `/admin/api/tokens` | admin | List tokens |
| DELETE | `/admin/api/tokens/{hash}` | admin | Revoke a token |
| DELETE | `/admin/api/debates/{id}` | write | Delete a debate |

## CLI

The CLI is aligned with the `/admin/api/*` admin API, including `debate start` and NDJSON streaming (`/admin/api/debates/{id}/stream`). Two usage modes: scriptable commands (Click) and interactive shell.

```bash
# Environment variables
export ADVICEROOM_URL=http://localhost:8088  # Local WAF; http://localhost:8000 for direct backend dev
export ADVICEROOM_TOKEN=your-token

# Basic commands
python scripts/adviceroom_cli.py health          # Server status
python scripts/adviceroom_cli.py models          # Available LLM models
python scripts/adviceroom_cli.py debate list     # List debates
python scripts/adviceroom_cli.py debate start "Your question" -m gpt-54,claude-opus-46

# Choose mode and number of rounds
python scripts/adviceroom_cli.py debate start "Question" -m gpt-54,claude-opus-46 --mode standard -r 7
python scripts/adviceroom_cli.py debate start "Question" -m gpt-54,qwen35-27b --mode blitz

# Interactive shell (autocompletion + contextual help)
python scripts/adviceroom_cli.py shell
```

### `debate start` options

| Flag | Short | Description | Default |
|------|-------|-------------|---------|
| `--models` | `-m` | Model IDs separated by commas | *(required)* |
| `--mode` | | Debate mode: `standard`, `parallel`, `blitz` | `parallel` |
| `--rounds` | `-r` | Max number of rounds (1-20) | per mode |

The same options are available in the interactive shell:
```
adviceroom> debate start "My question" -m gpt-54,claude-opus-46 --mode standard -r 5
```

## MCP (AI Agents)

AdviceRoom exposes its tools via the **MCP Streamable HTTP** protocol, compatible with MCP clients like [Cline](https://github.com/cline/cline), Claude Desktop, or any AI agent supporting MCP.

### Cline Configuration

In your `cline_mcp_settings.json` file:

```json
{
  "mcpServers": {
    "mcp-advice": {
      "disabled": false,
      "timeout": 1800,
      "type": "streamableHttp",
      "url": "https://advice.mcp.cloud-temple.app/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

### Recommended Timeouts

Multi-LLM debates take time — each LLM must respond at each round. The MCP timeout must be adapted to the **debate mode** used:

| Mode | Typical duration | Recommended timeout | Description |
|------|-----------------|---------------------|-------------|
| ⚡ **blitz** | 2-5 min | `600` (10 min) | 1 reaction round, quick response |
| 🔄 **parallel** *(default)* | 3-8 min | `900` (15 min) | Parallel rounds, good trade-off |
| ⚙️ **standard** | 15-25 min | `1800` (30 min) | Sequential rounds, maximum interaction |

> **💡 Tip:** Use `"timeout": 1800` to cover all modes without having to modify the config. A timeout that is too short (e.g., the default 60s) will cause a client-side error while the debate is running correctly on the server.

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `debate_create` | Create a debate (question, models, mode, rounds) |
| `debate_status` | Track the status of an ongoing debate |
| `debate_list` | List existing debates |
| `provider_list` | List available LLM models |
| `system_health` | Server health status |
| `system_about` | Server information |

## Supported LLM Models

| Provider              | Model           | Type         | Status |
| --------------------- | --------------- | ------------ | ------ |
| LLMaaS (Cloud Temple) | GPT-OSS 120B    | SecNumCloud  | ✅     |
| LLMaaS (Cloud Temple) | Qwen 3.5 27B    | SecNumCloud  | ✅     |
| LLMaaS (Cloud Temple) | Gemma 4 31B     | SecNumCloud  | ✅     |
| OpenAI                | GPT-5.4         | Public cloud | ✅     |
| Anthropic             | Claude Opus 4-6 | Public cloud | ✅     |
| Google                | Gemini 3.1 Pro  | Public cloud | ✅     |

## Security

- **Multi-tenant isolation**: each debate is tied to its creator (`owner`). Non-admin tokens only see their own debates (read = own debates, write = own debates + create, admin = everything). 11 endpoints protected
- **Reporting a vulnerability**: see [SECURITY.md](SECURITY.md). Do not open a public issue — use GitHub private vulnerability reporting
- **V1.1 audit (2026-04-22)**: 22 findings, 19 fixed, 2 minor partials ([report](DESIGN/SECURITY_AUDIT_V1.md))
- **2026-08-24 audit**: 4 CRITICAL and 5 HIGH identified. **9 of 9 addressed** — 8 fixed in 0.3.0 (guessable bootstrap key, stored XSS in the console, Google key in the query string, revoked-token resurrection, missing rate limiting, secrets in plaintext in the repr, XSS in the HTML export), and the verdict prompt injection **mitigated** in 0.3.1 through defence in depth — not closable, see below
- **Auth**: Bearer Token + ContextVar on all REST and MCP routes
- **Validation**: UUID regex, length limits, bounds, whitelists
- **Infra**: Non-root Dockerfile (UID 1001), internal ports only, HSTS, security headers
- **WAF**: Caddy + Coraza enabled (OWASP CRS v4.8.0, `SecRuleEngine On`)
- **Rate limiting**: throughput and concurrent-debate quota per client, across all 3 creation paths (REST, admin, MCP); admin token creation capped. Answers `429` with `Retry-After`
- **Secrets**: typed `pydantic.SecretStr` — they no longer appear in `repr(settings)`. Note: LLM providers still read their keys from the environment, which a dump would expose
- **Known limitation — verdict prompt injection**: participant outputs feed the synthesizer's prompt. This is inherent to an LLM-to-LLM architecture: we harden in depth, we do not close it. A debate is not a trust boundary
- **Supply chain**: `mcp>=2.1.1,<3` declared explicitly and bounded (`fastmcp` removed — never imported), requirements.lock available

## Documentation

- [Architecture v1.1](DESIGN/architecture.md) — Reference document (17 sections)
- [Security Audit V1.1](DESIGN/SECURITY_AUDIT_V1.md) — Full report (22 findings, 19 fixed)
- [Research Papers](DESIGN/research/README.md) — 9 foundational papers

## Project Structure

```
mcp-adviceroom/
├── application/
│   ├── backend/           # FastAPI + MCP SDK v2
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

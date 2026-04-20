# AdviceRoom — Architecture Document v1.0

> **Date** : 17 avril 2026
> **Auteur** : Christophe Lesur / Agent Cline
> **Licence** : Apache 2.0, open-source
> **Statut** : v1.0 — en attente de validation

---

## 1. Vision produit

**AdviceRoom** est un serveur MCP et une application web qui orchestre des **débats structurés entre LLMs hétérogènes**. L'utilisateur pose une question complexe, invite jusqu'à 5 LLMs (mix SecNumCloud + cloud public), et ils débattent en temps réel selon un protocole fondé sur la recherche académique, jusqu'à convergence ou divergence structurée.

### 1.1 Positionnement

- **Produit interne Cloud Temple**, publié en open-source (Apache 2.0)
- **Agnostique au domaine** : questions stratégiques, techniques, ou ouvertes
- **Multi-provider** : LLMs SNC (gpt-oss, gemma4, qwen) + cloud public (GPT, Claude, Gemini)
- **Outillé** : les LLMs ont accès à des outils (recherche internet, base de connaissance, calcul, MCP externes)
- **Double interface** : MCP (pour agents IA) + Web UI (pour humains)

### 1.2 Cas d'usage cibles

1. "Faut-il adopter Kubernetes pour ce client ?" — débat stratégique avec analyse multi-angles
2. "Quelle architecture pour migrer cette base Oracle ?" — débat technique avec outils
3. "Quels sont les risques de ce contrat SaaS ?" — débat juridique/commercial
4. Tout sujet où des perspectives multiples apportent de la valeur

---

## 2. Fondements académiques

L'architecture s'appuie sur les papiers de recherche suivants (2024-2025) :

### 2.1 Papiers clés — classés par contribution majeure

#### 🔴 Tier 1 — Structurants (définissent le cœur du protocole)

| Réf. | Papier | Contribution majeure | Pourquoi structurant | Intégré dans AdviceRoom |
| ---- | ------ | -------------------- | -------------------- | ----------------------- |
| [2]  | **Free-MAD** (arXiv 2509.11035) | Paradigme consensus-free : évalue la trajectoire entière du débat. Mode conformité + anti-conformité | **Façonne 3 des 7 principes** : verdict par trajectoire (§3.4), challenge obligatoire (§14), dissensus accepté. C'est le papier qui a le plus d'influence directe sur le protocole AdviceRoom | Verdict par analyse de trajectoire, challenge obligatoire |
| [5]  | **Can LLM Agents Really Debate?** (arXiv 2511.07784) | Les LLMs tendent au conformisme. Le biais majoritaire est le défi #1. Le vote majoritaire seul explique la plupart des gains attribués au débat | **Identifie LE problème central** que notre protocole doit résoudre. Sans ce papier, on n'aurait pas de §14 (enforcement anti-conformité). Le conformisme est notre risque #1 (§11) | Anti-conformité forcée dans le prompt + validation post-tour (§14) |
| [1]  | **Multi-LLM Debate** (NeurIPS 2024) | Framework théorique bayésien. Echo chamber, tyrannie de la majorité, misconceptions partagées via training data corrélée. Propose diversity pruning, quality pruning, misconception refutation | **Fournit la justification théorique** de tout le projet. Prouve mathématiquement que le débat entre modèles similaires est futile (→ notre choix de LLMs hétérogènes multi-provider) | Positions initiales en parallèle (déduit du théorème echo chamber). Note : diversity pruning et misconception refutation non implémentés en v1 |

#### 🟡 Tier 2 — Fonctionnels (définissent des composants clés)

| Réf. | Papier | Contribution majeure | Pourquoi fonctionnel | Intégré dans AdviceRoom |
| ---- | ------ | -------------------- | -------------------- | ----------------------- |
| [7]  | **Persona-Driven Multi-Agent** (COLING 2025) | Assigner des personas distinctes maximise la diversité et la persuasion des arguments | **Définit §3.5 entièrement** : les 5 personas, l'attribution automatique, l'injection dans les prompts. Sans ce papier, tous les LLMs auraient le même angle d'analyse | Attribution automatique de personas/angles |
| [3]  | **Stability Detection** (arXiv 2510.12697) | Détection adaptative de stabilité via Beta-Binomial + test KS. Surpasse le vote majoritaire | **Définit §13 entièrement** : l'arrêt adaptatif au lieu d'un nombre fixe de rounds. Approche simplifiée en heuristiques pour notre contexte de débat ouvert | Détection de stabilité pour arrêt adaptatif (heuristiques inspirées du Beta-Binomial+KS — voir §13) |
| [9]  | **Tool-MAD** (arXiv 2601.04742) | Débat multi-agent avec outils hétérogènes par agent + reformulation adaptative des requêtes + scoring hallucinations | **Justifie §4.2.4 (Tool Router)** : donner accès aux outils pendant le débat. Le papier montre +5.5% accuracy avec outils. AdviceRoom donne les mêmes outils à tous (le papier donne des outils différents — amélioration v2) | Tous les LLMs ont accès aux mêmes outils |

#### 🟢 Tier 3 — Cadrage philosophique (orientent les choix sans définir de composant)

| Réf. | Papier | Contribution majeure | Pourquoi cadrage | Intégré dans AdviceRoom |
| ---- | ------ | -------------------- | ---------------- | ----------------------- |
| [6]  | **Consensus-Diversity Trade-off** (arXiv 2502.16565 / EMNLP 2025) | Le consensus implicite surpasse le consensus explicite. La diversité partielle booste l'exploration et la robustesse | **Valide le choix du verdict à 3 issues** (consensus, consensus_partiel, dissensus). Nous autorise à accepter le désaccord comme un résultat valide, pas un échec | Dissensus structuré accepté comme issue valide |
| [4]  | **Debate Protocols** (arXiv 2603.28813) | Comparaison de protocoles (WR, CR, RA-CR). Trade-off entre interaction et convergence | **Confirme le choix du round-robin** (Cross-Round) comme meilleur compromis. Pourrait nous inspirer en v2 pour rendre le protocole configurable | Round-robin avec challenge obligatoire |
| [8]  | **Society of Thought** (arXiv 2601.10825) | Les modèles de raisonnement simulent implicitement un débat multi-perspectives interne | **Validation conceptuelle pure** : si un seul LLM simule un débat interne pour mieux raisonner, un débat explicite entre LLMs doit être encore plus puissant. Renforce la raison d'être du projet | Valide le concept fondamental |

### 2.2 Principes retenus

1. **Anti-ancrage** : positions initiales générées en parallèle (pas séquentiellement) — [1]
2. **Anti-conformité** : chaque LLM DOIT challenger au moins un argument par round — [2, 5]
3. **Personas diversifiées** : angles d'analyse attribués automatiquement — [7]
4. **Pas de consensus forcé** : le dissensus structuré est une issue valide — [2, 6]
5. **Arrêt adaptatif** : détection de stabilité, pas un nombre fixe de rounds — [3]
6. **Verdict par trajectoire** : analyse du débat entier, pas du dernier round — [2]
7. **Outils pour tous** : chaque LLM a accès aux mêmes outils — [9]

---

## 3. Protocole de débat

### 3.1 Vue d'ensemble

```
┌──────────────────────────────────────────────────────────────┐
│                    PROTOCOLE ADVICEROOM                        │
│                                                                │
│  Phase 1: OPENING (parallèle)                                  │
│  ┊  Tous les LLMs produisent leur position initiale            │
│  ┊  EN MÊME TEMPS → évite le biais d'ancrage                  │
│  ┊  Chaque LLM reçoit un persona + accès aux outils           │
│                                                                │
│  Phase 2: DEBATE (round-robin, max N rounds)                   │
│  ┊  Chaque LLM à son tour :                                   │
│  ┊    1. Voit les positions des autres                         │
│  ┊    2. Répond aux arguments (accord/désaccord)               │
│  ┊    3. DOIT challenger ≥1 argument (anti-conformité)         │
│  ┊    4. Peut utiliser des outils (recherche, calcul...)       │
│  ┊    5. Peut poser une question à l'utilisateur → PAUSE       │
│  ┊    6. Met à jour sa position + confidence                   │
│  ┊  → Détection de stabilité après chaque round                │
│  ┊  → Si stable → Phase 3                                     │
│                                                                │
│  Phase 3: VERDICT (LLM synthétiseur dédié)                     │
│  ┊  Analyse la trajectoire entière du débat                    │
│  ┊  Produit : verdict + points d'accord/divergence             │
│  ┊  + recommandation + confidence score                        │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Phase 1 — Opening

**Objectif** : Obtenir des positions initiales indépendantes, sans biais d'ancrage.

- Les N participants reçoivent chacun :
  - La question de l'utilisateur
  - Leur persona assigné (voir §3.5)
  - Le system prompt de débat
  - Accès aux outils
- Tous génèrent leur réponse **en parallèle** (`asyncio.gather`)
- Chaque position initiale est structurée :
  - **Thèse** : position claire sur la question
  - **Arguments** : 2-4 arguments étayant la thèse
  - **Confidence** : 0-100
  - **Tool calls** éventuels (recherche de faits, calculs)

### 3.3 Phase 2 — Debate

**Objectif** : Enrichir, challenger et affiner les positions via des rounds de débat.

**Déroulement d'un round** :
1. L'orchestrateur constitue le **contexte du round** :
   - Question originale
   - Toutes les positions/réponses précédentes
   - Éventuelles réponses de l'utilisateur
2. Chaque participant parle **à tour de rôle** (round-robin)
3. Chaque intervention DOIT contenir :
   - **Réaction** aux arguments des autres (accord ou désaccord argumenté)
   - **Challenge** : identification d'au moins une faille/faiblesse dans l'argumentation d'un autre participant
   - **Position mise à jour** : thèse + confidence actualisées
4. Chaque participant peut :
   - **Utiliser des outils** (recherche internet, base de connaissance, calcul)
   - **Poser une question à l'utilisateur** → **pause complète du débat**

**Arrêt adaptatif** :
- Après chaque round complet, calcul d'un score de stabilité
- Si les positions et confidences n'ont pas significativement bougé → passage en Phase 3
- Sécurité : nombre max de rounds configurable (défaut : 5)

### 3.4 Phase 3 — Verdict

**Objectif** : Synthétiser le débat en un verdict structuré.

Un **LLM synthétiseur dédié** (6ème LLM, hors quota des 5 max) analyse la trajectoire entière :

```json
{
  "verdict": "consensus | consensus_partiel | dissensus",
  "confidence": 78,
  "summary": "Synthèse en 2-3 paragraphes",
  "agreement_points": ["Point d'accord 1", "Point d'accord 2"],
  "divergence_points": [
    {
      "topic": "Timeline de migration",
      "positions": {
        "camp_a": {"participants": ["gpt-5.2", "claude-opus"], "position": "6 mois"},
        "camp_b": {"participants": ["gemini-3.1-pro"], "position": "12 mois"}
      }
    }
  ],
  "recommendation": "Recommandation actionnable",
  "unresolved_questions": ["Question non résolue éventuelle"],
  "key_insights": ["Insight 1 du débat", "Insight 2"]
}
```

### 3.5 Personas (angles d'analyse)

Attribution automatique selon le nombre de participants, avec override possible par l'utilisateur.

| N participants | Personas attribués                                                             |
| -------------- | ------------------------------------------------------------------------------ |
| 2              | Pragmatique, Avocat du diable                                                  |
| 3              | Pragmatique, Analyste risques, Expert technique                                |
| 4              | Pragmatique, Analyste risques, Expert technique, Avocat du diable              |
| 5              | Pragmatique, Analyste risques, Expert technique, Avocat du diable, Visionnaire |

**Définition des personas** :

- **Pragmatique** : Analyse coût-bénéfice, faisabilité, contraintes opérationnelles. Cherche la solution la plus réaliste.
- **Analyste risques** : Identifie les risques, les edge cases, les scénarios d'échec. Challenge les hypothèses optimistes.
- **Expert technique** : Plonge dans les détails techniques, la faisabilité d'implémentation, les trade-offs architecturaux.
- **Avocat du diable** : Conteste systématiquement la position dominante. Cherche les failles, les alternatives non considérées.
- **Visionnaire** : Pense long terme, innovation, tendances. Propose des approches non conventionnelles.

Chaque persona est injecté dans le system prompt du LLM participant.

### 3.6 User-in-the-loop

Quand un LLM émet une question pour l'utilisateur :
1. Le débat entre en état **`paused`**
2. L'événement `user_question` est émis dans le stream
3. **Tous** les participants sont en attente (pause complète)
4. L'utilisateur répond via l'API ou la Web UI
5. La réponse est ajoutée au contexte pour **tous** les participants
6. Le débat reprend au point exact où il s'était arrêté

---

## 4. Architecture technique

### 4.1 Vue globale

```
                    ┌──────────────┐
                    │   Web UI     │  React + Vite + Tailwind
                    │  (Frontend)  │  Design System Cloud Temple
                    └──────┬───────┘
                           │ NDJSON streaming
                    ┌──────┴───────┐
                    │   Backend    │  FastAPI (Python)
                    │  (API REST)  │  Debate Orchestrator
                    └──────┬───────┘
              ┌────────────┼────────────┐
              │            │            │
    ┌─────────┴──┐  ┌──────┴─────┐  ┌──┴──────────┐
    │ MCP Server │  │ LLM Router │  │ Tool Router  │
    │ (FastMCP)  │  │ (Providers)│  │ (MCP Tools)  │
    └────────────┘  └──────┬─────┘  └──────┬───────┘
                           │               │
              ┌────────────┼───────┐       │
              │            │       │       │
         ┌────┴───┐  ┌────┴──┐ ┌──┴───┐  ┌┴──────────┐
         │ LLMaaS │  │OpenAI │ │Anthr.│  │ MCP Tools  │
         │  (SNC) │  │ API   │ │ API  │  │ Perplexity │
         └────────┘  └───────┘ └──────┘  │ Graph-Mem  │
                        ┌──────┐         │ Calc, etc. │
                        │Google│         └────────────┘
                        │ API  │
                        └──────┘
                           │
                    ┌──────┴───────┐
                    │     S3       │  Dell ECS Cloud Temple
                    │  (Storage)   │  Débats, index, transcripts
                    └──────────────┘
```

### 4.2 Composants

#### 4.2.1 Backend — FastAPI

Le backend est le cœur du système. Il expose :

**API REST** :
| Méthode | Endpoint                         | Description                            |
| ------- | -------------------------------- | -------------------------------------- |
| `POST`  | `/api/v1/debates`                | Créer un nouveau débat                 |
| `GET`   | `/api/v1/debates/:id/stream`     | Stream NDJSON du débat en temps réel   |
| `POST`  | `/api/v1/debates/:id/answer`     | Réponse utilisateur à une question LLM |
| `GET`   | `/api/v1/debates/:id`            | État / historique d'un débat           |
| `GET`   | `/api/v1/debates`                | Liste des débats (par API key)         |
| `GET`   | `/api/v1/debates/:id/transcript` | Export Markdown du transcript          |
| `GET`   | `/api/v1/providers`              | Liste des LLMs disponibles             |
| `GET`   | `/api/v1/providers/:id/status`   | Statut d'un provider                   |

**Requête de création** :
```json
{
  "question": "Faut-il migrer vers Kubernetes ?",
  "participants": [
    {"provider": "snc", "model": "gpt-oss:120b"},
    {"provider": "anthropic", "model": "claude-opus-4.6"},
    {"provider": "google", "model": "gemini-3.1-pro"},
    {"provider": "snc", "model": "gemma4:31b"},
    {"provider": "openai", "model": "gpt-5.2"}
  ],
  "persona_overrides": {
    "claude-opus-4.6": "Expert sécurité"
  },
  "config": {
    "max_rounds": 5,
    "tools_enabled": true,
    "synthesizer_model": "claude-opus-4.6"
  }
}
```

#### 4.2.2 Debate Engine (core)

Le Debate Engine est la pièce centrale, **nouvelle** (n'existe pas dans QuoteFlow) :

```
app/services/debate/
├── orchestrator.py      # DebateOrchestrator — gère le cycle de vie complet
├── context_builder.py   # Construit le contexte pour chaque participant à chaque round
├── stability.py         # Détection de stabilité (heuristiques simplifiées, voir §13)
├── personas.py          # Attribution et gestion des personas
├── verdict.py           # VerdictSynthesizer — analyse trajectoire → verdict
└── models.py            # Dataclasses : Debate, Round, Turn, Position, Verdict
```

**DebateOrchestrator** — Cycle de vie :
```
CREATED → OPENING → DEBATING → [PAUSED] → VERDICT → COMPLETED
                        ↑          │
                        └──────────┘ (user answers)
```

**États du débat** :
- `created` : débat créé, pas encore démarré
- `opening` : positions initiales en cours de génération
- `debating` : rounds de débat en cours
- `paused` : en attente d'une réponse utilisateur
- `verdict` : synthèse en cours de génération
- `completed` : terminé (consensus, consensus_partiel, ou dissensus)
- `error` : erreur fatale
- `cancelled` : annulé par l'utilisateur

#### 4.2.3 LLM Providers (dupliqué + étendu depuis QuoteFlow)

```
app/services/llm/
├── base.py              # BaseLLMProvider (abstraction) — depuis QuoteFlow
├── llmaas.py            # LLMaaS Cloud Temple (SNC) — depuis QuoteFlow
├── google.py            # Google Gemini — depuis QuoteFlow
├── openai.py            # OpenAI — NOUVEAU
├── anthropic.py         # Anthropic — NOUVEAU
├── router.py            # LLM Router multi-provider — adapté de QuoteFlow
└── models_config.py     # Chargement YAML des modèles — depuis QuoteFlow
```

**Interface commune** (héritée de QuoteFlow) :
```python
class BaseLLMProvider(ABC):
    async def generate(self, messages, tools=None, **kwargs) -> LLMResponse
    async def generate_stream(self, messages, tools=None, **kwargs) -> AsyncIterator[LLMStreamChunk]
```

**Normalization** : tous les providers retournent des `LLMResponse` / `LLMStreamChunk` normalisés au format OpenAI (standard interne).

#### 4.2.4 Tool Router (dupliqué depuis QuoteFlow)

```
app/services/tools/
├── registry.py          # MCP Tool Registry — depuis QuoteFlow
├── executor.py          # Tool Executor — depuis QuoteFlow
└── config/
    └── tools.yaml       # Configuration des outils disponibles
```

**Pipeline 4 étapes** (hérité de QuoteFlow) :
1. **Profile filtering** : quels MCPs sont autorisés dans le contexte
2. **Intent routing** : quel MCP correspond à l'appel tool
3. **Tool selection** : quel outil spécifique dans le MCP
4. **Execution dispatch** : appel effectif au serveur MCP

**Outils disponibles pendant le débat** :

| Outil                               | Source       | Usage dans le débat                              |
| ----------------------------------- | ------------ | ------------------------------------------------ |
| `perplexity_search`                 | mcp-tools    | Vérifier des faits, trouver des données récentes |
| `perplexity_doc`                    | mcp-tools    | Documentation technique                          |
| `memory_search` / `question_answer` | graph-memory | Interroger la base de connaissance Cloud Temple  |
| `calc`                              | mcp-tools    | Calculs chiffrés (TCO, dimensionnement)          |
| `date`                              | mcp-tools    | Contexte temporel                                |
| `http`                              | mcp-tools    | Appels API externes                              |
| `shell` (sandbox)                   | mcp-tools    | Commandes système (sandboxé)                     |
| MCP externes                        | Configurable | N'importe quel MCP connecté                      |

Tous les outils sont disponibles pour **tous** les LLMs participants.

#### 4.2.5 MCP Server — même processus que le Backend

> **Décision architecturale** : le serveur MCP et le backend REST vivent dans le **même processus FastAPI**. Le backend sert à la fois `/api/v1/` (REST pour la Web UI) et `/mcp` (Streamable HTTP pour les agents IA). Pas de service séparé, pas de communication inter-processus.
>
> **Justification** : le Debate Engine est le même code dans les deux cas. Séparer en deux services forcerait soit une duplication du moteur, soit une API REST interne (latence + complexité). Le pattern starter-kit montre déjà comment monter FastMCP dans une app ASGI existante via `create_app()`.

```python
# app/main.py — un seul processus, deux interfaces
def create_app():
    # FastMCP (innermost) — sert /mcp
    mcp_app = mcp.streamable_http_app()
    
    # Pile middleware ASGI (pattern starter-kit)
    app = AuthMiddleware(mcp_app)
    app = HealthCheckMiddleware(app)
    app = AdminMiddleware(app, mcp)
    app = LoggingMiddleware(app)
    
    # Mount FastAPI REST sous /api/v1/
    fastapi_app = FastAPI(title="AdviceRoom")
    fastapi_app.include_router(debates_router, prefix="/api/v1")
    fastapi_app.include_router(providers_router, prefix="/api/v1")
    
    # Combiner les deux
    fastapi_app.mount("/mcp", app)       # Agents IA
    fastapi_app.mount("/admin", admin)    # Console admin
    
    return fastapi_app
```

**Conséquence sur le docker-compose** : le service `mcp-server` séparé est **supprimé**. Le backend sert tout. Le docker-compose passe de 6 à 5 services.

**Outils MCP exposés** (dans `app/mcp/tools.py`) :

| Outil               | Permission | Description                              |
| ------------------- | ---------- | ---------------------------------------- |
| `debate_create`     | write      | Créer et lancer un nouveau débat         |
| `debate_status`     | read       | Statut d'un débat en cours               |
| `debate_answer`     | write      | Répondre à une question posée par un LLM |
| `debate_list`       | read       | Lister les débats (filtré par token)     |
| `debate_transcript` | read       | Transcript Markdown complet d'un débat   |
| `debate_cancel`     | write      | Annuler un débat en cours                |
| `provider_list`     | read       | Lister les LLMs disponibles              |
| `system_health`     | —          | État de santé du service                 |
| `system_about`      | —          | Informations sur le service              |
| `system_whoami`     | read       | Identité du token courant                |

Les outils MCP appellent **directement** les mêmes services internes (`DebateOrchestrator`, `LLMRouter`, etc.) que les endpoints REST — pas d'indirection réseau.

#### 4.2.6 Frontend — React

```
frontend/src/
├── App.jsx
├── main.jsx
├── design-system/       # Dupliqué depuis QuoteFlow (tokens, components, layouts)
├── contexts/
│   ├── AuthContext.jsx   # Dupliqué depuis QuoteFlow
│   └── DebateContext.jsx # NOUVEAU — état du débat courant
├── hooks/
│   ├── useAuth.js        # Dupliqué depuis QuoteFlow
│   ├── useHttpClient.js  # Dupliqué depuis QuoteFlow
│   ├── useNDJSONStream.js # Dupliqué depuis QuoteFlow, étendu
│   └── useDebate.js      # NOUVEAU — orchestration frontend du débat
├── modules/
│   ├── debate/           # NOUVEAU — Module principal
│   │   ├── DebatePage.jsx        # Page principale
│   │   ├── DebateCreate.jsx      # Formulaire de création
│   │   ├── DebateView.jsx        # Vue temps réel du débat
│   │   ├── DebateHistory.jsx     # Liste des débats passés
│   │   ├── components/
│   │   │   ├── ParticipantBubble.jsx  # Bulle de message par LLM
│   │   │   ├── ToolCallBadge.jsx      # Badge d'appel outil inline
│   │   │   ├── UserQuestionPanel.jsx  # Zone de réponse utilisateur
│   │   │   ├── VerdictPanel.jsx       # Panel de verdict final
│   │   │   ├── StabilityIndicator.jsx # Indicateur de convergence
│   │   │   ├── RoundTimeline.jsx      # Timeline des rounds
│   │   │   └── ParticipantAvatar.jsx  # Avatar + couleur par LLM
│   │   └── utils/
│   │       ├── participantColors.js   # Palette de couleurs par participant
│   │       └── streamParser.js        # Parse les événements NDJSON du débat
│   └── admin/            # Dupliqué depuis QuoteFlow (si nécessaire)
└── layouts/
    └── AppShell.jsx      # Dupliqué depuis QuoteFlow
```

#### 4.2.7 Storage — S3

```
adviceroom/
├── debates/
│   ├── {api_key_hash}/           # Isolation par API key
│   │   ├── _index.json           # Liste des débats (métadonnées)
│   │   └── {debate_id}/
│   │       ├── meta.json         # Métadonnées du débat
│   │       ├── opening.json      # Positions initiales
│   │       ├── rounds/
│   │       │   ├── 1.json        # Round 1 complet
│   │       │   ├── 2.json        # Round 2 complet
│   │       │   └── ...
│   │       ├── verdict.json      # Verdict final
│   │       ├── transcript.md     # Transcript Markdown lisible
│   │       └── metrics.json      # Métriques (tokens, durées, coûts)
└── _system/
    └── tokens.json               # Token Store (pattern starter-kit)
```

### 4.3 Protocole de streaming NDJSON

Le flux NDJSON est le protocole de communication temps réel entre le backend et le frontend (ou tout client).

**Événements** :

```jsonl
{"type": "debate_start", "debate_id": "abc123", "question": "...", "participants": [...], "config": {...}}

{"type": "phase", "phase": "opening", "round": 0}
{"type": "turn_start", "participant": {"model": "claude-opus-4.6", "provider": "anthropic", "persona": "Analyste risques"}}
{"type": "chunk", "participant_id": "claude-opus-4.6", "content": "Concernant la migration..."}
{"type": "chunk", "participant_id": "claude-opus-4.6", "content": " je recommande..."}
{"type": "tool_call", "participant_id": "claude-opus-4.6", "tool": "perplexity_search", "args": {"query": "K8s TCO 2025"}}
{"type": "tool_result", "participant_id": "claude-opus-4.6", "tool": "perplexity_search", "result": "...", "duration_ms": 2300}
{"type": "turn_end", "participant_id": "claude-opus-4.6", "position": "pour", "confidence": 85}

{"type": "phase", "phase": "debate", "round": 1}
{"type": "turn_start", "participant": {"model": "gpt-5.2", "provider": "openai", "persona": "Pragmatique"}}
{"type": "chunk", "participant_id": "gpt-5.2", "content": "Je conteste l'argument de Claude..."}
{"type": "turn_end", "participant_id": "gpt-5.2", "position": "contre", "confidence": 72}

{"type": "user_question", "participant_id": "gemini-3.1-pro", "question": "Quelle est la taille de votre équipe DevOps ?"}
{"type": "debate_paused", "reason": "waiting_for_user"}

{"type": "user_answer", "answer": "3 personnes"}
{"type": "debate_resumed"}

{"type": "stability", "round": 2, "score": 0.87, "converging": true, "positions_changed": 1}

{"type": "phase", "phase": "verdict"}
{"type": "verdict", "result": "consensus_partiel", "confidence": 78, "summary": "...", "agreement_points": [...], "divergence_points": [...], "recommendation": "..."}

{"type": "debate_end", "duration_seconds": 45, "total_tokens": 125000, "total_rounds": 3}
```

---

## 5. Modèles LLM

### 5.1 Registry

```yaml
# config/llm_models.yaml
categories:
  snc:
    display_name: "SecNumCloud"
    description: "Modèles hébergés sur infrastructure SecNumCloud Cloud Temple"
  externe:
    display_name: "Cloud Public"
    description: "Modèles via APIs cloud public"

models:
  # --- SNC (LLMaaS Cloud Temple) ---
  - id: gpt-oss-120b
    display_name: "GPT-OSS 120B"
    provider: llmaas
    category: snc
    api_model_id: "gpt-oss:120b"
    capabilities: [chat, tools, streaming]
    context_window: 131072
    active: true

  - id: gemma4-31b
    display_name: "Gemma 4 31B"
    provider: llmaas
    category: snc
    api_model_id: "gemma4:31b"
    capabilities: [chat, tools, streaming]
    context_window: 131072
    active: true

  - id: qwen35-27b
    display_name: "Qwen 3.5 27B"
    provider: llmaas
    category: snc
    api_model_id: "qwen3.5:27b"
    capabilities: [chat, tools, streaming]
    context_window: 131072
    active: true

  # --- OpenAI ---
  - id: gpt-52
    display_name: "GPT-5.2"
    provider: openai
    category: externe
    api_model_id: "gpt-5.2"
    capabilities: [chat, tools, streaming]
    context_window: 200000
    active: true

  # --- Anthropic ---
  - id: claude-opus-46
    display_name: "Claude Opus 4.6"
    provider: anthropic
    category: externe
    api_model_id: "claude-opus-4.6"
    capabilities: [chat, tools, streaming]
    context_window: 200000
    active: true

  # --- Google ---
  - id: gemini-31-pro
    display_name: "Gemini 3.1 Pro"
    provider: google
    category: externe
    api_model_id: "gemini-3.1-pro"
    capabilities: [chat, tools, streaming]
    context_window: 1000000
    active: true

# Modèle par défaut pour le synthétiseur de verdict
default_synthesizer: claude-opus-46
```

### 5.2 Ajout de nouveaux providers

Pour ajouter un provider, créer un fichier `app/services/llm/{provider}.py` qui implémente `BaseLLMProvider` :

```python
class OpenAIProvider(BaseLLMProvider):
    async def generate(self, messages, tools=None, **kwargs) -> LLMResponse: ...
    async def generate_stream(self, messages, tools=None, **kwargs) -> AsyncIterator[LLMStreamChunk]: ...
```

L'interface est normalisée au format OpenAI (standard interne hérité de QuoteFlow).

---

## 6. Stack technique

### 6.1 Backend

| Composant     | Technologie              | Rôle                               |
| ------------- | ------------------------ | ---------------------------------- |
| Framework API | FastAPI (Python 3.12)    | API REST + NDJSON streaming        |
| Framework MCP | FastMCP (Python SDK)     | Outils MCP via Streamable HTTP     |
| Serveur HTTP  | Uvicorn (ASGI)           | Sert l'application                 |
| Configuration | pydantic-settings        | Variables d'environnement + `.env` |
| LLM clients   | httpx (async)            | Appels aux APIs LLM                |
| S3            | boto3                    | Stockage des débats                |
| Auth          | JWT RS256 + Bearer Token | Double mode (Web UI + MCP)         |

### 6.2 Frontend

| Composant     | Technologie                    | Rôle                           |
| ------------- | ------------------------------ | ------------------------------ |
| Framework     | React 18 + Vite                | SPA moderne                    |
| CSS           | Tailwind CSS                   | Styling utilitaire             |
| Design System | Cloud Temple DS (de QuoteFlow) | Tokens, composants, layouts    |
| Streaming     | useNDJSONStream (de QuoteFlow) | Consommation NDJSON temps réel |
| Markdown      | react-markdown + rehype        | Rendu des réponses LLM         |
| Auth          | AuthContext (de QuoteFlow)     | JWT + refresh tokens           |

### 6.3 Infrastructure

| Composant    | Technologie                         | Rôle                          |
| ------------ | ----------------------------------- | ----------------------------- |
| Conteneurs   | Docker + Docker Compose             | Déploiement                   |
| WAF          | Caddy + Coraza                      | TLS, rate limiting, OWASP CRS |
| Storage      | S3 Dell ECS (Cloud Temple)          | Débats, tokens, config        |
| Auth service | FastAPI microservice (de QuoteFlow) | JWT RS256 + JWKS              |
| Redis        | Redis 7                             | Cache JWKS, sessions          |

### 6.4 Docker Compose

Voir §17 pour le Docker Compose révisé (5 services après fusion MCP + Backend).

---

## 7. Composants réutilisés depuis QuoteFlow

### 7.1 Règle : copie, jamais de modification

Tous les composants sont **dupliqués** depuis QuoteFlow dans le repo AdviceRoom. Le repo QuoteFlow n'est **jamais modifié**.

### 7.2 Matrice de réutilisation

| Composant                       | Source QuoteFlow                                          | Destination AdviceRoom                           | Adaptation                     |
| ------------------------------- | --------------------------------------------------------- | ------------------------------------------------ | ------------------------------ |
| `BaseLLMProvider` + dataclasses | `backend/app/services/llm_providers/base.py`              | `backend/app/services/llm/base.py`               | Aucune                         |
| Provider LLMaaS                 | `backend/app/services/llm_providers/llmaas.py`            | `backend/app/services/llm/llmaas.py`             | Aucune                         |
| Provider Google                 | `backend/app/services/llm_providers/google.py`            | `backend/app/services/llm/google.py`             | Aucune                         |
| LLM Router                      | `backend/app/services/llm_router.py`                      | `backend/app/services/llm/router.py`             | Adapter pour multi-participant |
| LLM Service                     | `backend/app/services/llm_service.py`                     | `backend/app/services/llm/service.py`            | Refactorer pour débat          |
| MCP Registry                    | `backend/app/services/mcp/mcp_registry.py`                | `backend/app/services/tools/registry.py`         | Simplifier (pas de profiles)   |
| Context management              | `backend/app/services/llm_service.py`                     | `backend/app/services/debate/context_builder.py` | Adapter pour débat             |
| Design System                   | `frontend/src/design-system/`                             | `frontend/src/design-system/`                    | Aucune                         |
| AuthContext                     | `frontend/src/contexts/AuthContext.jsx`                   | `frontend/src/contexts/AuthContext.jsx`          | Aucune                         |
| useNDJSONStream                 | `frontend/src/modules/assistant/hooks/useNDJSONStream.js` | `frontend/src/hooks/useNDJSONStream.js`          | Étendre événements             |
| useHttpClient                   | `frontend/src/hooks/useHttpClient.js`                     | `frontend/src/hooks/useHttpClient.js`            | Aucune                         |
| Auth microservice               | `application/auth/`                                       | `application/auth/`                              | Aucune                         |
| WAF Caddy+Coraza                | `waf/`                                                    | `waf/`                                           | Adapter ports                  |

### 7.3 Composants entièrement nouveaux

| Composant                 | Description                                     |
| ------------------------- | ----------------------------------------------- |
| `DebateOrchestrator`      | Orchestration du débat en 3 phases              |
| `StabilityDetector`       | Détection de convergence/stabilité              |
| `VerdictSynthesizer`      | Analyse de trajectoire → verdict structuré      |
| `PersonaManager`          | Attribution et injection des personas           |
| `OpenAIProvider`          | Provider OpenAI API                             |
| `AnthropicProvider`       | Provider Anthropic API                          |
| Module frontend `debate/` | Toute l'UI de débat (bulles, timeline, verdict) |
| MCP Server AdviceRoom     | Outils MCP pour agents IA                       |

---

## 8. Sécurité

### 8.1 Principes

- **Isolation multi-tenant** : chaque API key ne voit que ses propres débats
- **Pas de token via query string** : Bearer header uniquement
- **Comparaison constante** : `hmac.compare_digest()` pour les clés
- **Fail-close** : token invalide/expiré → rejet
- **WAF** : Caddy + Coraza OWASP CRS + rate limiting
- **HSTS** : forcé dans le WAF
- **Les clés API des providers LLM** sont côté serveur uniquement (jamais exposées au frontend)

### 8.2 Modèle d'authentification

Deux modes coexistent :
1. **Web UI** : JWT RS256 via auth microservice (login/password, optionnel OIDC)
2. **MCP** : Bearer token simple via Token Store S3 (pattern starter-kit)

---

## 9. Plan de développement

### Phase 1 — Fondation + Debate Engine (semaine 1)

| #    | Tâche                                                           | Priorité |
| ---- | --------------------------------------------------------------- | -------- |
| 1.1  | Setup projet (structure, Dockerfile, docker-compose, .env)      | P0       |
| 1.2  | Dupliquer LLM providers depuis QuoteFlow (base, llmaas, google) | P0       |
| 1.3  | Créer OpenAI provider                                           | P0       |
| 1.4  | Créer Anthropic provider                                        | P0       |
| 1.5  | Adapter LLM Router pour multi-participant                       | P0       |
| 1.6  | Créer DebateOrchestrator (cycle de vie complet)                 | P0       |
| 1.7  | Créer PersonaManager                                            | P1       |
| 1.8  | Dupliquer MCP Tool Pipeline depuis QuoteFlow                    | P1       |
| 1.9  | S3 persistence des débats                                       | P1       |
| 1.10 | MCP Server (debate_create, debate_status, debate_transcript)    | P1       |

### Phase 2 — Streaming + User Interaction (semaine 2)

| #   | Tâche                               | Priorité |
| --- | ----------------------------------- | -------- |
| 2.1 | Endpoint NDJSON streaming du débat  | P0       |
| 2.2 | User-in-the-loop (pause/reprise)    | P0       |
| 2.3 | StabilityDetector (arrêt adaptatif) | P1       |
| 2.4 | VerdictSynthesizer                  | P0       |
| 2.5 | Tool calls pendant le débat         | P1       |

### Phase 3 — Frontend (semaine 2-3)

| #   | Tâche                                           | Priorité |
| --- | ----------------------------------------------- | -------- |
| 3.1 | Dupliquer Design System + Auth depuis QuoteFlow | P0       |
| 3.2 | Dupliquer/adapter useNDJSONStream               | P0       |
| 3.3 | DebateCreate (formulaire)                       | P0       |
| 3.4 | DebateView (bulles temps réel + streaming)      | P0       |
| 3.5 | ToolCallBadge (affichage inline)                | P1       |
| 3.6 | UserQuestionPanel                               | P0       |
| 3.7 | VerdictPanel                                    | P0       |
| 3.8 | DebateHistory (liste des débats)                | P1       |

### Phase 4 — Polish + Production (semaine 3-4)

| #   | Tâche                                         | Priorité |
| --- | --------------------------------------------- | -------- |
| 4.1 | Export transcript Markdown                    | P1       |
| 4.2 | Métriques (tokens, durées, coûts par débat)   | P2       |
| 4.3 | Docker Compose complet + WAF                  | P0       |
| 4.4 | Auth microservice (dupliqué depuis QuoteFlow) | P1       |
| 4.5 | Documentation + README                        | P1       |
| 4.6 | Tests                                         | P2       |

---

## 10. Structure de fichiers cible

```
mcp-adviceroom/
├── DESIGN/
│   └── architecture.md          # Ce document
├── starter-kit/                 # Référence boilerplate MCP
├── application/
│   ├── backend/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py                    # FastAPI entry point
│   │       ├── config/
│   │       │   ├── settings.py            # pydantic-settings (.env)
│   │       │   ├── loader.py              # Chargeur YAML (lazy singletons)
│   │       │   ├── llm_models.yaml        # Registry des modèles LLM
│   │       │   ├── prompts.yaml           # System prompts (opening, debate, verdict)
│   │       │   ├── personas.yaml          # Personas et attribution automatique
│   │       │   ├── debate.yaml            # Paramètres protocole (stabilité, erreurs, contexte)
│   │       │   └── tools.yaml             # Configuration des outils MCP
│   │       ├── routers/
│   │       │   ├── debates.py             # API REST des débats
│   │       │   └── providers.py           # API des providers LLM
│   │       ├── services/
│   │       │   ├── debate/                # ← NOUVEAU (cœur du projet)
│   │       │   │   ├── orchestrator.py    # Debate Orchestrator
│   │       │   │   ├── context_builder.py # Contexte par participant
│   │       │   │   ├── stability.py       # Détection de stabilité
│   │       │   │   ├── personas.py        # Gestion des personas
│   │       │   │   ├── verdict.py         # Synthétiseur de verdict
│   │       │   │   └── models.py          # Dataclasses
│   │       │   ├── llm/                   # ← Dupliqué + étendu
│   │       │   │   ├── base.py            # BaseLLMProvider
│   │       │   │   ├── llmaas.py          # LLMaaS (SNC)
│   │       │   │   ├── google.py          # Google Gemini
│   │       │   │   ├── openai.py          # OpenAI (NOUVEAU)
│   │       │   │   ├── anthropic.py       # Anthropic (NOUVEAU)
│   │       │   │   ├── router.py          # LLM Router
│   │       │   │   └── service.py         # LLM Service unifié
│   │       │   ├── tools/                 # ← Dupliqué
│   │       │   │   ├── registry.py        # MCP Tool Registry
│   │       │   │   └── executor.py        # Tool Executor
│   │       │   └── storage/               # ← Adapté
│   │       │       └── s3_service.py      # Persistence S3 des débats
│   │       └── middleware/
│   │           ├── auth.py                # JWT + Bearer
│   │           └── logging.py             # Request logging
│   ├── frontend/
│   │   ├── Dockerfile
│   │   ├── package.json
│   │   ├── vite.config.js
│   │   ├── tailwind.config.js
│   │   └── src/
│   │       ├── App.jsx
│   │       ├── main.jsx
│   │       ├── design-system/             # ← Dupliqué de QuoteFlow
│   │       ├── contexts/
│   │       │   ├── AuthContext.jsx         # ← Dupliqué
│   │       │   └── DebateContext.jsx       # ← NOUVEAU
│   │       ├── hooks/
│   │       │   ├── useAuth.js             # ← Dupliqué
│   │       │   ├── useHttpClient.js       # ← Dupliqué
│   │       │   ├── useNDJSONStream.js     # ← Dupliqué + étendu
│   │       │   └── useDebate.js           # ← NOUVEAU
│   │       └── modules/
│   │           └── debate/                # ← NOUVEAU
│   │               ├── DebatePage.jsx
│   │               ├── DebateCreate.jsx
│   │               ├── DebateView.jsx
│   │               ├── DebateHistory.jsx
│   │               └── components/
│   └── auth/                              # ← Dupliqué de QuoteFlow
│       ├── Dockerfile
│       └── app/
├── waf/                                   # ← Dupliqué de QuoteFlow
│   ├── Caddyfile
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
├── VERSION                                # 0.1.0
├── LICENSE                                # Apache 2.0
└── README.md
```

---

## 11. Risques identifiés

| Risque                     | Impact                                       | Probabilité | Mitigation                                                                      |
| -------------------------- | -------------------------------------------- | ----------- | ------------------------------------------------------------------------------- |
| **Conformisme des LLMs**   | Les LLMs s'alignent tous → débat inutile     | Élevée      | Anti-conformité forcée (challenge obligatoire) + positions initiales parallèles |
| **Coût token élevé**       | Un débat 5 LLMs × 5 rounds = 100-200K tokens | Certaine    | Pas un problème (décision Christophe) mais métriques pour suivi                 |
| **Latence**                | 5 LLMs séquentiels en phase débat = lent     | Élevée      | Streaming NDJSON + positions initiales en parallèle                             |
| **Provider API down**      | Un LLM indisponible bloque le débat          | Moyenne     | Timeout + graceful degradation (le débat continue sans ce participant)          |
| **Biais d'ancrage**        | Le premier LLM à parler influence les autres | Élevée      | Phase 1 parallèle résout ce problème                                            |
| **Complexité du contexte** | Le contexte grossit à chaque round           | Moyenne     | Smart truncation (hérité de QuoteFlow)                                          |
| **Détection de stabilité** | Faux positifs/négatifs sur la convergence    | Moyenne     | Nombre max de rounds en sécurité                                                |

---

## 12. Fichiers de configuration externalisés

> **Principe** : tout ce qui est configurable est dans des fichiers YAML dans `app/config/`, JAMAIS codé en dur dans le Python. Cela permet de modifier les prompts, personas, seuils, et comportements sans toucher au code.

### 12.1 Structure des fichiers de configuration

```
app/config/
├── llm_models.yaml        # Registry des modèles LLM (voir §5.1)
├── tools.yaml             # Configuration des outils MCP disponibles
├── prompts.yaml           # ← TOUS les system prompts
├── personas.yaml          # ← Définition des personas et attribution
├── debate.yaml            # ← Paramètres du protocole de débat
└── settings.py            # Variables d'environnement (pydantic-settings)
```

### 12.2 `prompts.yaml` — System Prompts

```yaml
# config/prompts.yaml
# Tous les prompts sont des templates Jinja2 avec variables {variable}

opening:
  system: |
    Tu es un expert participant à un débat structuré dans AdviceRoom.

    ## Ton rôle
    Tu es "{persona_name}" — {persona_description}

    ## Règles du débat
    - Tu participes à un débat avec {n_participants} autres experts IA
    - C'est la PHASE D'OUVERTURE : tu donnes ta position initiale SANS connaître celles des autres
    - Tu dois être indépendant dans ton analyse — ne fais pas de suppositions sur ce que les autres diront

    ## Ta tâche
    Analyse la question suivante selon ton angle d'expertise et produis ta position initiale.

    ## Format de réponse OBLIGATOIRE
    Tu DOIS terminer ta réponse par un bloc structuré exactement dans ce format :

    ---POSITION---
    thesis: [Ta position en une phrase claire]
    confidence: [Un nombre entre 0 et 100]
    arguments:
    - [Argument 1]
    - [Argument 2]
    - [Argument 3]
    ---END---

    Le texte AVANT le bloc ---POSITION--- est ton analyse détaillée (en Markdown).
    Le bloc ---POSITION--- est parsé automatiquement — respecte le format exactement.

    ## Outils
    Tu as accès à des outils (recherche internet, base de connaissance, calcul). Utilise-les si tu as besoin de vérifier des faits ou faire des calculs pour étayer ta position.

    ## Question pour l'utilisateur
    Si tu as absolument besoin d'une information manquante pour répondre, tu peux poser UNE question à l'utilisateur en ajoutant :
    ---USER_QUESTION---
    [Ta question]
    ---END---

debate:
  system: |
    Tu es un expert participant à un débat structuré dans AdviceRoom.

    ## Ton rôle
    Tu es "{persona_name}" — {persona_description}

    ## Contexte du débat
    Question originale : "{question}"
    {user_answers_if_any}

    ## Positions des autres participants
    {formatted_previous_positions}

    ## Règles du round {round_number}
    1. RÉAGIS aux arguments des autres participants (accord ou désaccord ARGUMENTÉ)
    2. Tu DOIS CHALLENGER au minimum UN argument d'un autre participant — identifie une faille, une hypothèse non vérifiée, un risque ignoré, ou une alternative non considérée. Un challenge superficiel ("je ne suis pas tout à fait d'accord") ne compte PAS — tu dois expliquer POURQUOI l'argument est faible.
    3. Mets à jour ta position si les arguments des autres t'ont convaincu (partiellement ou totalement)
    4. Tu peux utiliser des outils pour étayer tes arguments

    ## Format de réponse OBLIGATOIRE
    Ton analyse en Markdown, puis :

    ---POSITION---
    thesis: [Ta position mise à jour]
    confidence: [0-100, mis à jour]
    arguments:
    - [Tes arguments actualisés]
    challenged: [Nom du participant dont tu as challengé l'argument]
    challenge_target: [L'argument spécifique que tu contestes]
    challenge_reason: [Pourquoi cet argument est faible/incorrect]
    agrees_with:
    - [participant_id]: [Sur quel point tu es d'accord]
    disagrees_with:
    - [participant_id]: [Sur quel point tu es en désaccord]
    ---END---

    {user_question_instruction}

verdict:
  system: |
    Tu es le synthétiseur impartial d'un débat AdviceRoom.

    ## Ta mission
    Analyse la TRAJECTOIRE ENTIÈRE du débat ci-dessous et produis un verdict structuré.
    Tu n'es PAS un participant — tu es un analyste neutre.

    ## Ce que tu dois évaluer
    1. Les positions ont-elles convergé ? (consensus)
    2. Y a-t-il des points d'accord partiels ? (consensus_partiel)
    3. Les positions restent-elles irréconciliables ? (dissensus)
    4. Quels arguments ont été les plus solides ?
    5. Quels challenges ont fait évoluer les positions ?
    6. Y a-t-il des questions non résolues ?

    ## Trajectoire du débat
    Question : "{question}"
    Réponses utilisateur : {user_answers}

    ### Positions initiales (Opening)
    {formatted_opening_positions}

    ### Rounds de débat
    {formatted_rounds}

    ## Format de réponse OBLIGATOIRE
    ---VERDICT---
    verdict: [consensus | consensus_partiel | dissensus]
    confidence: [0-100]
    summary: |
      [Synthèse en 2-3 paragraphes]
    agreement_points:
    - [Point d'accord 1]
    - [Point d'accord 2]
    divergence_points:
    - topic: [Sujet de divergence]
      camp_a:
        participants: [liste]
        position: [position]
      camp_b:
        participants: [liste]
        position: [position]
    recommendation: |
      [Recommandation actionnable]
    unresolved_questions:
    - [Question non résolue]
    key_insights:
    - [Insight 1]
    - [Insight 2]
    ---END---

challenge_retry: |
  Tu n'as pas identifié de faille dans l'argumentation des autres participants.
  Le débat AdviceRoom EXIGE que tu challenges au moins un argument.

  Voici les positions des autres participants :
  {other_positions}

  Identifie UNE faiblesse concrète dans l'argumentation de l'un d'entre eux.
  Cela peut être : une hypothèse non vérifiée, un risque ignoré, un cas limite non considéré,
  une donnée manquante, ou une alternative non explorée.

  Réponds UNIQUEMENT avec :
  ---CHALLENGE---
  challenged: [participant_id]
  challenge_target: [L'argument contesté]
  challenge_reason: [Explication détaillée de la faille]
  ---END---
```

### 12.3 `personas.yaml` — Personas et attribution

```yaml
# config/personas.yaml

# Définition de chaque persona
definitions:
  pragmatique:
    name: "Pragmatique"
    description: "Analyse coût-bénéfice, faisabilité, contraintes opérationnelles. Cherche la solution la plus réaliste."
    icon: "💼"
    color: "#4CAF50"

  analyste_risques:
    name: "Analyste risques"
    description: "Identifie les risques, les edge cases, les scénarios d'échec. Challenge les hypothèses optimistes."
    icon: "⚠️"
    color: "#FF9800"

  expert_technique:
    name: "Expert technique"
    description: "Plonge dans les détails techniques, la faisabilité d'implémentation, les trade-offs architecturaux."
    icon: "🔧"
    color: "#2196F3"

  avocat_du_diable:
    name: "Avocat du diable"
    description: "Conteste systématiquement la position dominante. Cherche les failles, les alternatives non considérées."
    icon: "😈"
    color: "#F44336"

  visionnaire:
    name: "Visionnaire"
    description: "Pense long terme, innovation, tendances. Propose des approches non conventionnelles."
    icon: "🔮"
    color: "#9C27B0"

# Attribution automatique selon le nombre de participants
auto_assignment:
  2: [pragmatique, avocat_du_diable]
  3: [pragmatique, analyste_risques, expert_technique]
  4: [pragmatique, analyste_risques, expert_technique, avocat_du_diable]
  5: [pragmatique, analyste_risques, expert_technique, avocat_du_diable, visionnaire]
```

### 12.4 `debate.yaml` — Paramètres du protocole

```yaml
# config/debate.yaml

# Limites du débat
limits:
  max_participants: 5             # Max LLMs invités (hors synthétiseur)
  max_rounds: 5                   # Max rounds de débat (Phase 2)
  min_rounds: 2                   # Min rounds avant arrêt adaptatif

# Détection de stabilité (§13)
stability:
  threshold: 0.85                 # Score minimum pour considérer le débat stable
  weights:
    position_delta: 0.5           # Poids du changement de position
    confidence_delta: 0.3         # Poids de la variation de confidence
    argument_novelty: 0.2         # Poids des nouveaux arguments
  confidence_instability_threshold: 30  # Variation > 30 points = instable

# Anti-conformité (§14)
anti_conformity:
  challenge_min_length: 20        # Longueur min du challenge_reason (chars)
  substantive_min_length: 50      # Longueur min pour être "substantive"
  max_retries: 1                  # Nombre de retry si pas de challenge

# Gestion des erreurs (§15)
error_handling:
  provider_timeout_seconds: 60    # Timeout par appel LLM
  provider_max_retries: 1         # Retries avant skip
  rate_limit_backoff: [2, 4, 8]   # Backoff exponentiel (secondes)
  rate_limit_max_retries: 3       # Max retries sur 429
  skip_threshold: 3               # Rounds consécutifs skipés → retrait
  min_active_participants: 2      # En dessous → état error
  user_question_timeout_minutes: 30  # Timeout question utilisateur

# Context window (§16)
context:
  sliding_window_rounds: 2        # Nombre de rounds récents en entier
  summary_tokens_per_participant: 200  # Tokens par participant dans les résumés
  response_reserve_ratio: 0.38    # % de la fenêtre réservé pour la réponse
  protected_zone_tokens: 12000    # Tokens protégés (system prompt, question, etc.)

# Synthétiseur
synthesizer:
  default_model: "claude-opus-46" # Modèle par défaut pour le verdict
  fallback_model: "gpt-52"       # Fallback si le premier échoue

# Streaming
streaming:
  chunk_flush_interval_ms: 50     # Intervalle entre flush des chunks NDJSON
```

### 12.5 Chargement des configs

```python
# app/config/loader.py
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent

def load_config(filename: str) -> dict:
    """Charge un fichier YAML de configuration."""
    path = CONFIG_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)

# Lazy singletons
_prompts = None
_personas = None
_debate = None

def get_prompts() -> dict:
    global _prompts
    if _prompts is None:
        _prompts = load_config("prompts.yaml")
    return _prompts

def get_personas() -> dict:
    global _personas
    if _personas is None:
        _personas = load_config("personas.yaml")
    return _personas

def get_debate_config() -> dict:
    global _debate
    if _debate is None:
        _debate = load_config("debate.yaml")
    return _debate
```

> **Avantage** : pour modifier un prompt, un seuil de stabilité, ou ajouter un persona, il suffit d'éditer le fichier YAML correspondant et de redémarrer le service. Zéro modification de code Python.

### 12.6 Parsing des réponses

Le format utilise des **marqueurs YAML entre délimiteurs** (`---POSITION---` / `---END---`), qui est le meilleur compromis entre :

| Approche                         | Avantage                                                                                                     | Inconvénient                                                                                        | Verdict |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- | ------- |
| JSON mode                        | Parsing fiable                                                                                               | Pas tous les providers le supportent. Bloque le streaming du texte libre.                           | ❌      |
| Function calling                 | Structuré, schema validé                                                                                     | API différente par provider. La réponse doit être 100% structurée (pas de texte libre + structure). | ❌      |
| Texte libre + LLM extraction     | Flexible                                                                                                     | Coûte un appel LLM supplémentaire par tour. Latence.                                                | ❌      |
| **Marqueurs YAML dans le texte** | Compatible tous providers. Texte libre + structure. Streaming du texte fonctionne. Parsing simple par regex. | Le LLM peut mal formater.                                                                           | ✅      |

**Implémentation du parser** :
```python
import re
import yaml

def parse_position(text: str) -> tuple[str, dict]:
    """Sépare le texte libre et le bloc structuré."""
    match = re.search(r'---POSITION---\n(.+?)\n---END---', text, re.DOTALL)
    if not match:
        # Fallback : pas de bloc structuré → position inconnue
        return text, {"thesis": "Non structuré", "confidence": 50, "arguments": []}
    
    prose = text[:match.start()].strip()
    structured = yaml.safe_load(match.group(1))
    return prose, structured
```

**Fallback** : si un LLM ne produit pas le bloc structuré (mauvaise instruction following), l'orchestrateur extrait ce qu'il peut du texte libre et assigne `confidence: 50` par défaut. Le débat continue — on ne crash pas.

---

## 13. Détection de stabilité

> **Note sur l'approche** : Le papier [3] utilise un modèle statistique formel (Beta-Binomial mixture + EM + KS test) pour la détection de stabilité dans un contexte LLM-as-Judge (tâches fermées, réponses binaires correct/incorrect). Pour le débat ouvert d'AdviceRoom (positions textuelles, arguments qualitatifs), nous adoptons une approche simplifiée par heuristiques qui est plus adaptée à notre format structuré de réponses. L'approche Beta-Binomial pourrait être envisagée en v2 si les heuristiques s'avèrent insuffisantes.

### 13.1 Métriques mesurées

Après chaque round complet, le `StabilityDetector` calcule 3 métriques :

| Métrique             | Mesure                                       | Comment                                                                                 |
| -------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------- |
| **Position delta**   | Combien de participants ont changé de thesis | Comparaison textuelle simplifiée (sentiment: pour/mitigé/contre)                        |
| **Confidence delta** | Variation moyenne des scores de confidence   | `mean(abs(conf_round_N - conf_round_N-1))`                                              |
| **Argument novelty** | Des arguments nouveaux apparaissent-ils ?    | Heuristique : nombre de points dans `arguments` qui n'existaient pas au round précédent |

### 13.2 Score de stabilité

```python
def compute_stability(round_n: list[Position], round_n_minus_1: list[Position]) -> float:
    """Retourne un score 0.0 (instable) à 1.0 (totalement stable)."""
    n = len(round_n)
    
    # 1. Position delta (poids 0.5)
    position_changes = sum(
        1 for curr, prev in zip(round_n, round_n_minus_1)
        if curr.sentiment != prev.sentiment  # pour/mitigé/contre
    )
    position_stability = 1.0 - (position_changes / n)
    
    # 2. Confidence delta (poids 0.3)
    avg_conf_delta = sum(
        abs(curr.confidence - prev.confidence)
        for curr, prev in zip(round_n, round_n_minus_1)
    ) / n
    confidence_stability = max(0, 1.0 - (avg_conf_delta / 30))  # 30 points = instable
    
    # 3. Argument novelty (poids 0.2)
    new_args = count_new_arguments(round_n, round_n_minus_1)
    novelty_stability = max(0, 1.0 - (new_args / (n * 2)))  # 2 nouveaux args/participant = instable
    
    return 0.5 * position_stability + 0.3 * confidence_stability + 0.2 * novelty_stability
```

### 13.3 Règle d'arrêt

```python
STABILITY_THRESHOLD = 0.85  # Configurable
MIN_ROUNDS = 2              # Toujours au moins 2 rounds de débat

if round_number >= MIN_ROUNDS and stability_score >= STABILITY_THRESHOLD:
    # → Passer en Phase 3 (Verdict)
```

**Sécurités** :
- **Min 2 rounds** : même si stable dès le round 1, on fait au moins un round de réaction
- **Max N rounds** (défaut 5) : coupe-circuit si le débat ne converge jamais
- **Round 1 toujours exécuté** : pas de stabilité calculée avant d'avoir 2 rounds à comparer

---

## 14. Enforcement anti-conformité

### 14.1 Le problème

La recherche [5] montre que les LLMs tendent au conformisme : ils adoptent la position majoritaire même quand elle est incorrecte. Le prompt seul ("tu DOIS challenger") ne suffit pas — il faut un mécanisme de vérification.

### 14.2 Pipeline de validation post-tour

Après chaque tour en Phase 2, l'orchestrateur exécute :

```python
async def validate_turn(self, turn: Turn, context: DebateContext) -> Turn:
    """Valide qu'un tour respecte les règles anti-conformité."""
    
    position = turn.structured_position
    
    # 1. Vérifier la présence d'un challenge
    has_challenge = (
        position.get("challenged") is not None
        and position.get("challenge_reason") is not None
        and len(position.get("challenge_reason", "")) > 20  # Pas juste "je ne suis pas d'accord"
    )
    
    if not has_challenge:
        # 2. Demander un retry avec un prompt ciblé
        retry_response = await self._request_challenge_retry(turn.participant, context)
        if retry_response.has_challenge:
            turn = turn.merge_challenge(retry_response)
        else:
            # 3. Le LLM refuse de challenger → logger + continuer
            # On ne bloque PAS le débat, mais on flag le tour
            turn.flags.append("missing_challenge")
            turn.structured_position["challenge_quality"] = "absent"
    else:
        # 4. Évaluer la qualité du challenge (superficiel vs substantiel)
        turn.structured_position["challenge_quality"] = self._rate_challenge_quality(position)
    
    return turn
```

### 14.3 Prompt de retry (si challenge absent)

```
Tu n'as pas identifié de faille dans l'argumentation des autres participants.
Le débat AdviceRoom EXIGE que tu challenges au moins un argument.

Voici les positions des autres participants :
{other_positions}

Identifie UNE faiblesse concrète dans l'argumentation de l'un d'entre eux.
Cela peut être : une hypothèse non vérifiée, un risque ignoré, un cas limite non considéré,
une donnée manquante, ou une alternative non explorée.

Réponds UNIQUEMENT avec :
---CHALLENGE---
challenged: [participant_id]
challenge_target: [L'argument contesté]
challenge_reason: [Explication détaillée de la faille]
---END---
```

### 14.4 Évaluation de la qualité du challenge

| Qualité       | Critère                                                                          | Traitement                                           |
| ------------- | -------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `substantive` | `challenge_reason` > 50 chars ET mentionne un fait/risque/alternative spécifique | ✅ Accepté                                           |
| `superficial` | `challenge_reason` < 50 chars OU reformule simplement le désaccord               | ⚠️ Flaggé mais accepté                             |
| `absent`      | Pas de challenge même après retry                                                | ❌ Flaggé, pris en compte dans le score de stabilité |

Les flags sont transmis au synthétiseur de verdict, qui peut noter : "GPT-5.2 n'a pas challengé au round 3, suggérant un possible conformisme".

---

## 15. Gestion des erreurs

### 15.1 Matrice d'erreurs

| Erreur                              | Quand            | Impact                       | Comportement                                                                                                                                                                |
| ----------------------------------- | ---------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Provider timeout**                | Phase 1 ou 2     | Un participant ne répond pas | Attente 60s → retry 1 fois → skip ce participant pour ce round. Événement `{"type": "participant_error", "participant_id": "...", "error": "timeout", "action": "skipped"}` |
| **Provider rate limit (429)**       | Phase 1 ou 2     | Trop de requêtes             | Backoff exponentiel (2s, 4s, 8s) → max 3 retries → skip                                                                                                                     |
| **Provider erreur 500**             | Phase 1 ou 2     | Erreur serveur provider      | Retry 1 fois après 5s → skip                                                                                                                                                |
| **Réponse mal formatée**            | Phase 2          | Pas de bloc `---POSITION---` | Fallback : extraire le texte, assigner confidence 50, pas de challenge → flag `missing_structure`                                                                           |
| **Synthétiseur échoue**             | Phase 3          | Pas de verdict               | Retry avec un modèle de fallback. Si 2ème échec → verdict `{"verdict": "error", "summary": "Le synthétiseur n'a pas pu produire un verdict. Voir le transcript."}`          |
| **Tous les participants en erreur** | Phase 1          | Aucune position initiale     | Débat → état `error`. Message : "Aucun participant n'a pu répondre."                                                                                                        |
| **User question timeout**           | Phase 2 (paused) | L'utilisateur ne répond pas  | Timeout configurable (défaut : 30 min). Événement `user_question_timeout` → le débat reprend SANS la réponse, en informant les participants                                 |
| **S3 indisponible**                 | Toute phase      | Pas de persistence           | Le débat continue en mémoire. Retry S3 en background. Log warning.                                                                                                          |

### 15.2 Participant skipé

Quand un participant est skipé :
- Les autres participants sont informés dans le contexte du round suivant : "(Note : {participant} n'a pas pu répondre à ce round)"
- Le participant skipé est **toujours invité** au round suivant (il peut revenir)
- Si un participant est skipé **3 rounds consécutifs**, il est retiré définitivement du débat
- Le verdict note les participants retirés

### 15.3 Graceful degradation

Le débat reste valide tant qu'il y a **≥ 2 participants actifs**. En dessous, le débat passe en état `error` avec un message explicatif.

---

## 16. Gestion du contexte (Context Window)

### 16.1 Le problème

Avec 5 participants × 5 rounds × outils, le contexte grossit exponentiellement :
- Opening : ~5 × 2K tokens = 10K
- Round 1 : contexte opening (10K) + 5 × 2K = 20K
- Round 2 : contexte (20K) + 5 × 2K = 30K
- Round 5 : ~60-80K tokens de contexte

La fenêtre de contexte minimale (131K pour les modèles SNC) impose une gestion intelligente.

### 16.2 Stratégie de troncation

```
┌─────────────────────────────────────────────────────────┐
│                    BUDGET CONTEXTE                        │
│                                                           │
│  Zone PROTÉGÉE (jamais tronquée) :                       │
│  ┊  System prompt + persona          ~1K tokens          │
│  ┊  Question originale               ~0.5K               │
│  ┊  Réponses utilisateur             ~0.5K               │
│  ┊  Positions initiales (opening)    ~10K (résumées)     │
│                                                           │
│  Zone GLISSANTE (les plus récents en entier) :           │
│  ┊  Round N (courant)                ~10-15K             │
│  ┊  Round N-1                        ~10-15K             │
│                                                           │
│  Zone RÉSUMÉE (rounds anciens) :                         │
│  ┊  Rounds 1..N-2 → résumé par participant              │
│  ┊  "GPT-5.2 (round 1): Pour. Conf 80. Args: TCO,      │
│  ┊   scalabilité. Challenge: risque vendor lock-in."     │
│  ┊  ~200 tokens par participant par round résumé         │
│                                                           │
│  Zone RÉSERVÉE pour la réponse :                         │
│  ┊  ~30-40% de la fenêtre (pour que le LLM puisse       │
│  ┊  produire sa réponse + tool calls)                    │
└─────────────────────────────────────────────────────────┘
```

### 16.3 Budget par zone

Pour un modèle avec 131K tokens de contexte :

| Zone             | Budget    | Contenu                                                |
| ---------------- | --------- | ------------------------------------------------------ |
| Protégée         | 12K (9%)  | System prompt, question, réponses user, opening résumé |
| Glissante        | 30K (23%) | 2 rounds les plus récents en entier                    |
| Résumée          | 40K (30%) | Rounds anciens résumés (200 tokens/participant/round)  |
| Réservée réponse | 49K (38%) | Espace pour la génération + tool calls                 |

### 16.4 Résumé automatique des rounds anciens

Quand un round sort de la zone glissante (round N-2 et avant), il est résumé :

```python
def summarize_round_for_context(round: Round) -> str:
    """Produit un résumé compact d'un round pour le contexte."""
    lines = [f"### Round {round.number} (résumé)"]
    for turn in round.turns:
        pos = turn.structured_position
        line = (
            f"- **{turn.participant.display_name}** : "
            f"{pos.get('sentiment', '?')}. "
            f"Conf {pos.get('confidence', '?')}. "
            f"Args: {', '.join(pos.get('arguments', [])[:3])}. "
        )
        if pos.get("challenged"):
            line += f"Challenge → {pos['challenged']}: {pos.get('challenge_reason', '')[:80]}"
        lines.append(line)
    return "\n".join(lines)
```

### 16.5 Tool results

Les résultats d'outils sont traités spécialement :
- **Round courant** : résultats complets dans le contexte
- **Rounds précédents** : résultats résumés à 1 ligne ("Recherche Perplexity: K8s TCO moyen = 150K€/an pour 50 nodes")
- **Rounds résumés** : tool results omis (seule la conclusion du participant est gardée)

---

## 17. Docker Compose révisé

Suite à la fusion MCP Server + Backend (§4.2.5), le docker-compose est simplifié à 5 services :

```yaml
services:
  waf:
    build: ./waf
    ports:
      - "${WAF_PORT:-8082}:8082"
    depends_on:
      - backend
    networks:
      - adviceroom-net

  backend:
    build: ./application/backend
    expose:
      - "8000"                    # Sert /api/v1/ + /mcp + /admin + /health
    env_file: .env
    depends_on:
      - redis
    networks:
      - adviceroom-net

  frontend:
    build: ./application/frontend
    ports:
      - "${FRONTEND_PORT:-5173}:5173"
    depends_on:
      - backend
    networks:
      - adviceroom-net

  auth:
    build: ./application/auth
    expose:
      - "8001"
    env_file: .env
    depends_on:
      - redis
    networks:
      - adviceroom-net

  redis:
    image: redis:7-alpine
    expose:
      - "6379"
    networks:
      - adviceroom-net

networks:
  adviceroom-net:
    driver: bridge
```

> **Note** : le service `mcp-server` a été supprimé. Le backend sert `/mcp` directement.

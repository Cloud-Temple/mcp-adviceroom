# Changelog

Toutes les modifications notables de ce projet sont documentées dans ce fichier.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionning [Semantic Versioning](https://semver.org/lang/fr/).

## [0.1.0] — 2026-04-22

Première version fonctionnelle complète du moteur de débat multi-LLM.

### Ajouté

#### Moteur de débat (Phase 1 — 20/04)
- **DebateOrchestrator** : protocole 3 phases (OPENING parallèle, DEBATE round-robin, VERDICT synthétiseur dédié)
- **StabilityDetector** : arrêt adaptatif (3 métriques : position delta, confidence delta, argument novelty)
- **VerdictSynthesizer** : consensus / consensus_partiel / dissensus avec fallback model
- **PersonaManager** : 5 personas (Pragmatique, Avocat du diable, Analyste risques, Expert technique, Innovateur)
- **ContextBuilder** : gestion context window (zones protégée/glissante/résumée)
- **Parser YAML** : robuste aux artefacts Markdown (backticks, bold, listes numérotées, tabs)

#### Providers LLM (Phase 1 — 20/04)
- **LLMaaSProvider** : Cloud Temple SecNumCloud (GPT-OSS 120B, Qwen 3.5 27B, Gemma 4 31B)
- **OpenAIProvider** : GPT-5.2 (max_completion_tokens)
- **AnthropicProvider** : Claude Opus 4-6 (fusion messages, tool_use, thinking blocks)
- **GoogleProvider** : Gemini 3.1 Pro
- **LLM Router** : dispatch multi-provider, modèles groupés par catégorie

#### API & MCP (Phase 1 — 20/04)
- **API REST** : 11 endpoints /api/v1/ (debates CRUD, stream NDJSON, export, providers)
- **6 outils MCP** : debate_create, debate_status, debate_list, provider_list, system_health, system_about
- **Streaming NDJSON** : 13 types d'événements temps réel

#### Frontend (Phase 1 — 20/04)
- **React 18 + Vite + Tailwind** : formulaire création, vue temps réel NDJSON, panel verdict

#### Docker (Phase 2 — 20/04)
- **Docker Compose** : 4 services (backend, frontend, redis, WAF)
- **WAF Caddy** : reverse proxy TLS + redirect HTTP→HTTPS

#### MCP Tools Integration (20/04)
- **Bridge MCP Tools** : web_search, calculator, datetime_info pour les LLMs pendant le débat
- **Boucle tool call** : max 10 itérations par tour, graceful degradation

#### Admin & Auth (Phase 3 — 21/04)
- **Auth Bearer Token** : ContextVar + Token Store S3, 3 niveaux (read, write, admin)
- **Admin SPA** : console web dark theme Cloud Temple (/admin)
  - Dashboard : stats débats, tokens, modèles LLM, dernier débat
  - Liste débats : badges verdict, participants par provider, timeline
  - Viewer inline : cartes participants, verdict complet, évolution positions, graphe stabilité
  - Monitoring live : header pulsant, KPI, cartes participants, graphes confiance/stabilité
  - Formulaire débat : cartes grid responsive, auto-activation persona, monitoring NDJSON
  - Export HTML : rendu Markdown complet (titres, liens, listes, blockquotes, LaTeX)
  - 12 tooltips d'aide contextuelle
- **Pile ASGI** : Logging → Admin → HealthCheck → Auth → FastAPI(REST+MCP)

#### CLI (Phase 3 — 21/04)
- **Architecture 3 couches** : Click (scriptable) + Shell interactif (prompt_toolkit) + Display Rich
- **11 commandes** alignées 1:1 sur /admin/api/* + debate start streaming
- **Sortie --json** sur toutes les commandes
- **Auth Bearer** via --token / ADVICEROOM_TOKEN

### Corrigé

#### Fix Anthropic Opus (21/04)
- Fusion des messages user consécutifs (alternance stricte user/assistant)
- Tools TOUJOURS passés aux appels LLM (boucle + retries)
- Réponses tool_use traitées comme valides (pas "vides")
- Tools passés au synthétiseur verdict et anti-conformité
- max_tool_loops 3→10 pour les chaînes de tool calls
- ANTHROPIC_MAX_TOKENS configurable (défaut 64000)
- **8 corrections combinées sur 3 fichiers**, validées E2E

#### Parser YAML (21/04)
- `safe_confidence()` : gère 85, "85", "85/100", "85%", "0.85"
- `_sanitize_yaml_block()` : protège backticks, markdown bold, accolades
- Listes numérotées → items YAML quotés
- Tabs → espaces en pré-traitement
- 4 regex compilées cohérentes (case-insensitive, tirets flexibles)
- Fallback regex pour verdict et challenge
- Clés YAML avec tirets (llm-a, model-b)

#### Backend (21/04)
- Timeout 180s + retry 3x avec backoff (5/10/15s)
- LLM Router initialisé au démarrage (pas de lazy loading)
- Détection réponses vides → Turn avec error explicite
- Corrections llm_models.yaml (gemma4:31b, qwen3.5:27b, context_windows)

### Sécurité

#### Audit V1 complet (21/04) — 22/22 findings traités
- **V1-01** [CRITIQUE] : Auth Depends(require_read/write) sur 13 routes REST
- **V1-02** [CRITIQUE] : Auth check_access/check_write sur 4 outils MCP
- **V1-03** [ÉLEVÉ] : Validation entrée UUID v4, longueurs, bornes, whitelists
- **V1-04** [ÉLEVÉ] : fastmcp≥3.2.0 (4 CVE : command injection, XSS, SSRF)
- **V1-06** [ÉLEVÉ] : Port backend fermé en direct (expose only)
- **V1-07** [ÉLEVÉ] : WAF Coraza compilé (xcaddy + coraza-caddy/v2)
- **V1-08** : Body limit 1 MB admin API
- **V1-09** : Whitelist permissions {read, write, admin}
- **V1-14** : Dockerfile USER non-root (appuser, UID 1001)
- **V1-15** : requirements.lock généré (1246 lignes, SHA256 hashes)
- **V1-17** : Port frontend fermé (expose only)

#### Audit V1.1 — passe de vérification (22/04) — 19 ✅, 2 ⚠️, 0 ❌
- **V1-07** : WAF Coraza **ACTIVÉ** dans le Caddyfile (directive `coraza_waf` + OWASP CRS v4.8.0 + `SecRuleEngine On`)
- **V1-12** : str(e) → messages génériques dans **12 fichiers** (providers, executor, verdict, s3_store, orchestrator)
- Suppression de toutes les fuites d'informations internes (`str(e)`) dans les réponses API
- Audit sécurité complet : SECURITY_AUDIT_V1.md mis à jour (révision V1.1)

### Conformité recherche (22/04) — audit 9 papiers vs code

#### Correction critique : protocoles de débat [4]
- **Mode standard = Within-Round (WR)** : implémenté la vraie same-round visibility — chaque agent voit les turns déjà complétés dans le même round (`context_builder.py` + `orchestrator.py`)
- **Mode parallel = Cross-Round (CR)** : labels corrigés (c'était inversé dans l'architecture)
- **Mode blitz = NI + 1 round** : inchangé, conforme
- `debate.yaml` : commentaires corrigés (WR/CR)
- `architecture.md` : §3.1.1 mis à jour (v1.1), labels et descriptions WR/CR corrigés

### Nettoyé
- Supprimé starter-kit/ (boilerplate plus nécessaire)
- Supprimé scripts/analyze_debate.py (remplacé par CLI `debate get`)
- Supprimé scripts/test_opus_debate.sh (fix Opus validé)
- Supprimé logo-cloudtemple.svg racine (dupliqué dans static/)

---

*Cloud Temple — [cloud-temple.com](https://www.cloud-temple.com)*

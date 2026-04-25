# Changelog

Toutes les modifications notables de ce projet sont documentées dans ce fichier.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionning [Semantic Versioning](https://semver.org/lang/fr/).

## [0.1.6] — 2026-04-25

### Amélioré

- **Parser YAML — Support block scalars** (v0.1.5 déployé, intégré ici) : `_sanitize_yaml_block()` détecte les indicateurs `|` et `>` et préserve le contenu littéral — résout le bug "Extrait par fallback (YAML invalide dans le bloc)" sur les verdicts contenant des `:` ou `[]` dans les champs `summary:` et `recommendation:`
- **Fallback verdict enrichi** : quand `yaml.safe_load` échoue malgré la sanitization, `_fallback_extract_verdict_from_block()` extrait maintenant **tous les champs** par regex (summary, agreement_points, key_insights, recommendation, unresolved_questions) au lieu de seulement verdict + confidence
- **Logging diagnostique** : le bloc YAML brut (tronqué à 500 chars) est maintenant loggé quand le parsing échoue, facilitant le débogage futur

### Ajouté

- **2 tests parser** (+2 tests, 140 total) :
  - `test_verdict_with_block_scalar_summary` : vérifie que `summary: |` avec `:` et `[]` est parsé correctement par YAML
  - `test_verdict_yaml_invalid_fallback_extracts_real_summary` : vérifie que le fallback enrichi extrait le vrai summary + toutes les listes quand le YAML est invalide

---

## [0.1.5] — 2026-04-24

### Corrigé

- **Échappements `\"` dans le rendu** : les guillemets échappés par la sérialisation JSON (`\"conflit majeur\"`) apparaissaient avec des backslashes dans le viewer admin et l'export HTML — nettoyage ajouté dans `md()` et `mdExport()`
- **Dashboard KPI Round X/Y** : `resetDashState()` écrasait `DM_MAX_ROUNDS=5` après le set utilisateur — inversé l'ordre d'appel
- **WAF Coraza** (poussé par Christophe) : méthodes `DELETE/PUT/PATCH` autorisées dans OWASP CRS + `flush_interval -1` sur `/api/*` et `/mcp*` pour le streaming NDJSON

---

## [0.1.4] — 2026-04-24

### Corrigé

- **Dashboard KPI "Round X/Y"** : le max affiché (Y) ne correspondait pas au choix de l'utilisateur — l'orchestrator envoie maintenant `max_rounds` dans l'event `debate_start` NDJSON, et le frontend le lit comme source de vérité
- **Admin inaccessible aux tokens non-admin** : les tokens `read,write` recevaient un 401 sur `/admin/api/*` — séparation des routes en 2 niveaux d'accès :
  - Routes lecture (health, whoami, models, debates, logs) → tout token authentifié
  - Routes gestion tokens (create, revoke, list) → admin uniquement
  - Ajout de `_is_authenticated()` (tout token valide) vs `_is_admin()` (permission admin)

---

## [0.1.3] — 2026-04-24

### Corrigé

- **Rounds max ignorés** : le nombre de rounds choisi dans `/admin` était systématiquement plafonné à 3 en mode parallel (et 5 en standard)
  - Cause racine : `orchestrator.py` bornait le `config_overrides["max_rounds"]` par `min(user_value, mode_cfg.max_rounds)` — le max du mode servait de plafond au lieu de valeur par défaut
  - Fix : le `max_rounds` du mode est maintenant la valeur par défaut uniquement ; l'utilisateur peut choisir jusqu'à 20 rounds (borne API)
- **CLI `--rounds` ignoré** : le flag `--rounds` / `-r` de `debate start` était défini mais jamais passé à `create_debate()` — corrigé dans `commands.py`
- **Shell `--mode` et `--rounds` manquants** : le shell interactif ne parsait ni `--mode` ni `-r` — corrigé dans `shell.py`
- **Admin UI blitz** : le sélecteur de rounds affichait 3 en mode blitz au lieu de 1 — corrigé + ajout option "1 round"

---

## [0.1.2] — 2026-04-22

### Corrigé

- **Token Store S3 — bug critique** : les tokens étaient écrasés à chaque création (seul le dernier persistait)
  - Cause racine : boto3 SigV4 par défaut → `XAmzContentSHA256Mismatch` sur Dell ECS — aucun token n'était sauvé sur S3
  - Fix : `BotoConfig(signature_version="s3")` — SigV2 legacy compatible Dell ECS (même pattern que `s3_store.py`)
  - Fix : `self.load()` avant `create()` et `revoke()` — pattern read-modify-write pour éviter l'écrasement
- **Redirection `/` → `/admin`** : la racine du WAF affichait l'ancien frontend React obsolète — redirige maintenant vers l'admin console (301 permanent)
- **Nettoyage git** : `.clinerules/` retiré du tracking, `.DS_Store` dédupliqué dans `.gitignore`

---

## [0.1.1] — 2026-04-22

### Corrigé

- **Limite question** : augmentée de 10 000 à 50 000 caractères (`debates.py` + `tools.py`) — permet les questions longues (documents, contexte riche)

### Documentation

- **README FR/EN** : badge tests 127→135, ajout section "3 modes de débat", architecture v1.1, WAF Coraza activé, suppression lien cassé SECURITY_AUDIT_METHODOLOGY.md
- **CHANGELOG** : ajout des 3 modes de débat et améliorations UI/CLI dans les sections manquantes

---

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

### Ajouté (22/04)

#### 3 modes de débat — basés sur [4] Debate Protocols
- **standard** (Within-Round) : round-robin séquentiel, same-round visibility, interaction maximale (15-25 min)
- **parallel** (Cross-Round, **défaut**) : `asyncio.gather` par round, 3× plus rapide (3-8 min)
- **blitz** (NI + 1 round) : opening parallèle + 1 round de réaction croisée (~1-2 min)
- 13 fichiers modifiés : orchestrator, context_builder, debate.yaml, models, debates.py, tools.py, serializer, admin API/HTML, CLI
- +8 tests modes E2E (135 total)

#### Améliorations UI et CLI
- **Admin HTML** : badge mode coloré (⚡ blitz rouge, 🔄 parallel bleu, ⚙️ standard orange) dans header et liste débats
- **Admin HTML** : tooltips <?> expliquant les 3 modes, durée formatée mm:ss (plus de secondes brutes)
- **Admin HTML** : export HTML enrichi avec mode et durée formatée
- **CLI display** : colonnes Mode (avec icône) et Durée (Xmin Ys) dans `debate list` et `debate get`

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

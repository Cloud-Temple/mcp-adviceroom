# Changelog

Toutes les modifications notables de ce projet sont documentées dans ce fichier.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionning [Semantic Versioning](https://semver.org/lang/fr/).

## [Non publié]

### Modifié

- **Migration du SDK MCP Python v1 → v2** ([#5](https://github.com/Cloud-Temple/mcp-adviceroom/issues/5)) : `mcp 1.27.0` → `mcp>=2.1.1,<3`
  - **Serveur** : `FastMCP` devient `MCPServer` (`mcp.server.mcpserver`). Les paramètres de transport (`host`, `port`, `streamable_http_path`) n'étant plus acceptés par le constructeur, ils sont passés à `streamable_http_app()`
  - **Simplification** : le contournement v1 qui remettait à `None` le `StreamableHTTPSessionManager` mis en cache est supprimé. En v2, `streamable_http_app()` construit un nouveau manager à chaque appel et l'attache au lifespan du `Starlette` retourné
  - **Client** : `streamablehttp_client` devient `streamable_http_client`. Les paramètres `headers`, `timeout` et `sse_read_timeout` sont supprimés au profit d'un `httpx2.AsyncClient` fourni par l'appelant, et le transport ne renvoie plus que `(read, write)` — le `get_session_id` de v1 disparaît
  - **Robustesse** : un flux SSE qui se ferme sur HTTP 200 sans réponse JSON-RPC terminale remonte désormais une `MCPError(code=CONNECTION_CLOSED)` bornée et distincte d'un échec d'exécution, au lieu de laisser l'appel d'outil bloqué jusqu'au watchdog
  - **Dépendances** : `fastmcp>=3.2.0` est retiré — ce paquet tiers n'était jamais importé et sa contrainte `mcp<2.0` bloquait la migration. `mcp` est désormais déclaré explicitement, avec une borne haute `<3`. `httpx2` arrive comme dépendance du SDK et coexiste avec `httpx`, utilisé par les providers LLM

### Corrigé

- **Isolation des tests — clé de bootstrap** (`tests/conftest.py`) : la suite s'authentifiait avec `"changeme-in-production"`, c'est-à-dire la valeur vulnérable elle-même. Une clé de test dédiée est désormais injectée dans l'environnement, ce qui découple les tests du défaut corrigé et les rend déterministes quel que soit le `.env` présent — les tests d'API échouaient jusqu'ici en 401 lors d'une exécution Docker
- **Providers LLM — Claude Opus 5 et GPT-5.6 Terra** ([#2](https://github.com/Cloud-Temple/mcp-adviceroom/issues/2)) : les deux modèles échouaient en HTTP 400 avant toute génération, le payload contenant systématiquement `temperature`. Les contraintes sont désormais portées par le registre des modèles (`ModelConfig.supports_temperature` et `ModelConfig.extra_params`, résolus par `LLMRouter`), et non par des heuristiques de préfixe de nom
  - `claude-opus-5` : le champ `temperature` est omis, en génération standard, en streaming et dans le retry `thinking`. `claude-opus-4-6` conserve son comportement
  - `gpt-5.6-terra` : `reasoning_effort: "none"` est obligatoire dès que des function tools sont présents — toute valeur de raisonnement active (`low`, `medium`, `high`, `xhigh`) déclenche un HTTP 400. Ce même réglage rend le paramètre `temperature` de nouveau acceptable : les températures modulées par phase (0.7 en débat, 0.8 en anti-conformité, 0.3 pour un verdict factuel) sont donc préservées
  - Les 4 sites d'appel sont couverts (`orchestrator` ×3 et `verdict`), en standard comme en streaming
- **Isolation des tests — clés API** : les deux `test_headers_format` supprimaient définitivement une clé API réelle de l'environnement (`del os.environ[...]`), faisant échouer les tests d'intégration réelle exécutés ensuite. Remplacé par `monkeypatch.setenv`

### Sécurité

Correction des 4 findings **CRITICAL** de l'audit de sécurité du 24/08/2026. Chaque correctif est verrouillé par des tests dont l'échec sur le code vulnérable a été vérifié.

- **Clé de bootstrap admin devinable** (`config/settings.py`) : `admin_bootstrap_key` valait par défaut `"changeme-in-production"`. Le dépôt étant public, tout déploiement ayant omis de définir la variable accordait un **accès admin total** à une valeur connue de quiconque lit le code. Le défaut devient vide, ce qui **désactive** le bootstrap (fail-closed) : l'accès admin passe alors uniquement par les tokens du Token Store S3. Les 6 sites de comparaison sont centralisés dans `Settings.bootstrap_key_matches()`, qui refuse les valeurs vides — sans quoi `hmac.compare_digest("", "")` aurait authentifié un porteur sans aucun secret. L'avertissement de démarrage est déplacé dans `create_app()` : il vivait dans `main()`, qui n'est jamais exécuté puisque le conteneur démarre `uvicorn app.main:app`
- **XSS stocké dans la console admin** (`static/admin.html`) : `loadWebLogs()` insérait `l.path` et `l.method` dans `innerHTML` sans échappement. Ces valeurs proviennent de la requête HTTP brute, journalisée **avant authentification** : un simple `curl` sur une URL forgée déposait un payload qui s'exécutait ensuite chez tout administrateur ouvrant l'onglet Activité, permettant le vol du token Bearer conservé en `localStorage`. Le rendu est reconstruit par API DOM et `textContent`, ce qui ferme la faille par construction. `esc()` échappe désormais aussi les guillemets, insuffisance qui rendait tout contexte d'attribut vulnérable
- **Clé d'API Google en query string** (`services/llm/google.py`) : `GEMINI_API_KEY` transitait dans l'URL (`?key=...`) sur les appels de génération et le test de connectivité, donc en clair dans les journaux d'accès du WAF Caddy, des proxys et des intermédiaires réseau. Elle passe par l'en-tête `x-goog-api-key`
- **Résurrection de tokens révoqués** (`auth/token_store.py`) : `load()` conservait silencieusement un cache périmé sur échec S3, `_save()` avalait toutes les exceptions, et `revoke()` retournait un succès dès que la mise à jour **mémoire** avait abouti. Enchaînés, ces trois défauts faisaient qu'une révocation opérée pendant une indisponibilité S3 était confirmée à l'administrateur sans jamais être écrite — le token redevenant actif au rechargement suivant (TTL 5 min ou redémarrage). Les écritures sont désormais fail-closed : `load(strict=True)` sur les chemins d'écriture, `_save()` lève une `TokenStorePersistenceError`, `create()` et `revoke()` restaurent l'état mémoire en cas d'échec, et l'API admin répond **503** au lieu de confirmer. Les lectures restent tolérantes pour ne pas rendre l'authentification indisponible, mais marquent le store comme dégradé
- **Fuite de contenu utilisateur dans les logs** (`services/tools/executor.py`) : les arguments d'outil — dont la requête de recherche web dérivée de la question de débat — et un aperçu de 200 caractères du résultat étaient journalisés en niveau `INFO`, donc actifs en production. Remplacé par un diagnostic structurel : nom de l'outil, **clés** des arguments et taille du résultat, sans aucune valeur. Couvert par `tests/test_tools_executor.py`
- **Debug Anthropic** : les `print` de diagnostic exposant rôles, tailles, aperçus de texte et, en cas de réponse vide, le contenu complet des réponses, sont remplacés par un `logger.debug` purement structurel

### Remerciements

- [@atilavahedian](https://github.com/atilavahedian) pour le diagnostic du rejet
  `Function tools with reasoning_effort are not supported for gpt-5.6-terra`
  ([PR #3](https://github.com/Cloud-Temple/mcp-adviceroom/pull/3)). Ce rejet masquait
  l'erreur `temperature` décrite dans l'issue #2 et n'apparaissait donc pas dans nos
  reproductions. Sans ce signalement, une valeur `reasoning_effort` inopérante partait
  en production et cassait tous les appels au modèle OpenAI par défaut

---

## [0.2.0] — 2026-05-26

### Corrigé

- **MCP Streamable HTTP** : le lifespan du sous-app FastMCP est maintenant propagé par le parent FastAPI. Corrige le `500 Internal Server Error` avec `RuntimeError: Task group is not initialized` sur `/mcp`
- **Bootstrap admin** : `.env.example` documente `ADMIN_BOOTSTRAP_KEY`; `ADVICEROOM_BOOTSTRAP_KEY` reste accepté comme alias legacy
- **CLI alignée sur `/admin`** : `debate start` et le shell interactif utilisent maintenant `/admin/api/models`, `POST /admin/api/debates` et le stream `/admin/api/debates/{id}/stream`, sans détour par `/api/v1`
- **API admin débats** : ajout de `POST /admin/api/debates`, `GET /admin/api/debates/{id}/stream` et `POST /admin/api/debates/{id}/cancel` pour que la console et la CLI utilisent la même surface protégée
- **Console admin** : pendant un débat en cours, le monitoring live ne masque plus la liste des autres débats
- **Question de débat** : rendu Markdown activé dans le monitoring live et le viewer détail, avec hauteur bornée et scroll vertical pour les très gros prompts
- **Dashboard `/admin`** : la fiche "Dernier débat" rend maintenant Markdown et reste bornée avec ascenseur pour les gros prompts
- **WAF streaming admin** : le stream NDJSON des débats sous `/admin/api/debates/*/stream` est explicitement non bufferisé

### Modifié

- **Release** : version du projet promue en `0.2.0` (backend, frontend, README et package-lock alignés)
- **OpenAI** : modèle par défaut et registre LLM mis à jour de GPT-5.2 vers GPT-5.4 (`gpt-54` / `gpt-5.4`)
- **Documentation** : README FR/EN, design d'architecture et commentaires Docker Compose mis à jour pour refléter la surface principale `/admin/api/*`
- **Dashboard `/admin`** : ajout d'un test de disponibilité des providers/modèles LLM avec latence, statut, détail d'erreur et nombre de modèles configurés/upstream

---

## [0.1.12] — 2026-05-19

### Sécurité

- **Fix routage WAF — exposition UI sans authentification** : le handler catch-all `handle { reverse_proxy frontend:3000 }` dans le Caddyfile exposait l'interface de création de débats (formulaire, liste des modèles LLM) sur **toute URL non répertoriée** (ex : `/adm`, `/anything`) **sans aucune authentification**. En cause : nginx (frontend) répond à toutes les routes avec `index.html` (SPA fallback), et l'app React n'utilise pas de router URL. Corrigé en **supprimant totalement l'accès au frontend React depuis le WAF** — plus aucune route ne proxie vers `frontend:3000`. La racine `/` redirige vers `/admin` (SPA admin.html protégée par auth Bearer). Toute autre URL inconnue retourne **404**

### Corrigé

- **Version frontend** : l'en-tête du frontend React affichait `v0.1.5` au lieu de la version courante

---

## [0.1.11] — 2026-06-05

### Corrigé

- **MCP Streamable HTTP 404** : l'endpoint MCP retournait 404 car `FastMCP` monte son handler interne sur `/mcp` par défaut, combiné avec `fastapi_app.mount("/mcp")` cela créait un double chemin `/mcp/mcp`. Fix : `streamable_http_path="/"` dans le constructeur FastMCP. Le rewrite Caddy `/mcp` → `/mcp/` dans le WAF gère aussi le trailing slash requis par Starlette mount

### Ajouté

- **Section MCP (Agents IA) dans README (FR/EN)** : configuration Cline (`cline_mcp_settings.json`), tableau des timeouts recommandés par mode de débat (blitz 600s, parallel 900s, standard 1800s), liste des 6 outils MCP disponibles

---

## [0.1.10] — 2026-05-05

### Sécurité

- **Isolation owner étendue aux routes admin** : les endpoints `/admin/api/debates` (list, get, delete) du middleware ASGI admin ne vérifiaient pas l'owner — un token non-admin pouvait voir et supprimer tous les débats via l'interface admin. Corrigé : les 3 fonctions reçoivent le token, résolvent le `client_name` via `_get_token_client_name()` et filtrent par owner. Même logique que les routes REST

---

## [0.1.9] — 2026-05-05

### Sécurité

- **Isolation multi-tenant par propriétaire (owner)** : les tokens non-admin ne voient plus que leurs propres débats. Chaque débat enregistre le `client_name` du token créateur comme `owner`. Modèle de permissions : **read** = voit ses débats, **read+write** = voit + lance les siens, **admin** = tout voir/faire. Les débats legacy (sans owner) ne sont accessibles qu'aux admins. Retourne 404 (pas 403) pour ne pas révéler l'existence de débats d'autres utilisateurs
  - 11 endpoints REST protégés : list, active, status, stream, get, export, create, delete, cancel, answer
  - Outil MCP `debate_create` : owner enregistré via `get_current_client_name()`
  - Champ `owner` ajouté au modèle `Debate` et sérialisé dans le JSON S3

### Corrigé

- **Limite question 50K → 200K caractères** : les prompts Advice Room complexes (papier de recherche complet ~108K chars en annexe + questions structurées + données) dépassaient la limite de 50K. Augmenté `_MAX_QUESTION_LENGTH` à 200 000 dans `debates.py` et `tools.py`. Les modèles modernes (128K-1M tokens de fenêtre de contexte) gèrent sans problème des prompts de cette taille

---

## [0.1.8] — 2026-05-03

### Corrigé

- **WAF Coraza 403 sur prompts Markdown très riches** : le seuil d'anomalie CRS à 50 (v0.1.7) restait insuffisant pour les prompts complexes type Advice Room (tableaux ~200 `|`, gras `**`, YAML `{}[]`, Unicode, regex) — score cumulé estimé 1300+. Augmenté `tx.inbound_anomaly_score_threshold` à 5000 (les vraies attaques multi-vecteurs en PL1 scorent bien au-delà)
- **JSON.parse crash sur réponse WAF vide** : quand le WAF retournait un 403 sans body, `resp.json()` crashait avec "unexpected end of data". Ajout d'une gestion robuste des réponses vides dans `admin.html` (startDebate) et `useHttpClient.js` (React hook) avec messages d'erreur explicites

---

## [0.1.7] — 2026-04-26

### Corrigé

- **WAF Coraza 403 sur Markdown riche** : les requêtes POST `/api/v1/debates` avec du contenu Markdown complexe (tableaux `|`, titres `--`, gras `**`, Unicode `Δ`/`→`) déclenchaient des faux positifs OWASP CRS — le seuil d'anomalie par défaut (5) était trop bas pour une API de débat recevant du texte riche. Augmenté `tx.inbound_anomaly_score_threshold` à 50 (les vraies attaques multi-vecteurs scorent 100+ au PL1)

---

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

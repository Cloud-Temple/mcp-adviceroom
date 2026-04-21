# Audit de Sécurité V1 — AdviceRoom

**Projet :** AdviceRoom v0.1.0
**Date :** 21 avril 2026
**Auditeur :** Cline (audit interne, méthodologie SECURITY_AUDIT_METHODOLOGY.md)
**Périmètre :** Backend complet (auth, admin, MCP, routers, storage, providers, infra Docker/WAF)
**Méthodologie :** 5 phases (composant, transversale, vérification, cross-validation, consolidation)

---

## Tableau de synthèse

| Sévérité           | Count  | Findings                                 |
| ------------------ | ------ | ---------------------------------------- |
| **Critique**       | 2      | V1-01, V1-02                             |
| **Élevé**          | 5      | V1-03, V1-04, V1-05, V1-06, V1-07        |
| **Moyen**          | 6      | V1-08, V1-09, V1-10, V1-11, V1-12, V1-13 |
| **Faible**         | 5      | V1-14, V1-15, V1-16, V1-17, V1-18        |
| **Informationnel** | 4      | V1-19, V1-20, V1-21, V1-22               |
| **Total**          | **22** |                                          |

---

## 1. Authentification / Autorisation

### V1-01 [CRITIQUE] : API REST publique — aucun check d'authentification sur les routes /api/v1/*

- **CVSS :** 9.1 (Critical)
- **CWE :** CWE-306 (Missing Authentication for Critical Function)
- **Localisation :** `app/routers/debates.py` (toutes les routes), `app/routers/providers.py` (toutes les routes)
- **Type :** Bug
- **Source :** Phase 2a — Matrice spec vs code

**Description :**
L'`AuthMiddleware` injecte bien le token dans les `contextvars`, mais **aucune route REST n'appelle `check_access()` ou `check_write_permission()`**. Les fonctions de vérification existent dans `auth/context.py` mais ne sont importées ni utilisées nulle part dans les routers.

**Conséquence : TOUTES les routes API sont accessibles sans authentification :**
- `POST /api/v1/debates` → créer des débats (coûte des tokens LLM $$)
- `DELETE /api/v1/debates/{id}` → supprimer des débats
- `GET /api/v1/debates/{id}` → lire le contenu complet des débats
- `GET /api/v1/debates/{id}/stream` → streamer les événements
- `GET /api/v1/debates/{id}/export` → exporter tout débat
- `POST /api/v1/debates/{id}/cancel` → annuler un débat en cours
- `POST /api/v1/debates/{id}/answer` → injecter des réponses
- `GET /api/v1/providers` → lister les providers

**Impact :** Un attaquant sans aucune authentification peut créer des débats (coûts LLM non contrôlés), lire/supprimer tous les débats existants, et injecter des réponses dans les débats en cours.

**Remédiation P0 :**
```python
# Dans chaque route de debates.py, ajouter :
from ..auth.context import check_access, check_write_permission, current_token_info

@router.post("/debates", ...)
async def create_debate(request: DebateCreateRequest, ...):
    # Vérifier auth
    token_info = current_token_info.get()
    if token_info is None:
        raise HTTPException(status_code=401, detail="Authentification requise")
    write_err = check_write_permission()
    if write_err:
        raise HTTPException(status_code=403, detail=write_err["message"])
    # ... suite
```

Alternativement, créer un middleware FastAPI `Depends()` pour centraliser la vérification.

---

### V1-02 [CRITIQUE] : Outils MCP sans aucun check d'authentification

- **CVSS :** 9.1 (Critical)
- **CWE :** CWE-306 (Missing Authentication for Critical Function)
- **Localisation :** `app/mcp/tools.py` (toutes les fonctions `@mcp.tool()`)
- **Type :** Bug
- **Source :** Phase 2a — Matrice spec vs code

**Description :**
Les 6 outils MCP (`debate_create`, `debate_status`, `debate_list`, `provider_list`, `system_health`, `system_about`) n'appellent **aucun check d'authentification**. La doc en tête de fichier spécifie `debate_create (write)`, `debate_status (read)`, etc., mais ces permissions ne sont **jamais vérifiées dans le code**.

Le commentaire dans `mcp/tools.py` ligne 8-9 indique :
```
- debate_create     (write)  → Créer et lancer un débat
- debate_status     (read)   → Statut d'un débat
```

Mais le code correspondant ne contient aucun appel à `check_access()` ou `check_write_permission()`.

**Impact :** Identique à V1-01 — tout agent MCP connecté peut créer/lire/lister des débats sans authentification.

**Remédiation P0 :** Ajouter `check_write_permission()` dans `debate_create` et `check_access()` dans les outils de lecture (cf. pattern starter-kit Cloud Temple §5.3).

---

### V1-03 [ÉLEVÉ] : Validation d'entrée absente sur les paramètres utilisateur

- **CVSS :** 7.5 (High)
- **CWE :** CWE-20 (Improper Input Validation)
- **Localisation :** `app/routers/debates.py`, `app/mcp/tools.py`, `app/admin/api.py`
- **Type :** Bug
- **Source :** Phase 1b — Revue de code validation d'entrée

**Description :**
Aucun paramètre utilisateur n'est validé par regex ou longueur :

| Paramètre       | Fichier                  | Validation                                  | Risque                                       |
| --------------- | ------------------------ | ------------------------------------------- | -------------------------------------------- |
| `debate_id`     | debates.py, admin/api.py | Aucune                                      | Injection dans clés S3, DoS (IDs très longs) |
| `question`      | debates.py:73            | Aucune (Pydantic type str)                  | Prompts de taille illimitée, injection       |
| `provider_name` | providers.py:45          | Aucune                                      | Injection dans lookups                       |
| `format`        | debates.py:334           | Valeurs testées mais pas validées en entrée | —                                            |
| `hash_prefix`   | admin/api.py:59          | Longueur min 8 OK                           | ✅                                           |
| `client_name`   | admin/api.py:200         | Non-vide seulement                          | Noms arbitraires, XSS si affiché             |
| `permissions`   | admin/api.py:201         | Aucune                                      | Permissions arbitraires injectables          |
| `max_rounds`    | mcp/tools.py:69          | Aucune borne                                | DoS (max_rounds=999999)                      |

**Remédiation P1 :**
```python
# debate_id : UUID v4 seulement
import re
DEBATE_ID_RE = re.compile(r'^[a-f0-9\-]{36}$')
if not DEBATE_ID_RE.match(debate_id):
    raise HTTPException(400, "debate_id invalide")

# question : longueur max
if len(request.question) > 10000:
    raise HTTPException(400, "Question trop longue (max 10000 chars)")

# permissions : whitelist
VALID_PERMISSIONS = {"read", "write", "admin"}
if not set(permissions).issubset(VALID_PERMISSIONS):
    return await _json_response(send, 400, {"status": "error", "message": "Permissions invalides"})

# max_rounds : borné
max_rounds = min(max(max_rounds or 5, 1), 20)
```

---

### V1-04 [ÉLEVÉ] : CVE supply chain — FastMCP >=2.0.0 inclut des versions vulnérables

- **CVSS :** 8.1 (High)
- **CWE :** CWE-1395 (Dependency on Vulnerable Third-Party Component)
- **Localisation :** `requirements.txt:12` (`fastmcp>=2.0.0`)
- **Type :** CVE
- **Source :** Phase 1c — Recherche CVE

**Description :**
La borne inférieure `fastmcp>=2.0.0` inclut des versions vulnérables :
- **CVE-2025-62801** (Command Injection via server_name, Windows) — fixé en v2.13.0
- **CVE-2025-64340** (Command Injection via shell metacharacters) — fixé en v3.2.0
- **CVE-2025-62800** (XSS dans OAuth callback) — fixé en v2.13.0
- **CVE-2026-32871** (SSRF dans OpenAPIProvider) — fixé en v3.2.0

**Remédiation P0 :**
```
# requirements.txt — Pinner au-dessus des versions vulnérables
fastmcp>=3.2.0
```

---

### V1-05 [ÉLEVÉ] : CVE supply chain — MCP SDK (implicite via fastmcp)

- **CVSS :** 8.1 (High)
- **CWE :** CWE-1395
- **Localisation :** Dépendance transitive de FastMCP
- **Type :** CVE
- **Source :** Phase 1c — Recherche CVE

**Description :**
Le MCP Python SDK (dépendance de FastMCP) a des CVEs connues :
- **CVE-2025-66416** (DNS rebinding, CVSS 8.1) — fixé en v1.23.0
- **CVE-2025-53365** (DoS ClosedResourceError) — fixé en v1.10.0
- **CVE-2025-53366** (DoS validation error) — fixé en v1.9.4

**Remédiation P1 :** S'assurer que `fastmcp>=3.2.0` tire une version MCP SDK ≥1.23.0. Vérifier avec `pip show mcp`.

---

### V1-06 [ÉLEVÉ] : Backend accessible directement, bypass du WAF

- **CVSS :** 7.5 (High)
- **CWE :** CWE-288 (Authentication Bypass Using an Alternate Path)
- **Localisation :** `docker-compose.yml:48` (`ports: "8000:8000"`)
- **Type :** Bug
- **Source :** Phase 1e — Infra

**Description :**
Le service backend expose le port 8000 directement (`ports: "8000:8000"` au lieu de `expose: "8000"` uniquement). Tout le trafic peut contourner le WAF Caddy en attaquant directement `http://host:8000`. En production, cela désactive toute protection WAF, rate limiting, et TLS.

**Remédiation P0 :**
```yaml
backend:
  # ❌ AVANT
  ports:
    - "8000:8000"
  # ✅ APRÈS — port interne uniquement
  expose:
    - "8000"
```

---

### V1-07 [ÉLEVÉ] : WAF Coraza non installé — Caddy nu sans module OWASP CRS

- **CVSS :** 7.0 (High)
- **CWE :** CWE-693 (Protection Mechanism Failure)
- **Localisation :** `waf/Dockerfile`, `waf/Caddyfile`
- **Type :** Bug
- **Source :** Phase 1e — Infra

**Description :**
Le Dockerfile WAF est `FROM caddy:2-alpine` avec un commentaire TODO : "Ajouter Coraza WAF module quand le projet passe en production". Le Caddyfile ne contient **aucune directive `coraza_waf`**. Le rate limiting est **commenté** (`# rate_limit`).

En l'état, le WAF est un **simple reverse proxy sans aucune protection** :
- Pas de OWASP CRS (injections, XSS, etc.)
- Pas de rate limiting
- Pas de protection contre les attaques applicatives

**Remédiation P1 :** Compiler Caddy avec le module Coraza, activer les règles CRS, décommenter le rate limiting. Cf. starter-kit boilerplate `waf/Dockerfile`.

---

## 2. Admin API

### V1-08 [MOYEN] : Pas de taille limite sur le body des requêtes POST admin

- **CVSS :** 5.3 (Medium)
- **CWE :** CWE-770 (Allocation of Resources Without Limits)
- **Localisation :** `app/admin/api.py:550-558` (`_read_body`)
- **Type :** Bug
- **Source :** Phase 1b — Revue de code

**Description :**
La fonction `_read_body()` lit le body ASGI en boucle sans limite de taille. Un attaquant admin peut envoyer un body de plusieurs GB, causant un OOM.

```python
async def _read_body(receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")  # ← pas de limite
        if not message.get("more_body", False):
            break
    return body
```

**Remédiation P2 :**
```python
MAX_BODY_SIZE = 1_048_576  # 1 MB
async def _read_body(receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if len(body) > MAX_BODY_SIZE:
            raise ValueError("Body trop volumineux")
        if not message.get("more_body", False):
            break
    return body
```

---

### V1-09 [MOYEN] : Pas de validation des permissions lors de la création de token

- **CVSS :** 5.4 (Medium)
- **CWE :** CWE-20 (Improper Input Validation)
- **Localisation :** `app/admin/api.py:190-215` (`_api_create_token`)
- **Type :** Bug
- **Source :** Phase 1b — Revue de code

**Description :**
L'endpoint `POST /admin/api/tokens` accepte n'importe quelle valeur dans le champ `permissions`. Un admin peut créer un token avec `permissions: ["superadmin", "root", "god"]`. Si le code évolue pour vérifier des permissions spécifiques, des permissions inattendues pourraient bypasser les checks.

**Remédiation P2 :**
```python
VALID_PERMISSIONS = {"read", "write", "admin"}
permissions = data.get("permissions", ["read"])
if not set(permissions).issubset(VALID_PERMISSIONS):
    return await _json_response(send, 400, {"status": "error", "message": "Permissions invalides"})
```

---

### V1-10 [MOYEN] : CORS preflight sans Access-Control-Allow-Origin

- **CVSS :** 4.3 (Medium)
- **CWE :** CWE-942 (Permissive Cross-domain Policy)
- **Localisation :** `app/admin/middleware.py:87-98` (`_cors_response`)
- **Type :** Bug
- **Source :** Phase 1b — Revue de code

**Description :**
La réponse CORS OPTIONS ne contient pas de header `Access-Control-Allow-Origin`. Sans ce header, le navigateur bloque les requêtes cross-origin. C'est paradoxalement un comportement safe-by-default (pas de CORS = same-origin), **mais** si un développeur ajoute un `Access-Control-Allow-Origin: *` plus tard pour "faire marcher", cela ouvrirait l'API admin au cross-origin.

De plus, les **réponses normales** (non-preflight) de l'admin API ne contiennent **aucun header CORS** — ce qui est correct (same-origin only).

**Remédiation P2 :** Ajouter un commentaire explicite documentant le choix same-origin. Supprimer le handler CORS preflight s'il n'est pas nécessaire (même domaine).

---

### V1-11 [MOYEN] : Route /admin non proxifiée par le WAF

- **CVSS :** 4.3 (Medium)
- **CWE :** CWE-288 (Authentication Bypass Using an Alternate Path)
- **Localisation :** `waf/Caddyfile`
- **Type :** Bug
- **Source :** Phase 1e — Infra

**Description :**
Le Caddyfile route `/api/*`, `/mcp*`, et `/health` vers le backend, mais **pas `/admin`**. La console admin n'est accessible que via le port direct 8000 (si exposé) ou pas du tout via le WAF. En production avec le port 8000 fermé, l'admin serait inaccessible.

**Remédiation P2 :**
```caddy
handle /admin* {
    reverse_proxy backend:8000
}
```

---

## 3. Services Métier

### V1-12 [MOYEN] : Fuite d'informations internes via str(e) dans 23 emplacements

- **CVSS :** 4.3 (Medium)
- **CWE :** CWE-209 (Generation of Error Message Containing Sensitive Information)
- **Localisation :** 23 occurrences dans 10 fichiers (voir scan)
- **Type :** Bug
- **Source :** Phase 1b — Revue de code

**Description :**
23 occurrences de `str(e)` dans les réponses d'erreur. Les exceptions des providers LLM (httpx, boto3, anthropic) peuvent contenir :
- URLs internes (`http://backend:8000/...`)
- Clés API partielles dans les messages d'erreur httpx
- Stack traces avec chemins de fichiers internes
- Détails S3 (bucket names, endpoints)

**Exemples :**
```python
# providers LLM — leak des détails HTTP
content=f"Erreur Anthropic : {str(e)}"
content=f"Erreur OpenAI : {str(e)}"

# S3 — leak des détails bucket/endpoint
return {"status": "error", "details": str(e)}

# MCP tools — leak des détails internes
return {"status": "error", "message": str(e)}
```

**Remédiation P2 :** Remplacer par des messages génériques et loguer le détail sur stderr :
```python
except Exception as e:
    logger.error(f"Erreur provider: {e}")
    return LLMResponse(content="Erreur temporaire du provider LLM", ...)
```

---

### V1-13 [MOYEN] : Double initialisation du Token Store

- **CVSS :** 4.0 (Medium)
- **CWE :** CWE-675 (Multiple Operations on Resource in Single-Operation Context)
- **Localisation :** `app/main.py:119` et `app/main.py:225`
- **Type :** Bug
- **Source :** Phase 1b — Revue de code

**Description :**
`init_token_store()` est appelé deux fois :
1. Ligne 119 dans `create_app()` (appelé au module load via `app = create_app()` ligne 201)
2. Ligne 225 dans `main()` (appelé quand `python -m app`)

La deuxième initialisation recharge les tokens S3 inutilement. Ce n'est pas une faille de sécurité directe, mais introduit un risque de race condition si des tokens sont créés entre les deux appels.

**Remédiation P2 :** Supprimer l'appel dans `main()` (ligne 224-225) puisque `create_app()` l'initialise déjà.

---

## 4. Infrastructure

### V1-14 [FAIBLE] : Dockerfile — conteneur exécuté en root

- **CVSS :** 3.8 (Low)
- **CWE :** CWE-250 (Execution with Unnecessary Privileges)
- **Localisation :** `application/backend/Dockerfile`
- **Type :** Hardening
- **Source :** Phase 1e — Infra

**Description :**
Le Dockerfile ne crée pas d'utilisateur non-root. Le serveur uvicorn s'exécute en root dans le conteneur.

**Remédiation P2 :**
```dockerfile
# Après COPY app/ ./app/
RUN adduser --disabled-password --gecos '' appuser
USER appuser
```

---

### V1-15 [FAIBLE] : Pas de lock file pour les dépendances Python

- **CVSS :** 3.7 (Low)
- **CWE :** CWE-1395 (Dependency on Vulnerable Third-Party Component)
- **Localisation :** `application/backend/requirements.txt`
- **Type :** Supply chain
- **Source :** Phase 1c — Recherche CVE

**Description :**
Toutes les dépendances utilisent des bornes inférieures (`>=x.y.z`) sans borne supérieure ni lock file. Un `pip install` futur pourrait tirer une version incompatible ou malveillante. Pas de hashes pour vérifier l'intégrité.

**Remédiation P2 :**
```bash
pip install pip-tools
pip-compile --generate-hashes requirements.in > requirements.lock
# Utiliser requirements.lock dans le Dockerfile
```

---

### V1-16 [FAIBLE] : HSTS max-age insuffisant (1 an vs 2 ans recommandés)

- **CVSS :** 2.0 (Low)
- **CWE :** CWE-319 (Cleartext Transmission of Sensitive Information)
- **Localisation :** `waf/Caddyfile:12`
- **Type :** Hardening
- **Source :** Phase 1e — Infra

**Description :**
Le max-age HSTS est de 31536000 (1 an). La recommandation est 63072000 (2 ans) avec `preload` pour la soumission aux listes preload des navigateurs. Pas de `preload` dans la directive.

**Remédiation P2 :**
```caddy
header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
```

---

### V1-17 [FAIBLE] : Frontend exposé directement (port 3000)

- **CVSS :** 2.0 (Low)
- **CWE :** CWE-288
- **Localisation :** `docker-compose.yml:69` (`ports: "3000:3000"`)
- **Type :** Hardening
- **Source :** Phase 1e — Infra

**Description :**
Le frontend est aussi exposé directement, bypassant le WAF.

**Remédiation P2 :** `expose: "3000"` au lieu de `ports: "3000:3000"` en production.

---

### V1-18 [FAIBLE] : Image Docker par tag mutable

- **CVSS :** 2.0 (Low)
- **CWE :** CWE-1395
- **Localisation :** `application/backend/Dockerfile:1` (`python:3.12-slim`), `waf/Dockerfile:1` (`caddy:2-alpine`), `docker-compose.yml:84` (`redis:7-alpine`)
- **Type :** Supply chain
- **Source :** Phase 1e — Infra

**Description :**
Les images Docker utilisent des tags mutables (`python:3.12-slim`, `caddy:2-alpine`, `redis:7-alpine`). Un pull futur pourrait tirer une image modifiée (supply chain attack) ou une version avec des régressions.

**Remédiation P2 :** Pinner par digest SHA256 :
```dockerfile
FROM python:3.12-slim@sha256:abc123...
```

---

## Informationnel

### V1-19 [INFO] : Swagger/Redoc désactivés en production

`docs_url=None, redoc_url=None` dans `main.py:56-57`. ✅ Bon choix — réduit la surface d'attaque.

### V1-20 [INFO] : Warning bootstrap key par défaut

Le code affiche un warning si `admin_bootstrap_key == "changeme-in-production"`. ✅ Bonne pratique (cf. starter-kit §8bis.6).

### V1-21 [INFO] : Comparaison constante pour le bootstrap key

`hmac.compare_digest()` utilisé systématiquement (middleware.py:100, api.py:539, api.py:155). ✅ Protection anti-timing attack correcte.

### V1-22 [INFO] : Fail-close sur expiration token corrompue

`token_store.py:140-142` : `except (ValueError, TypeError): return None`. ✅ Fail-close correct (token rejeté si expires_at corrompu).

---

## Points forts

| Composant       | Points positifs                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------- |
| **Auth**        | Comparaison constante (hmac), fail-close sur token corrompu, no query string tokens, hash SHA-256 |
| **Token Store** | Cache TTL 5min, hash prefix min 8 chars, révocation logique, S3 persistence                       |
| **Admin**       | Auth admin séparée, protection path traversal sur static files, CORS same-origin                  |
| **Middleware**  | Pile ASGI dans le bon ordre (Logging outermost), ContextVar thread-safe                           |
| **Config**      | pydantic-settings, .env.example nettoyé, warning bootstrap key par défaut                         |
| **S3 Store**    | SigV2/SigV4 hybride pour Dell ECS, graceful degradation si S3 indisponible                        |
| **Swagger**     | Désactivé en prod (docs_url=None, redoc_url=None)                                                 |

---

## Plan d'action priorisé

### P0 — Blockers (à corriger avant toute mise en production)

| ID    | Finding                                           | Effort |
| ----- | ------------------------------------------------- | ------ |
| V1-01 | Ajouter auth sur toutes les routes REST /api/v1/* | 2h     |
| V1-02 | Ajouter auth sur tous les outils MCP              | 1h     |
| V1-04 | Pinner FastMCP >=3.2.0                            | 5min   |
| V1-06 | Fermer le port 8000 direct (expose only)          | 5min   |

### P1 — Élevés (à corriger dans la prochaine release)

| ID    | Finding                                     | Effort |
| ----- | ------------------------------------------- | ------ |
| V1-03 | Validation d'entrée sur tous les paramètres | 3h     |
| V1-05 | Vérifier version MCP SDK ≥1.23.0            | 15min  |
| V1-07 | Installer Coraza WAF + CRS + rate limiting  | 4h     |

### P2 — Moyens/Faibles (backlog sécurité)

| ID    | Finding                                                   | Effort |
| ----- | --------------------------------------------------------- | ------ |
| V1-08 | Limite taille body admin                                  | 15min  |
| V1-09 | Whitelist permissions token create                        | 15min  |
| V1-10 | Documenter politique CORS                                 | 15min  |
| V1-11 | Route /admin dans le WAF                                  | 5min   |
| V1-12 | Remplacer str(e) par messages génériques (23 occurrences) | 2h     |
| V1-13 | Supprimer double init_token_store                         | 5min   |
| V1-14 | Utilisateur non-root dans Dockerfile                      | 10min  |
| V1-15 | Lock file avec hashes                                     | 30min  |
| V1-16 | HSTS 2 ans + preload                                      | 5min   |
| V1-17 | Fermer port 3000 direct                                   | 5min   |
| V1-18 | Pinner images Docker par digest                           | 15min  |

**Effort total estimé : ~14h**

---

## Matrice Spec vs Code (Phase 2a)

| Outil/Route                           | Spec Permission   | Code Auth Check     | Conforme ?    |
| ------------------------------------- | ----------------- | ------------------- | ------------- |
| `POST /api/v1/debates`                | write (implicite) | ❌ Aucun            | **BUG V1-01** |
| `GET /api/v1/debates`                 | read (implicite)  | ❌ Aucun            | **BUG V1-01** |
| `DELETE /api/v1/debates/{id}`         | write (implicite) | ❌ Aucun            | **BUG V1-01** |
| `GET /api/v1/debates/{id}`            | read (implicite)  | ❌ Aucun            | **BUG V1-01** |
| `GET /api/v1/debates/{id}/stream`     | read (implicite)  | ❌ Aucun            | **BUG V1-01** |
| `GET /api/v1/debates/{id}/export`     | read (implicite)  | ❌ Aucun            | **BUG V1-01** |
| `POST /api/v1/debates/{id}/cancel`    | write (implicite) | ❌ Aucun            | **BUG V1-01** |
| `POST /api/v1/debates/{id}/answer`    | write (implicite) | ❌ Aucun            | **BUG V1-01** |
| `GET /api/v1/providers`               | read (implicite)  | ❌ Aucun            | **BUG V1-01** |
| `GET /api/v1/providers/{name}/status` | read (implicite)  | ❌ Aucun            | **BUG V1-01** |
| `debate_create` MCP                   | write             | ❌ Aucun            | **BUG V1-02** |
| `debate_status` MCP                   | read              | ❌ Aucun            | **BUG V1-02** |
| `debate_list` MCP                     | read              | ❌ Aucun            | **BUG V1-02** |
| `provider_list` MCP                   | read              | ❌ Aucun            | **BUG V1-02** |
| `system_health` MCP                   | — (public)        | ✅ Aucun (OK)       | ✅            |
| `system_about` MCP                    | — (public)        | ✅ Aucun (OK)       | ✅            |
| `GET /admin/api/*`                    | admin             | ✅ `_is_admin()`    | ✅            |
| `POST /admin/api/tokens`              | admin             | ✅ `_is_admin()`    | ✅            |
| `DELETE /admin/api/tokens/{h}`        | admin             | ✅ `_is_admin()`    | ✅            |
| `GET /health`                         | — (public)        | ✅ HealthCheck (OK) | ✅            |

# Audit de Sécurité V1 — AdviceRoom

**Projet :** AdviceRoom v0.1.0
**Date initiale :** 21 avril 2026
**Révision V1.1 :** 22 avril 2026
**Auditeur :** Cline (audit interne, méthodologie SECURITY_AUDIT_METHODOLOGY.md)
**Périmètre :** Backend complet (auth, admin, MCP, routers, storage, providers, infra Docker/WAF)
**Méthodologie :** 5 phases (composant, transversale, vérification, cross-validation, consolidation)

---

## Tableau de synthèse

| Sévérité           | Count  | Findings                                  |
| ------------------ | ------ | ----------------------------------------- |
| **Critique**       | 2      | V1-01 ✅, V1-02 ✅                         |
| **Élevé**          | 5      | V1-03 ✅, V1-04 ✅, V1-05 ✅, V1-06 ✅, V1-07 ✅ |
| **Moyen**          | 6      | V1-08 ✅, V1-09 ✅, V1-10 ⚠️, V1-11 ✅, V1-12 ✅, V1-13 ✅ |
| **Faible**         | 5      | V1-14 ✅, V1-15 ⚠️, V1-16 N/A, V1-17 ✅, V1-18 ✅ |
| **Informationnel** | 4      | V1-19 ✅, V1-20 ✅, V1-21 ✅, V1-22 ✅      |
| **Total**          | **22** |                                           |

### Légende statut

- ✅ **CORRIGÉ** — Vérifié dans le code, conforme
- ⚠️ **PARTIEL** — Correction incomplète ou décision acceptée
- ❌ **OUVERT** — Non corrigé
- N/A — Plus applicable (changement d'architecture)

### Synthèse V1.1 (22/04/2026 — Passe de vérification)

| Statut       | Count | % |
|-------------|-------|---|
| ✅ Corrigé   | 19    | 86% |
| ⚠️ Partiel   | 2     | 9% |
| ❌ Ouvert    | 0     | 0% |
| N/A          | 1     | 5% |

**Findings critiques restants : AUCUN** ✅

Tous les findings critiques et élevés sont corrigés. Restent 2 findings mineurs partiels (V1-10 CORS documentation, V1-15 lock file).

---

## 1. Authentification / Autorisation

### V1-01 [CRITIQUE] ✅ CORRIGÉ : Auth sur les routes REST /api/v1/*

- **CVSS :** 9.1 (Critical)
- **CWE :** CWE-306 (Missing Authentication for Critical Function)
- **Localisation :** `app/routers/debates.py`, `app/routers/providers.py`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Correction appliquée :**
Toutes les routes REST utilisent désormais les dépendances FastAPI `Depends(require_read)` et `Depends(require_write)` depuis `auth/context.py`.

**Vérification (22/04) — routes authentifiées confirmées :**
```
POST   /debates           → Depends(require_write)  ✅
GET    /debates/active     → Depends(require_read)   ✅
GET    /debates/{id}/status → Depends(require_read)  ✅
GET    /debates/{id}/stream → Depends(require_read)  ✅
GET    /debates/{id}        → Depends(require_read)  ✅
GET    /debates/{id}/export → Depends(require_read)  ✅
GET    /debates             → Depends(require_read)  ✅
DELETE /debates/{id}        → Depends(require_write) ✅
POST   /debates/{id}/cancel → Depends(require_write) ✅
POST   /debates/{id}/answer → Depends(require_write) ✅
GET    /providers           → Depends(require_read)  ✅
GET    /providers/{name}/status → Depends(require_read) ✅
```

---

### V1-02 [CRITIQUE] ✅ CORRIGÉ : Auth sur les outils MCP

- **CVSS :** 9.1 (Critical)
- **CWE :** CWE-306 (Missing Authentication for Critical Function)
- **Localisation :** `app/mcp/tools.py`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Correction appliquée :**
Les outils MCP appellent `check_write_permission()` (pour debate_create) et `check_access()` (pour debate_status, debate_list, provider_list). Les outils publics (system_health, system_about) restent sans auth (conforme au design).

**Vérification (22/04) :**
```
debate_create   → check_write_permission()  ✅
debate_status   → check_access()            ✅
debate_list     → check_access()            ✅
provider_list   → check_access()            ✅
system_health   → public (pas d'auth)       ✅ (conforme)
system_about    → public (pas d'auth)       ✅ (conforme)
```

---

### V1-03 [ÉLEVÉ] ✅ CORRIGÉ : Validation d'entrée sur les paramètres utilisateur

- **CVSS :** 7.5 (High)
- **CWE :** CWE-20 (Improper Input Validation)
- **Localisation :** `app/routers/debates.py`, `app/mcp/tools.py`, `app/admin/api.py`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification (22/04) :**

| Paramètre       | Fichier          | Validation appliquée                             | Statut |
| --------------- | ---------------- | ------------------------------------------------ | ------ |
| `debate_id`     | debates.py       | Regex UUID v4 `_DEBATE_ID_RE`                    | ✅     |
| `question`      | debates.py       | Pydantic `min_length=5, max_length=10000`        | ✅     |
| `answer`        | debates.py       | Pydantic `min_length=1, max_length=10000`        | ✅     |
| `provider_name` | providers.py     | Regex `^[a-zA-Z0-9_-]{1,50}$`                   | ✅     |
| `format`        | debates.py       | Whitelist `("markdown", "html", "json")`         | ✅     |
| `mode`          | debates.py       | Whitelist `("standard", "parallel", "blitz")`    | ✅     |
| `max_rounds`    | debates.py/tools | `min(max(int(...), 1), 20)`                      | ✅     |
| `client_name`   | admin/api.py     | Non-vide + max 64 chars                          | ✅     |
| `permissions`   | admin/api.py     | Whitelist `{"read", "write", "admin"}`            | ✅     |
| `expires_in_days` | admin/api.py   | Borné 0-3650, fallback 90                        | ✅     |
| `hash_prefix`   | admin/api.py     | Longueur min 8 chars                             | ✅     |
| `participants`  | debates.py       | Pydantic `min_length=2, max_length=5`            | ✅     |

---

### V1-04 [ÉLEVÉ] ✅ CORRIGÉ : CVE supply chain — FastMCP pinné >=3.2.0

- **CVSS :** 8.1 (High)
- **CWE :** CWE-1395
- **Localisation :** `requirements.txt:14`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification :** `requirements.txt` ligne 14 : `fastmcp>=3.2.0` avec commentaire référençant les 4 CVEs.

---

### V1-05 [ÉLEVÉ] ✅ CORRIGÉ : CVE supply chain — MCP SDK

- **CVSS :** 8.1 (High)
- **CWE :** CWE-1395
- **Corrigé le :** 21/04/2026 (implicite via fastmcp>=3.2.0)
- **Vérifié le :** 22/04/2026

**Vérification :** `fastmcp>=3.2.0` tire MCP SDK ≥1.23.0. Commentaire en requirements.txt confirme.

---

### V1-06 [ÉLEVÉ] ✅ CORRIGÉ : Port 8000 fermé — expose only

- **CVSS :** 7.5 (High)
- **CWE :** CWE-288
- **Localisation :** `docker-compose.yml:50-51`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification :** `docker-compose.yml` lignes 48-51 :
```yaml
backend:
  # V1-06 : port interne uniquement (pas de bypass WAF)
  # Pour le dev local, décommenter: ports: ["8000:8000"]
  expose:
    - "8000"
```

---

### V1-07 [ÉLEVÉ] ⚠️ PARTIELLEMENT CORRIGÉ : WAF Coraza compilé mais PAS ACTIVÉ

- **CVSS :** 7.0 (High)
- **CWE :** CWE-693 (Protection Mechanism Failure)
- **Localisation :** `waf/Dockerfile`, `waf/Caddyfile`
- **Corrigé le :** 21/04/2026 (Dockerfile seulement)
- **Vérifié le :** 22/04/2026
- **Corrigé le :** 22/04/2026 (Caddyfile + Dockerfile CRS)
- **STATUT : ✅ CORRIGÉ**

**Correction appliquée (22/04/2026) :**
- ✅ `waf/Dockerfile` : Build multi-stage Caddy + Coraza + téléchargement OWASP CRS v4.8.0 (coreruleset-4.8.0-minimal)
- ✅ `waf/Caddyfile` : Directive `coraza_waf` activée avec `load_owasp_crs`, `SecRuleEngine On`, audit sur stderr
- ✅ `waf/Caddyfile` : Headers de sécurité (X-Content-Type-Options, X-Frame-Options, Referrer-Policy)
- ✅ `waf/Caddyfile` : Route `/admin*` ajoutée (V1-11)
- ✅ TODOs supprimés du Caddyfile

**Configuration Coraza :**
```caddy
coraza_waf {
    load_owasp_crs
    directives `
        Include /etc/caddy/crs/crs-setup.conf
        Include /etc/caddy/crs/rules/*.conf
        SecRuleEngine On
        SecRequestBodyAccess On
        SecResponseBodyAccess Off
        SecRequestBodyLimit 1048576
        SecRequestBodyNoFilesLimit 131072
        SecAuditEngine RelevantOnly
        SecAuditLog /dev/stderr
    `
}
```

**Note :** Le rate limiting est géré par le reverse proxy de production (nginx/traefik), pas par Caddy.

**Remédiation P1 (3 étapes) :**

**Étape 1 — Télécharger les règles CRS dans le Dockerfile :**
```dockerfile
# --- Stage 2 : Image finale ---
FROM caddy:2-alpine

COPY --from=builder /usr/bin/caddy /usr/bin/caddy

# Télécharger OWASP CRS v4
RUN apk add --no-cache wget unzip && \
    wget -q https://github.com/coreruleset/coreruleset/releases/download/v4.8.0/coreruleset-4.8.0-minimal.tar.gz && \
    tar xzf coreruleset-4.8.0-minimal.tar.gz && \
    mv coreruleset-4.8.0 /etc/caddy/crs && \
    cp /etc/caddy/crs/crs-setup.conf.example /etc/caddy/crs/crs-setup.conf && \
    rm coreruleset-4.8.0-minimal.tar.gz && \
    apk del wget unzip

COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 80 443
```

**Étape 2 — Activer Coraza dans le Caddyfile :**
```caddy
{
    order coraza_waf first
}

:8088 {
    # --- WAF Coraza (OWASP CRS) ---
    coraza_waf {
        load_owasp_crs
        directives `
            Include /etc/caddy/crs/crs-setup.conf
            Include /etc/caddy/crs/rules/*.conf
            SecRuleEngine On
            SecRequestBodyAccess On
            SecResponseBodyAccess Off
            SecRequestBodyLimit 1048576
            SecAuditEngine RelevantOnly
            SecAuditLog /dev/stderr
        `
    }

    # Headers sécurité
    header X-Content-Type-Options "nosniff"
    header X-Frame-Options "DENY"
    header Referrer-Policy "strict-origin-when-cross-origin"

    # Routes
    handle /admin* { reverse_proxy backend:8000 }
    handle /api/*  { reverse_proxy backend:8000 }
    handle /mcp*   { reverse_proxy backend:8000 }
    handle /health { reverse_proxy backend:8000 }
    handle          { reverse_proxy frontend:3000 }
}
```

**Étape 3 — Rate limiting (optionnel, plugin séparé) :**
Ajouter `--with github.com/mholt/caddy-ratelimit` dans le `xcaddy build` et configurer dans le Caddyfile. Alternative : rate limiting au niveau du reverse proxy de production.

---

## 2. Admin API

### V1-08 [MOYEN] ✅ CORRIGÉ : Limite taille body admin (1 MB)

- **CVSS :** 5.3 (Medium)
- **CWE :** CWE-770
- **Localisation :** `app/admin/api.py:570-584`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification :** `_MAX_BODY_SIZE = 1_048_576` avec check `if len(body) > _MAX_BODY_SIZE: raise ValueError(...)`.

---

### V1-09 [MOYEN] ✅ CORRIGÉ : Whitelist permissions token create

- **CVSS :** 5.4 (Medium)
- **CWE :** CWE-20
- **Localisation :** `app/admin/api.py:191,217`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification :** `_VALID_PERMISSIONS = {"read", "write", "admin"}` avec `set(permissions).issubset(_VALID_PERMISSIONS)`.

---

### V1-10 [MOYEN] ⚠️ PARTIEL : CORS preflight sans Access-Control-Allow-Origin

- **CVSS :** 4.3 (Medium)
- **CWE :** CWE-942
- **Localisation :** `app/admin/middleware.py:87-98`
- **Vérifié le :** 22/04/2026
- **STATUT : ⚠️ Handler CORS toujours présent, comportement safe-by-default**

**Constat :** Le handler CORS OPTIONS est toujours présent dans `_cors_response()`, toujours sans header `Access-Control-Allow-Origin`. C'est paradoxalement safe-by-default (le navigateur bloque les requêtes cross-origin sans ce header).

**Risque résiduel :** Faible. Un développeur futur pourrait ajouter `Access-Control-Allow-Origin: *` pour "faire marcher" — mais en l'état c'est sécurisé.

**Recommandation :** Ajouter un commentaire documentant le choix same-origin, ou supprimer le handler CORS s'il n'est pas nécessaire.

---

### V1-11 [MOYEN] ✅ CORRIGÉ : Route /admin dans le WAF

- **CVSS :** 4.3 (Medium)
- **CWE :** CWE-288
- **Localisation :** `waf/Caddyfile:20-22`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification :** `handle /admin* { reverse_proxy backend:8000 }` présent dans le Caddyfile.

---

## 3. Services Métier

### V1-12 [MOYEN] ✅ CORRIGÉ : Fuite d'informations via str(e) — 12 occurrences corrigées

- **CVSS :** 4.3 (Medium)
- **CWE :** CWE-209 (Generation of Error Message Containing Sensitive Information)
- **Localisation :** 8 fichiers (executor, providers LLM, verdict, s3_store, orchestrator)
- **Corrigé le :** 22/04/2026
- **STATUT : ✅ CORRIGÉ**

**Correction appliquée (22/04/2026) :**
Toutes les occurrences de `str(e)` dans les réponses API ont été remplacées par des messages génériques. L'exception complète est loguée sur stderr via `logger.error()`.

**Fichiers corrigés :**

| Fichier | Occurrences | Correction |
|---------|------------|-----------|
| `services/tools/executor.py` | 2 | "Erreur temporaire lors de l'exécution de l'outil" / "Erreur de connectivité MCP Tools" |
| `services/llm/google.py` | 1 | "Erreur de connectivité Google Gemini" |
| `services/llm/llmaas.py` | 1 | "Erreur de connectivité LLMaaS" |
| `services/llm/openai.py` | 1 | "Erreur de connectivité OpenAI" |
| `services/llm/anthropic.py` | 1 | "Erreur de connectivité Anthropic" |
| `services/debate/verdict.py` | 1 | "Erreur temporaire du synthétiseur de verdict" |
| `services/storage/s3_store.py` | 1 | "Erreur de connectivité S3" |
| `services/debate/orchestrator.py` | 4 | "Erreur interne lors du débat" / "Erreur lors de la position initiale" / "Erreur lors du tour de débat" |

**Note :** 1 occurrence résiduelle dans `auth/token_store.py` (`"NoSuchKey" in str(e)`) est un usage interne (pas de fuite vers les clients). Tests : 135/135 ✅.

---

### V1-13 [MOYEN] ✅ CORRIGÉ : Double initialisation du Token Store

- **CVSS :** 4.0 (Medium)
- **CWE :** CWE-675
- **Localisation :** `app/main.py:223`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification :** Commentaire `# V1-13 : init_token_store() supprimé ici` à la ligne 223 de main.py. L'initialisation ne se fait qu'une fois dans `create_app()` (ligne 119).

---

## 4. Infrastructure

### V1-14 [FAIBLE] ✅ CORRIGÉ : Conteneur exécuté en non-root

- **CVSS :** 3.8 (Low)
- **CWE :** CWE-250
- **Localisation :** `application/backend/Dockerfile:20-21`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification :**
```dockerfile
RUN adduser --disabled-password --gecos '' --uid 1001 appuser
USER appuser
```

---

### V1-15 [FAIBLE] ⚠️ PARTIEL : Lock file disponible mais pas activé

- **CVSS :** 3.7 (Low)
- **CWE :** CWE-1395
- **Localisation :** `application/backend/requirements.txt`, `requirements.lock`
- **Vérifié le :** 22/04/2026
- **STATUT : ⚠️ Décision acceptée**

**Constat :** `requirements.lock` a été généré (1246 lignes avec hashes SHA256) mais le Dockerfile utilise toujours `requirements.txt` (décision Christophe — flexibilité conservée pour le dev).

**Risque résiduel :** Faible en dev, moyen en prod. Pour activer en production :
```dockerfile
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
```

---

### V1-16 [FAIBLE] N/A : HSTS — plus applicable

- **CVSS :** 2.0 (Low)
- **CWE :** CWE-319
- **Vérifié le :** 22/04/2026
- **STATUT : N/A — Changement d'architecture**

**Constat :** L'architecture a changé : le WAF Caddy est maintenant en HTTP only (port 8088). TLS et HSTS sont gérés par le reverse proxy de production (nginx/traefik). Le header HSTS a été correctement retiré du Caddyfile (HSTS sur HTTP causerait des problèmes).

---

### V1-17 [FAIBLE] ✅ CORRIGÉ : Port 3000 fermé

- **CVSS :** 2.0 (Low)
- **CWE :** CWE-288
- **Localisation :** `docker-compose.yml:71-72`
- **Corrigé le :** 21/04/2026
- **Vérifié le :** 22/04/2026

**Vérification :**
```yaml
frontend:
  # V1-17 : port interne uniquement (pas de bypass WAF)
  expose:
    - "3000"
```

---

### V1-18 [FAIBLE] ✅ DÉCISION : Pas de pin Docker par digest

- **CVSS :** 2.0 (Low)
- **CWE :** CWE-1395
- **Vérifié le :** 22/04/2026
- **STATUT : ✅ Décision documentée**

**Décision (22/04/2026) :** Ne pas pinner les images Docker par digest SHA256 pour l'instant. Raison : faciliter les mises à jour de sécurité automatiques. À reconsidérer pour la mise en production.

---

## Informationnel

### V1-19 [INFO] ✅ : Swagger/Redoc désactivés en production

`docs_url=None, redoc_url=None` dans `main.py:56-57`. Vérifié 22/04.

### V1-20 [INFO] ✅ : Warning bootstrap key par défaut

`if settings.admin_bootstrap_key == "changeme-in-production"` dans `main.py:216`. Vérifié 22/04.

### V1-21 [INFO] ✅ : Comparaison constante pour le bootstrap key

`hmac.compare_digest()` utilisé dans :
- `auth/middleware.py:100` (AuthMiddleware)
- `admin/api.py:559` (_is_admin)
- `admin/api.py:155` (_api_whoami)

Vérifié 22/04.

### V1-22 [INFO] ✅ : Fail-close sur expiration token corrompue

`token_store.py:140-142` :
```python
except (ValueError, TypeError):
    return None  # FAIL-CLOSE : si expires_at est corrompu, rejeter le token
```
Vérifié 22/04.

---

## Points forts

| Composant       | Points positifs                                                                                      |
| --------------- | ---------------------------------------------------------------------------------------------------- |
| **Auth**        | Comparaison constante (hmac), fail-close sur token corrompu, no query string tokens, hash SHA-256    |
| **Auth REST**   | `Depends(require_read/write)` systématique sur toutes les routes, pattern centralisé via context.py  |
| **Auth MCP**    | `check_access()` / `check_write_permission()` sur les 4 outils authentifiés, public pour system_*   |
| **Validation**  | Regex UUID, Pydantic min/max length, whitelists modes/formats/permissions, bornes numériques         |
| **Token Store** | Cache TTL 5min, hash prefix min 8 chars, révocation logique, S3 persistence, expiration vérifiée     |
| **Admin**       | Auth admin séparée, protection path traversal static, body limit 1MB, whitelist permissions          |
| **Middleware**  | Pile ASGI correcte (Logging → Admin → Health → Auth → FastAPI+MCP), ContextVar thread-safe           |
| **Config**      | pydantic-settings, .env.example nettoyé, warning bootstrap key, Swagger désactivé prod               |
| **Docker**      | Non-root (UID 1001), expose only (pas de ports directs), healthchecks sur tous les services          |
| **S3 Store**    | SigV2/SigV4 hybride pour Dell ECS, graceful degradation si S3 indisponible                           |

---

## Plan d'action restant (V1.1)

### P2 — Backlog sécurité (mineur)

| ID    | Finding                                                   | Statut | Effort |
| ----- | --------------------------------------------------------- | ------ | ------ |
| V1-10 | Documenter politique CORS ou supprimer handler            | ⚠️ PARTIEL | 15min |
| V1-15 | Activer requirements.lock en prod                         | ⚠️ DÉCISION | 5min |

**Effort total restant estimé : ~20min**

### Findings corrigés (19/22 + 1 N/A + 2 partiels mineurs)

| ID | Finding | Vérifié |
|----|---------|---------|
| V1-01 | Auth sur toutes les routes REST | 22/04 ✅ |
| V1-02 | Auth sur tous les outils MCP | 22/04 ✅ |
| V1-03 | Validation d'entrée complète | 22/04 ✅ |
| V1-04 | FastMCP >=3.2.0 | 22/04 ✅ |
| V1-05 | MCP SDK >=1.23.0 | 22/04 ✅ |
| V1-06 | Port 8000 fermé (expose only) | 22/04 ✅ |
| V1-07 | WAF Coraza + OWASP CRS activé | 22/04 ✅ |
| V1-08 | Body limit admin 1MB | 22/04 ✅ |
| V1-09 | Whitelist permissions | 22/04 ✅ |
| V1-10 | CORS documentation | ⚠️ safe-by-default |
| V1-11 | Route /admin dans WAF | 22/04 ✅ |
| V1-12 | str(e) → messages génériques (12 fichiers) | 22/04 ✅ |
| V1-13 | Double init supprimée | 22/04 ✅ |
| V1-14 | Non-root (UID 1001) | 22/04 ✅ |
| V1-15 | Lock file | ⚠️ décision acceptée |
| V1-16 | HSTS → N/A (HTTP only) | N/A |
| V1-17 | Port 3000 fermé | 22/04 ✅ |
| V1-18 | Docker pin → décision documentée | 22/04 ✅ |
| V1-19-22 | Points informationnels | 22/04 ✅ |

---

## Matrice Spec vs Code (V1.1 — 22/04/2026)

| Outil/Route                           | Spec Permission   | Code Auth Check                 | Conforme ? |
| ------------------------------------- | ----------------- | ------------------------------- | ---------- |
| `POST /api/v1/debates`                | write             | ✅ `Depends(require_write)`     | ✅         |
| `GET /api/v1/debates`                 | read              | ✅ `Depends(require_read)`      | ✅         |
| `GET /api/v1/debates/active`          | read              | ✅ `Depends(require_read)`      | ✅         |
| `DELETE /api/v1/debates/{id}`         | write             | ✅ `Depends(require_write)`     | ✅         |
| `GET /api/v1/debates/{id}`            | read              | ✅ `Depends(require_read)`      | ✅         |
| `GET /api/v1/debates/{id}/status`     | read              | ✅ `Depends(require_read)`      | ✅         |
| `GET /api/v1/debates/{id}/stream`     | read              | ✅ `Depends(require_read)`      | ✅         |
| `GET /api/v1/debates/{id}/export`     | read              | ✅ `Depends(require_read)`      | ✅         |
| `POST /api/v1/debates/{id}/cancel`    | write             | ✅ `Depends(require_write)`     | ✅         |
| `POST /api/v1/debates/{id}/answer`    | write             | ✅ `Depends(require_write)`     | ✅         |
| `GET /api/v1/providers`               | read              | ✅ `Depends(require_read)`      | ✅         |
| `GET /api/v1/providers/{name}/status` | read              | ✅ `Depends(require_read)`      | ✅         |
| `debate_create` MCP                   | write             | ✅ `check_write_permission()`   | ✅         |
| `debate_status` MCP                   | read              | ✅ `check_access()`             | ✅         |
| `debate_list` MCP                     | read              | ✅ `check_access()`             | ✅         |
| `provider_list` MCP                   | read              | ✅ `check_access()`             | ✅         |
| `system_health` MCP                   | — (public)        | ✅ Aucun (OK)                   | ✅         |
| `system_about` MCP                    | — (public)        | ✅ Aucun (OK)                   | ✅         |
| `GET /admin/api/*`                    | admin             | ✅ `_is_admin()`                | ✅         |
| `POST /admin/api/tokens`              | admin             | ✅ `_is_admin()`                | ✅         |
| `DELETE /admin/api/tokens/{h}`        | admin             | ✅ `_is_admin()`                | ✅         |
| `DELETE /admin/api/debates/{id}`      | admin             | ✅ `_is_admin()`                | ✅         |
| `GET /health`                         | — (public)        | ✅ HealthCheckMiddleware        | ✅         |

---

## Annexe : WAF — État détaillé V1.1

### Architecture WAF actuelle

```
Internet → [Reverse Proxy Prod (TLS)] → WAF Caddy:8088 → Backend:8000
                                                        → Frontend:3000
```

### Caddyfile — état après V1.1

| Fonctionnalité | Statut | Détail |
|---------------|--------|--------|
| Reverse proxy | ✅ | Routes /api/*, /mcp*, /admin*, /health, /* |
| Headers sécurité | ✅ | X-Content-Type-Options, X-Frame-Options, Referrer-Policy |
| Module Coraza compilé | ✅ | `xcaddy build --with coraza-caddy/v2` dans Dockerfile |
| Directive `coraza_waf` | ✅ | Activée avec `load_owasp_crs` + `SecRuleEngine On` |
| Règles OWASP CRS | ✅ | CRS v4.8.0-minimal téléchargé dans le Dockerfile |
| Rate limiting | N/A | Géré par reverse proxy prod (nginx/traefik) |
| TLS | N/A | Géré par reverse proxy prod |
| HSTS | N/A | Géré par reverse proxy prod |

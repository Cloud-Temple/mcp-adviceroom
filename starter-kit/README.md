# 🚀 Starter Kit — Créer un serveur MCP Cloud Temple

> **Audience** : Assistant IA (Cline, Cursor, etc.) ou développeur humain.
> Ce guide contient le **pattern architectural** et les **conventions** pour créer
> un nouveau serveur MCP chez Cloud Temple, avec une CLI complète.
>
> **Références vivantes** :
> - [mcp-tools](https://github.com/chrlesur/mcp-tools) — bibliothèque d'outils exécutables pour agents IA
> - [mcp-office](https://github.com/Cloud-Temple/mcp-office.git) — génération de documents Office (PPTX, DOCX, XLSX, PDF, HTML)
>
> Le boilerplate inclus intègre les **correctifs de sécurité** et les **leçons de production**
> découverts lors du développement de mcp-office (audit sécurité complet v0.4.2).

---

## 1. Qu'est-ce qu'un serveur MCP ?

### Le protocole MCP (Model Context Protocol)
MCP est un protocole ouvert qui permet à des **agents IA** (Cline, Claude Desktop,
curseurs IA, agents autonomes) d'appeler des **outils** exposés par un serveur.

Un serveur MCP Cloud Temple :
- Expose des **outils** (`@mcp.tool()`) via **Streamable HTTP** (`/mcp`)
- Est consommé par des **clients MCP** (agents IA, CLI, applications web)
- Fournit un domaine métier spécifique (mémoire, monitoring, déploiement, etc.)
- Inclut une **console admin web** (`/admin`) pour l'administration

### Pourquoi ce starter-kit ?
Chaque serveur MCP Cloud Temple suit le **même pattern architectural** :
- **3 couches** d'interface (API MCP + CLI scriptable + shell interactif)
- **5 middlewares ASGI** (Admin, HealthCheck, Auth, Logging, FastMCP)
- **Mêmes conventions** (format retour, auth ContextVar, nommage, logs)
- **Mêmes outils** (FastMCP, Click, prompt_toolkit, Rich)
- **Même infra** (Docker, WAF Caddy+Coraza, S3 Token Store)

Ce guide vous permet de démarrer un nouveau serveur MCP en quelques heures
au lieu de quelques jours.

---

## 2. Architecture — La règle des 3 couches + 5 middlewares

### 2.1 Les 3 couches d'interface

**Toute fonctionnalité DOIT être exposée dans les 3 couches** :

```
┌─────────────────────────────────────────────────────┐
│  COUCHE 1 : Outil MCP (server.py)                   │
│  @mcp.tool() async def mon_outil(...) -> dict       │
│  → L'API, appelée par tout client MCP               │
├─────────────────────────────────────────────────────┤
│  COUCHE 2 : CLI Click (commands.py)                  │
│  @cli.command() def mon_outil(ctx, ...):            │
│  → Interface scriptable en ligne de commande         │
├─────────────────────────────────────────────────────┤
│  COUCHE 3 : Shell interactif (shell.py)              │
│  async def cmd_mon_outil(client, state, args):      │
│  → Interface interactive avec autocomplétion         │
├─────────────────────────────────────────────────────┤
│  PARTAGÉ : Affichage Rich (display.py)               │
│  def show_mon_outil_result(result):                 │
│  → Tables, panels, couleurs — utilisé par 2 et 3   │
└─────────────────────────────────────────────────────┘
```

### 2.2 La pile de 5 middlewares ASGI

Chaque serveur MCP Cloud Temple assemble **5 couches middleware** dans `create_app()` :

```
LoggingMiddleware → AdminMiddleware → HealthCheckMiddleware → AuthMiddleware → FastMCP
```

| Couche (ext → int)         | Intercepte                          | Rôle                                |
| -------------------------- | ----------------------------------- | ----------------------------------- |
| **LoggingMiddleware**      | **Toutes** les requêtes             | Log stderr + ring buffer 200 entrées|
| **AdminMiddleware**        | `/admin`, `/admin/static/*`, `/admin/api/*` | Console admin web SPA     |
| **HealthCheckMiddleware**  | `/health`, `/healthz`, `/ready`     | JSON direct (sans auth, pour WAF)   |
| **AuthMiddleware**         | Toutes les requêtes MCP             | Bearer Token → ContextVar           |
| **FastMCP app**            | MCP Protocol (Streamable HTTP)      | `/mcp` endpoint                     |

> ⚠️ **LoggingMiddleware DOIT être en position outermost** (dernier empilé = premier exécuté).
> Si placé en innermost, les requêtes admin et health ne sont pas loguées dans le ring buffer
> d'activité — bug découvert en production sur mcp-office.

```python
def create_app():
    from .auth.middleware import AuthMiddleware, LoggingMiddleware
    from .admin.middleware import AdminMiddleware

    app = mcp.streamable_http_app()       # FastMCP (innermost)
    app = AuthMiddleware(app)             # Auth Bearer + ContextVar
    app = HealthCheckMiddleware(app)       # /health, /healthz, /ready
    app = AdminMiddleware(app, mcp)        # /admin
    app = LoggingMiddleware(app)           # Logging (outermost !)

    return app
```

### 2.3 Console d'administration Web (`/admin`)

Chaque serveur MCP inclut une console admin web avec :
- **Login** : authentification par Bootstrap Key ou token admin S3
- **Dashboard** : état du serveur, version, nombre d'outils, état S3
- **Tokens** : CRUD des tokens d'accès (si S3 configuré)
- **Activité** : logs temps réel (ring buffer 200 entrées, auto-refresh 5s)

Design Cloud Temple : dark theme `#0f0f23`, accent teal `#41a890`.

### 2.4 Pourquoi ces choix ?

| Couche         | Consommateur                          | Usage                       |
| -------------- | ------------------------------------- | --------------------------- |
| Outil MCP      | Agents IA (Cline, Claude Desktop)     | Automatisation, intégration |
| CLI Click      | DevOps, scripts CI/CD, cron           | Scriptable, composable      |
| Shell interactif | Humains en exploration              | Découverte, debug, admin    |
| Console admin  | Administrateurs (navigateur web)      | Monitoring, gestion tokens  |

---

## 3. Stack technique de base

| Composant        | Technologie             | Rôle                                |
| ---------------- | ----------------------- | ----------------------------------- |
| Framework MCP    | `FastMCP` (Python SDK)  | Expose les outils via Streamable HTTP |
| Transport        | Streamable HTTP         | `/mcp` endpoint (remplace SSE)      |
| Serveur HTTP     | `Uvicorn` (ASGI)        | Sert l'application FastMCP          |
| Configuration    | `pydantic-settings`     | Variables d'environnement + `.env`  |
| CLI scriptable   | `Click`                 | Commandes en ligne                  |
| Shell interactif | `prompt_toolkit`        | Autocomplétion, historique          |
| Affichage        | `Rich`                  | Tables, panels, couleurs, Markdown  |
| Communication    | `httpx`                 | Client HTTP vers le serveur         |
| Auth             | Bearer Token + ContextVar | Authentification request-scoped   |
| Token Store      | S3 + cache TTL 5min     | Persistance tokens (optionnel)      |
| Console admin    | SPA HTML/JS             | Interface web d'administration      |
| Conteneur        | Docker + Docker Compose | Déploiement                         |
| WAF              | Caddy + Coraza          | TLS, rate limiting, OWASP CRS      |

---

## 4. Structure de fichiers recommandée

```
mon-mcp-server/
├── src/
│   └── mon_service/
│       ├── __init__.py
│       ├── __main__.py         # python -m mon_service
│       ├── server.py           # ← Outils MCP + create_app() + HealthCheckMiddleware + bannière
│       ├── config.py           # Configuration pydantic-settings (S3, WAF, etc.)
│       ├── admin/              # ← Console admin web (/admin)
│       │   ├── __init__.py
│       │   ├── middleware.py   # AdminMiddleware ASGI (static + API routing + CORS)
│       │   └── api.py          # REST API admin (health, tokens, logs)
│       ├── auth/               # ← Auth + Token Store
│       │   ├── __init__.py
│       │   ├── middleware.py   # AuthMiddleware (Bearer + ContextVar) + LoggingMiddleware (ring buffer)
│       │   ├── context.py      # check_access, check_write_permission via ContextVar
│       │   └── token_store.py  # Token Store S3 + cache mémoire TTL 5min
│       ├── static/             # ← Fichiers statiques admin (SPA)
│       │   └── admin.html      # SPA HTML (login + Dashboard + Tokens + Activité)
│       └── core/               # ← Vos services métier
│           ├── mon_service_a.py
│           ├── mon_service_b.py
│           └── models.py
├── scripts/
│   ├── mcp_cli.py              # Point d'entrée CLI
│   └── cli/
│       ├── __init__.py         # Config globale (MCP_URL, MCP_TOKEN)
│       ├── client.py           # Client HTTP vers le serveur
│       ├── commands.py         # ← Couche 2 : commandes Click
│       ├── shell.py            # ← Couche 3 : shell interactif
│       └── display.py          # Affichage Rich partagé (couches 2+3)
├── waf/                        # WAF Caddy + Coraza
│   ├── Caddyfile               # Config reverse proxy + OWASP CRS
│   └── Dockerfile              # Image Caddy avec plugin Coraza
├── Dockerfile
├── docker-compose.yml          # WAF + MCP service + réseau interne
├── requirements.txt
├── .env.example
├── VERSION
└── README.md
```

---

## 5. Conventions et patterns

### 5.1 Descriptions des paramètres MCP (obligatoire)

**Chaque paramètre** d'un outil MCP **doit** avoir une description via `Annotated[type, Field(description="...")]`.
Sans cela, les clients MCP (Cline, Claude Desktop…) affichent **"No description"** — inutile pour le LLM et l'utilisateur.

```python
from typing import Annotated, Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP, Context

@mcp.tool()
async def mon_outil(
    # ✅ Chaque paramètre utilisateur a une description
    resource_id: Annotated[str, Field(description="ID de la ressource à traiter")],
    action: Annotated[str, Field(default="read", description="Action : read, write, delete")] = "read",
    timeout: Annotated[int, Field(default=30, description="Timeout en secondes (max 60)")] = 30,
    tags: Annotated[Optional[list[str]], Field(default=None, description="Tags optionnels pour filtrer")] = None,
    # ⚠️ ctx est le seul paramètre SANS description (interne FastMCP)
    ctx: Optional[Context] = None,
) -> dict:
    """Description courte de l'outil (visible dans la liste des tools)."""
```

**Règles** :
- `Annotated[type, Field(description="...")]` pour **chaque** paramètre utilisateur
- Descriptions **concises** (1 ligne) avec valeurs possibles, exemples, contraintes
- `ctx: Optional[Context] = None` en dernier, **sans** description (injecté par FastMCP)
- Les optionnels : `Field(default=..., description="...")` + `= ...` (les deux !)
- Imports requis : `from typing import Annotated` et `from pydantic import Field`

### 5.2 Format de retour standardisé

```python
# Succès
return {"status": "ok", "data": ...}

# Erreur
return {"status": "error", "message": "Description de l'erreur"}

# Cas spéciaux
return {"status": "created", ...}
return {"status": "deleted", ...}
return {"status": "already_exists", ...}
return {"status": "not_found", ...}
```

> **Règle** : ne jamais lever d'exception dans un outil MCP.
> Toujours `try/except` et retourner `{"status": "error", "message": str(e)}`.

### 5.2 Nommage

| Couche                  | Convention        | Exemple                              |
| ----------------------- | ----------------- | ------------------------------------ |
| Outil MCP (server.py)   | `snake_case`      | `project_create`, `deploy_status`    |
| CLI Click (commands.py) | `kebab-case`      | `project create`, `deploy status`    |
| Shell (shell.py)        | `kebab-case`      | `create`, `deploy-status`            |
| Display (display.py)    | `show_xxx_result` | `show_deploy_result()`               |
| Handler shell           | `cmd_xxx`         | `cmd_deploy_status()`                |

### 5.3 Authentification via ContextVar

L'AuthMiddleware injecte les infos du token dans un `contextvars.ContextVar` :

```python
@mcp.tool()
async def mon_outil(resource_id: str, ...) -> dict:
    try:
        # 1. Vérifier l'accès (request-scoped via ContextVar)
        access_err = check_access(resource_id)
        if access_err:
            return access_err

        # 2. Vérifier permission write
        write_err = check_write_permission()
        if write_err:
            return write_err

        # 3. Logique métier...
```

Le mécanisme ContextVar est :
- **Thread-safe** en asyncio (isolé par tâche)
- **Request-scoped** (pas de fuite entre requêtes)
- **Zéro couplage** entre le middleware et les outils

### 5.4 Token Store S3 + cache TTL

Les tokens d'accès sont persistés sur S3 (`_system/tokens.json`), avec
un **cache mémoire TTL 5 minutes** qui évite de relire S3 à chaque requête.

```
Démarrage : init_token_store() → charge depuis S3
Requête   : AuthMiddleware → get_token_store() → lookup hash SHA-256 (cache)
Admin     : create/revoke → sauvegarde S3 + invalide cache
```

Chaque token stocke :
- `client_name` — Nom du client (obligatoire)
- `permissions` — Liste de permissions (`["read"]`, `["read", "write"]`, `["admin"]`)
- `allowed_resources` — Liste de ressources autorisées (vide = toutes)
- `email` — Email du propriétaire (optionnel, traçabilité)
- `expires_at` — Date d'expiration ISO 8601 (calculée depuis `expires_in_days`)
- `created_at` — Date de création ISO 8601
- `revoked` — Booléen (révocation logique)

**Expiration** : `get_by_hash()` vérifie `expires_at` et retourne `None` si le token est expiré.

Si S3 n'est pas configuré, seul le `ADMIN_BOOTSTRAP_KEY` fonctionne (mode dev).

### 5.5 Lazy-loading des services

Ne **jamais** instancier un service au top-level du module :

```python
# ✅ BIEN — lazy-load via getter singleton
_db_service = None

def get_db():
    global _db_service
    if _db_service is None:
        from .core.database import DatabaseService
        _db_service = DatabaseService()
    return _db_service
```

### 5.6 Logs serveur

Toujours sur `stderr` (jamais `stdout` qui pollue le flux MCP) :

```python
print(f"🔧 [MonOutil] Message de debug", file=sys.stderr)
```

### 5.7 Bannière dynamique au démarrage

La bannière liste automatiquement tous les outils MCP enregistrés :

```python
def _build_banner() -> str:
    tools_list = mcp._tool_manager.list_tools()
    # ... bannière ASCII avec liste dynamique des outils
```

---

## 6. Checklist — Créer un serveur MCP from scratch

### Phase 1 : Fondation

- [ ] Copier le dossier `boilerplate/` dans un nouveau repo
- [ ] Renommer `mon_service` → votre nom de service
- [ ] `config.py` — Adapter les variables d'environnement
- [ ] `server.py` — Vérifier `system_health` et `system_about`
- [ ] `__main__.py` — Adapter le nom du package
- [ ] `.env.example` — Documenter vos variables
- [ ] `docker compose build && docker compose up -d`
- [ ] Vérifier : `curl http://localhost:8082/health`
- [ ] Vérifier : `open http://localhost:8082/admin`

### Phase 2 : Outils métier

Pour **chaque** outil métier, suivre le processus 4 fichiers :

- [ ] **server.py** — `@mcp.tool()` avec docstring, auth, try/except
- [ ] **display.py** — Fonction `show_xxx_result()` Rich
- [ ] **commands.py** — Commande Click (ou sous-commande d'un groupe)
- [ ] **shell.py** — Handler `cmd_xxx()` + dispatch + autocomplétion + aide

### Phase 3 : Token Store S3

- [ ] Configurer S3 dans `.env` (endpoint, credentials, bucket)
- [ ] Vérifier : `init_token_store()` au démarrage (logs)
- [ ] Tester : créer un token via la console admin `/admin`
- [ ] Tester : `python scripts/mcp_cli.py token create mon-agent --email user@domain.com`
- [ ] Tester : `python scripts/mcp_cli.py token list`
- [ ] Vérifier l'expiration : tokens créés avec `--expires 90` expirent après 90 jours

### Phase 4 : Production

- [ ] TLS via WAF (HTTPS, Let's Encrypt ou reverse proxy amont)
- [ ] `ADMIN_BOOTSTRAP_KEY` ≥ 64 caractères aléatoires
- [ ] Rate limiting (déjà configuré via Caddy)
- [ ] Monitoring `/health` (déjà exposé via HealthCheckMiddleware)

---

## 7. Processus détaillé — Ajouter un outil

### Étape 1 : L'outil MCP dans `server.py`

```python
from typing import Annotated, Optional
from pydantic import Field

@mcp.tool()
async def mon_nouvel_outil(
    resource_id: Annotated[str, Field(description="ID de la ressource concernée")],
    param1: Annotated[str, Field(description="Paramètre principal (ex: nom, chemin, requête)")],
    param2: Annotated[Optional[int], Field(default=None, description="Paramètre optionnel (ex: limite, timeout)")] = None,
    ctx: Optional[Context] = None,
) -> dict:
    """Description courte (1 ligne) — visible dans la liste des tools MCP."""
    try:
        access_err = check_access(resource_id)
        if access_err:
            return access_err

        result = await get_my_service().do_something(resource_id, param1)

        return {"status": "ok", "resource_id": resource_id, "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

> **⚠️ Important** : Chaque paramètre utilise `Annotated[type, Field(description="...")]`
> pour que Cline et les autres clients MCP affichent les descriptions (voir §5.1).

### Étape 2 : L'affichage Rich dans `display.py`

```python
def show_mon_outil_result(result: dict):
    from rich.panel import Panel
    console.print(Panel.fit(
        f"[bold]Ressource:[/bold] [cyan]{result.get('resource_id', '?')}[/cyan]\n"
        f"[bold]Données:[/bold]   [green]{result.get('data', 'N/A')}[/green]",
        title="🔧 Mon outil",
        border_style="cyan",
    ))
```

### Étape 3 : La commande CLI Click dans `commands.py`

```python
@cli.command("mon-outil")
@click.argument("resource_id")
@click.option("--param1", required=True, help="Description")
@click.pass_context
def mon_outil_cmd(ctx, resource_id, param1):
    """🔧 Description courte pour l'aide Click."""
    async def _run():
        client = MCPClient(ctx.obj["url"], ctx.obj["token"])
        result = await client.call_tool("mon_nouvel_outil", {
            "resource_id": resource_id, "param1": param1
        })
        if result.get("status") == "ok":
            show_mon_outil_result(result)
        else:
            show_error(result.get("message", "Erreur"))
    asyncio.run(_run())
```

### Étape 4 : Le handler Shell dans `shell.py`

```python
async def cmd_mon_outil(client, state, args="", json_output=False):
    if not args:
        show_warning("Usage: mon-outil <param1>")
        return
    result = await client.call_tool("mon_nouvel_outil", {
        "resource_id": state.get("current_resource", ""),
        "param1": args.strip(),
    })
    if json_output:
        _json_dump(result)
    elif result.get("status") == "ok":
        show_mon_outil_result(result)
    else:
        show_error(result.get("message", "Erreur"))
```

---

## 8. Pièges à éviter

| Piège                        | Conséquence                                           | Solution                                 |
| ---------------------------- | ----------------------------------------------------- | ---------------------------------------- |
| Oublier une couche           | L'outil existe côté serveur mais pas dans le shell    | Toujours les 4 fichiers                  |
| Dupliquer du code display    | Copier les tables Rich dans commands.py ET shell.py   | Centraliser dans display.py (DRY)        |
| Auth oubliée                 | Un outil expose des données sans contrôle             | `check_access()` systématiquement        |
| `stdout` au lieu de `stderr` | Les logs polluent le flux JSON MCP                    | Toujours `file=sys.stderr`               |
| Import circulaire            | Crash au démarrage                                    | Utiliser les getters lazy-load (§5.5)    |
| Bloquer l'event loop         | Le serveur freeze sur du CPU-bound                    | `await loop.run_in_executor(None, func)` |
| Oublier le banner            | L'outil n'apparaît pas dans la bannière de démarrage  | La bannière est dynamique automatiquement|
| Shell sans autocomplétion    | L'utilisateur ne découvre pas la commande             | Ajouter dans `SHELL_COMMANDS`            |
| Exception non catchée        | Le client MCP reçoit une stacktrace au lieu d'un dict | `try/except` → `{"status": "error"}`     |
| Utiliser `mcp.sse_app()`    | Transport obsolète (SSE)                              | Utiliser `mcp.streamable_http_app()`     |
| Params sans description      | Cline affiche "No description" pour chaque paramètre | `Annotated[type, Field(description=...)]` (§5.1) |
| `except: pass` dans token_store | Token corrompu passe quand même (fail-open)        | `except: return None` (fail-close, §8bis.1) |
| `==` pour comparer le bootstrap key | Timing attack side-channel                    | `hmac.compare_digest()` (§8bis.2)        |
| Token via query string       | Token dans les logs, Referer, cache proxy (CWE-598)   | Bearer header uniquement (§8bis.3)       |
| CORS `*` sur l'admin         | API admin exposée à des requêtes cross-origin          | Same-origin, pas de wildcard (§8bis.4)   |
| LoggingMiddleware en innermost | Requêtes admin/health invisibles dans les logs       | Placer en outermost (§2.2)               |
| Bootstrap key par défaut     | Déploiement en prod avec la clé de dev                 | Warning au démarrage (§8bis.6)           |
| Hash prefix trop court       | Révocation du mauvais token (collision)                | Min 8 caractères (§8bis.5)               |

---

## 8bis. Durcissement sécurité (leçons de production)

Ces correctifs proviennent de l'**audit de sécurité mcp-office v0.4.2** (28 findings).
Ils sont déjà intégrés dans le boilerplate.

### 8bis.1 Fail-close sur expiration corrompue

```python
# ❌ AVANT (fail-open) — token corrompu passe quand même
except (ValueError, TypeError):
    pass  # → continue → return token

# ✅ APRÈS (fail-close) — doute = rejet
except (ValueError, TypeError):
    return None  # Token rejeté si expires_at est invalide
```

### 8bis.2 Comparaison constante (anti timing attack)

```python
import hmac

# ❌ AVANT — vulnérable aux timing attacks
if token == settings.admin_bootstrap_key:

# ✅ APRÈS — comparaison en temps constant
if hmac.compare_digest(token, settings.admin_bootstrap_key):
```

### 8bis.3 Pas de token via query string

Les tokens ne doivent **jamais** transiter via l'URL (`?token=xxx`).
Les query strings apparaissent dans : logs serveur, Referer headers,
historique navigateur, caches proxy. Seul le header `Authorization: Bearer` est accepté.

### 8bis.4 CORS restreint (pas de wildcard)

L'API admin (`/admin/api/*`) est servie par le même domaine que la console admin.
Pas besoin de `Access-Control-Allow-Origin: *` — ça exposerait l'API admin
à des requêtes cross-origin malveillantes.

### 8bis.5 Min 8 caractères pour les hash prefix

La révocation de token par préfixe de hash exige **≥ 8 caractères** pour
éviter les collisions accidentelles (révoquer le mauvais token).

### 8bis.6 Warning bootstrap key par défaut

Au démarrage, si `ADMIN_BOOTSTRAP_KEY` vaut `changeme-in-production`,
le serveur affiche un **⚠️ WARNING** sur stderr. Empêche de déployer
en production avec la clé de dev.

### 8bis.7 HSTS dans le WAF

Le Caddyfile inclut `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`.
Force les navigateurs à utiliser HTTPS même si l'utilisateur tape `http://`.

### 8bis.8 Pattern bypass WAF Caddy

**Leçon de production** : les `SecAction` Coraza avec un ID déjà défini dans
`@crs-setup.conf.example` sont **ignorés** (première occurrence gagne).
On ne peut **pas** overrider `tx.allowed_methods` via directives après les `Include`.

**Solution** : bypass `handle` en amont du WAF. Pour toute route qui nécessite
un bypass (upload volumineux, code source dans le body, méthodes DELETE bloquées
par CRS), ajouter un `handle /votre-route* { ... }` AVANT le bloc
`handle { ... }` qui contient `coraza_waf`.

### 8bis.9 Outil `system_whoami` (inclus dans le boilerplate)

Chaque serveur MCP expose un outil `system_whoami` qui retourne l'identité
du token courant : auth_type, client_name, permissions, email, dates.
Indispensable pour le debug et la traçabilité en multi-utilisateurs.

### 8bis.10 Helpers d'identité (`context.py`)

Le boilerplate inclut deux helpers en plus de `check_access()` et `check_write_permission()` :

```python
from .auth.context import get_current_client_name, is_admin

# Isolation multi-tenant : chaque client ne voit que ses ressources
owner = get_current_client_name()

# Opérations privilégiées
if is_admin():
    # Voir toutes les ressources
```

---

## 9. Docker — Pattern type

### docker-compose.yml

```yaml
services:
  waf:
    build: ./waf
    ports:
      - "${WAF_PORT:-8082}:8082"
    depends_on:
      - mon-mcp
    networks:
      - mcp-net

  mon-mcp:
    build: .
    expose:
      - "8002"          # PAS de ports: → non accessible directement
    env_file: .env
    networks:
      - mcp-net

networks:
  mcp-net:
    driver: bridge
```

**Important** : le service MCP utilise `expose` (pas `ports`) — il n'est
pas accessible directement. Tout le trafic passe par le WAF.

---

## 10. Boilerplate — Projet complet prêt à démarrer

Le dossier [`boilerplate/`](boilerplate/) contient un **projet MCP complet et fonctionnel** :

```
boilerplate/
├── src/mon_service/
│   ├── __init__.py
│   ├── __main__.py          # python -m mon_service
│   ├── server.py            # FastMCP + system_health/about/whoami + create_app() + bannière
│   ├── config.py            # pydantic-settings (S3, WAF, auth)
│   ├── admin/               # Console admin web (/admin)
│   │   ├── __init__.py
│   │   ├── middleware.py    # AdminMiddleware ASGI (static + API routing)
│   │   └── api.py           # REST API admin (health, tokens, logs, whoami)
│   ├── auth/                # Auth + Token Store
│   │   ├── __init__.py
│   │   ├── middleware.py    # AuthMiddleware (Bearer + ContextVar) + LoggingMiddleware (ring buffer)
│   │   ├── context.py       # check_access, check_write_permission, get_current_client_name, is_admin
│   │   └── token_store.py   # Token Store S3 + cache mémoire TTL 5min
│   └── static/
│       └── admin.html       # SPA HTML (login + Dashboard + Tokens + Activité)
├── scripts/
│   ├── mcp_cli.py           # Point d'entrée CLI
│   └── cli/
│       ├── __init__.py      # Config globale (MCP_URL, MCP_TOKEN)
│       ├── client.py        # Client HTTP complet
│       ├── commands.py      # CLI Click (health, about, whoami, shell, token create/list/revoke)
│       ├── shell.py         # Shell interactif (prompt_toolkit) + whoami + token management
│       └── display.py       # Affichage Rich partagé (system, tokens, whoami)
├── waf/
│   ├── Dockerfile           # Caddy + Coraza WAF + Rate Limiting
│   └── Caddyfile            # Config WAF : reverse proxy + OWASP CRS + HSTS
├── Dockerfile               # Python 3.11, utilisateur non-root
├── docker-compose.yml       # WAF (port 8082) → MCP (port 8002, interne)
├── requirements.txt         # mcp, uvicorn, boto3, click, rich, httpx
├── .env.example             # Variables d'environnement documentées
├── VERSION                  # 0.1.0
└── README.md                # Guide de démarrage rapide
```

**Pour démarrer un nouveau projet MCP** :
1. Copier le dossier `boilerplate/` dans un nouveau repo
2. Renommer `mon_service` → votre nom de service
3. Adapter `config.py` avec vos variables d'environnement
4. Ajouter vos services métier dans `src/mon_service/core/`
5. Ajouter vos outils MCP dans `server.py`
6. Pour chaque outil : compléter display.py → commands.py → shell.py

---

## 11. Configurer dans Cline (VS Code / VSCodium)

Une fois votre serveur MCP lancé, connectez-le à **Cline** pour que l'agent IA
puisse utiliser vos outils. Voir le guide complet : **[CLINE_SETUP.md](CLINE_SETUP.md)**

**Configuration rapide** — Ajoutez dans `cline_mcp_settings.json` :

```json
{
  "mcpServers": {
    "mon-mcp-service": {
      "url": "http://localhost:8082/mcp",
      "headers": {
        "Authorization": "Bearer VOTRE_TOKEN_ICI"
      },
      "timeout": 600
    }
  }
}
```

> **⚠️ Important** : l'endpoint est toujours `/mcp` (pas `/sse`).
> Le port `8082` est le port WAF externe (pas le port interne du service).
> Le `timeout: 600` évite les déconnexions MCP sur les opérations longues.

---

## 12. Exemples de référence

| Projet | Outils | Innovations clés |
| ------ | ------ | ---------------- |
| [mcp-tools](https://github.com/chrlesur/mcp-tools) | 12+ outils (shell, SSH, HTTP, network, files, calc, date, Perplexity...) | Sandbox Docker éphémère, anti-SSRF, Token Store S3, console admin web |
| [mcp-office](https://github.com/Cloud-Temple/mcp-office.git) | 7+ outils (read/write/convert Office, images, assets, templates) | Sandbox sidecar HTTP, Design Systems PPTX/DOCX/XLSX/PDF, audit sécurité 28 findings, HTML slide engine |
| [graph-memory](https://github.com/chrlesur/graph-memory) | ~28 outils (Knowledge Graph, RAG, ingestion, Q&A) | Recherche hybride, backup 3 couches, namespaces isolés |

Les fichiers clés dans chaque projet :

| Rôle                  | Fichier type                          |
| --------------------- | ------------------------------------- |
| Outils MCP            | `src/mon_service/server.py`           |
| Pile middleware ASGI   | `create_app()` dans `server.py`       |
| Console admin          | `admin/middleware.py` + `admin/api.py` |
| Auth + ContextVar      | `auth/middleware.py` + `auth/context.py` |
| Token Store S3         | `auth/token_store.py`                 |
| CLI Click             | `scripts/cli/commands.py`             |
| Shell interactif      | `scripts/cli/shell.py`                |
| Affichage Rich        | `scripts/cli/display.py`              |
| Client HTTP           | `scripts/cli/client.py`               |
| Config                | `src/mon_service/config.py`           |

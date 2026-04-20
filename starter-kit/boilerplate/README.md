# 🔧 Mon Service MCP

> Service MCP Cloud Temple — [décrire le domaine métier ici].

## Démarrage rapide

### 1. Configuration

```bash
cp .env.example .env
# Éditer .env avec vos paramètres
```

### 2. Lancement (Docker)

```bash
docker compose build
docker compose up -d

# Vérification
curl http://localhost:8082/health
# → {"status":"healthy","service":"mon-mcp-service","version":"0.1.0","transport":"streamable-http"}

# Console d'administration
open http://localhost:8082/admin
```

### 3. CLI

```bash
pip install -r requirements.txt

# Health check
python scripts/mcp_cli.py health

# Informations
python scripts/mcp_cli.py about

# Shell interactif
python scripts/mcp_cli.py shell
```

### 4. Lancement (local, sans Docker)

```bash
pip install -r requirements.txt
python -m src.mon_service
```

## Architecture

Ce service suit le pattern **3 couches + 5 middlewares** Cloud Temple :

### 3 couches d'interface

| Couche           | Fichier                       | Rôle                               |
| ---------------- | ----------------------------- | ---------------------------------- |
| Outils MCP       | `src/mon_service/server.py`   | API MCP (Streamable HTTP `/mcp`)   |
| CLI Click        | `scripts/cli/commands.py`     | Interface scriptable               |
| Shell interactif | `scripts/cli/shell.py`        | Interface interactive              |
| Affichage        | `scripts/cli/display.py`      | Rich partagé (couches 2+3)         |

### 5 middlewares ASGI

```
AdminMiddleware → HealthCheckMiddleware → AuthMiddleware → LoggingMiddleware → FastMCP
```

| Middleware              | Rôle                                        |
| ----------------------- | ------------------------------------------- |
| AdminMiddleware         | Console admin web `/admin` (SPA + API REST) |
| HealthCheckMiddleware   | `/health`, `/healthz`, `/ready` (sans auth) |
| AuthMiddleware          | Bearer Token → ContextVar (request-scoped)  |
| LoggingMiddleware       | Log stderr + ring buffer 200 entrées        |
| FastMCP                 | Protocole MCP (Streamable HTTP)             |

### Infrastructure

```
Internet → WAF Caddy+Coraza (:8082) → mon-mcp (:8002, réseau interne)
```

## Variables d'environnement

### Serveur (.env)

| Variable              | Description                        | Défaut                    |
| --------------------- | ---------------------------------- | ------------------------- |
| `MCP_SERVER_NAME`     | Nom du service                     | `mon-mcp-service`         |
| `MCP_SERVER_PORT`     | Port d'écoute (interne)            | `8002`                    |
| `WAF_PORT`            | Port d'écoute WAF (externe)        | `8082`                    |
| `ADMIN_BOOTSTRAP_KEY` | Token admin (⚠️ changer !)        | `change_me_in_production` |
| `S3_ENDPOINT_URL`     | Endpoint S3 (optionnel, tokens)    | (vide)                    |
| `S3_ACCESS_KEY_ID`    | Clé d'accès S3                     | (vide)                    |
| `S3_SECRET_ACCESS_KEY`| Secret S3                          | (vide)                    |
| `S3_BUCKET_NAME`      | Bucket S3 pour les tokens          | (vide)                    |

### Client CLI (variables shell)

| Variable    | Description        | Défaut                   |
| ----------- | ------------------ | ------------------------ |
| `MCP_URL`   | URL du serveur     | `http://localhost:8002`  |
| `MCP_TOKEN` | Token d'auth       | (vide)                   |

## Ajouter un outil métier

Voir le guide complet : [Starter Kit MCP Cloud Temple](../README.md)

1. `server.py` — `@mcp.tool()` avec docstring, auth, try/except
2. `display.py` — Fonction `show_xxx_result()` Rich
3. `commands.py` — Commande Click
4. `shell.py` — Handler + autocomplétion + aide

## Endpoints

| Endpoint        | Description                    | Auth requise |
| --------------- | ------------------------------ | ------------ |
| `/mcp`          | Protocole MCP (Streamable HTTP)| Bearer Token |
| `/health`       | Health check JSON              | Non          |
| `/admin`        | Console admin web (SPA)        | Non (login)  |
| `/admin/api/*`  | API REST admin                 | Admin token  |

## License

Cloud Temple — Usage interne.

# ============================================================
# AdviceRoom WAF — Caddy + Coraza (OWASP CRS)
# ============================================================
# V1-07 : Caddy compilé avec le module Coraza pour OWASP CRS
#
# Build multi-stage :
# 1. xcaddy compile Caddy avec le plugin Coraza
# 2. Image finale Alpine minimale
#
# Ref: DESIGN/SECURITY_AUDIT_V1.md V1-07

# --- Stage 1 : Compilation Caddy + Coraza ---
FROM caddy:2-builder AS builder

RUN xcaddy build \
    --with github.com/corazawaf/coraza-caddy/v2

# --- Stage 2 : Image finale ---
FROM caddy:2-alpine

# Copier le binaire Caddy compilé avec Coraza
COPY --from=builder /usr/bin/caddy /usr/bin/caddy

# Copier la configuration
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 80 443

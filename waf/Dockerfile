# ============================================================
# AdviceRoom WAF — Caddy + Coraza (OWASP CRS)
# ============================================================
# V1-07 : Caddy compilé avec le module Coraza pour OWASP CRS
#
# Build multi-stage :
# 1. xcaddy compile Caddy avec le plugin Coraza
# 2. Image finale Alpine avec règles CRS
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

# Télécharger OWASP CRS v4 (règles WAF)
RUN apk add --no-cache wget && \
    wget -q https://github.com/coreruleset/coreruleset/releases/download/v4.8.0/coreruleset-4.8.0-minimal.tar.gz && \
    tar xzf coreruleset-4.8.0-minimal.tar.gz && \
    mkdir -p /etc/caddy/crs && \
    mv coreruleset-4.8.0/* /etc/caddy/crs/ && \
    cp /etc/caddy/crs/crs-setup.conf.example /etc/caddy/crs/crs-setup.conf && \
    sed -i 's/tx.allowed_methods=GET HEAD POST OPTIONS/tx.allowed_methods=GET HEAD POST OPTIONS PUT DELETE PATCH/' /etc/caddy/crs/crs-setup.conf && \
    rm -rf coreruleset-4.8.0-minimal.tar.gz coreruleset-4.8.0 && \
    apk del wget

# Copier la configuration
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 8088

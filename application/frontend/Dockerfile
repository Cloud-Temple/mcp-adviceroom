# ============================================================
# AdviceRoom Frontend — Multi-stage Build
# ============================================================
# Stage 1 : Build React avec Vite
# Stage 2 : Serve via nginx (port 3000)

# --- Stage 1 : Build ---
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --silent
COPY . .
RUN npm run build

# --- Stage 2 : Serve ---
FROM nginx:alpine

# Supprimer la config par défaut et injecter la nôtre
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/adviceroom.conf

# Copier le build React
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000

# Healthcheck (curl disponible dans nginx:alpine, wget échoue sur IPv6)
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:3000/ > /dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]

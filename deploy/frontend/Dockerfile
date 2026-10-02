# ---- Build (Vite) -------------------------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# A URL da API é fixada no build: https://api[-teste].cadrius.ia.br/api/v1/
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# ---- Produção: Nginx sem privilégios servindo o build estático ---------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS prod
# ${API_ORIGIN} (ex.: https://api.cadrius.ia.br) é substituído no start pelo mecanismo de templates da imagem.
COPY nginx/security-headers.inc.template /etc/nginx/templates/security-headers.inc.template
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV API_ORIGIN=http://127.0.0.1:8000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

# ---- Desenvolvimento (docker compose up): Vite com hot reload ------------------------------
FROM node:20-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

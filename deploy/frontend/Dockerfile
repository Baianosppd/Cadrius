# Front-end (Vite/React) — build estático servido por Nginx sem privilégios.
# O Dockerfile do repositório do front roda `npm start` (script inexistente) e serve o servidor de DESENVOLVIMENTO;
# este é o de produção. Copiado para ./frontend pelo deploy.sh (ideal: versionar no repo do front).
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# A URL da API é fixada no build (Vite): https://api[-teste].cadrius.ia.br/api/v1/
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
# Variáveis (API_ORIGIN) substituídas no start pelo mecanismo de templates da imagem.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK CMD wget -qO- http://127.0.0.1:80/healthz || exit 1

# --- Этап 1: сборка статики (Node нужен только здесь, в рантайм не попадает) ---
# node:24 — ветки до 22 уязвимы к Node2Shell (CVE-2026-111497)
FROM node:24-alpine AS build-stage

WORKDIR /opt/app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- Этап 2: раздача через Angie (форк nginx) ---
FROM docker.angie.software/angie:minimal

COPY --from=build-stage /opt/app/dist /usr/share/angie/html
COPY angie.conf /etc/angie/http.d/default.conf

EXPOSE 80
CMD ["angie", "-g", "daemon off;"]

ARG NODE_IMAGE=docker.io/library/node:24-alpine
ARG ANGIE_IMAGE=docker.angie.software/angie:minimal

# --- Этап 1: сборка статики (Node нужен только здесь, в рантайм не попадает) ---
# node:24 — ветки до 22 уязвимы к Node2Shell
FROM ${NODE_IMAGE} AS build-stage

WORKDIR /opt/app
RUN chown node:node /opt/app
USER node

ARG NPM_REGISTRY=https://registry.npmjs.org
# base64 от "логин:пароль"
ARG NPM_AUTH=""
COPY --chown=node:node package*.json ./
RUN printf 'registry=%s\n' "$NPM_REGISTRY" > .npmrc \
    && if [ -n "$NPM_AUTH" ]; then \
         printf '%s:_auth=%s\nalways-auth=true\n' "${NPM_REGISTRY#https:}" "$NPM_AUTH" >> .npmrc; \
       fi \
    && npm ci \
    && rm -f .npmrc

# Файлы для сборки перечислены явно (вместо «COPY . .» — копирования всей
# папки целиком, которое может утащить в образ лишнее; SonarQube)
COPY --chown=node:node tsconfig.json vite.config.ts index.html ./
COPY --chown=node:node src ./src
RUN npm run build

# --- Этап 2: раздача через Angie (форк nginx) ---
# Мастер-процесс Angie стартует от root (стандартная модель nginx: root открывает
# порт и читает конфиг), рабочие процессы, обслуживающие запросы, — от
# непривилегированного пользователя angie.
FROM ${ANGIE_IMAGE}

COPY --from=build-stage /opt/app/dist /usr/share/angie/html
COPY angie.conf /etc/angie/http.d/default.conf

EXPOSE 80
CMD ["angie", "-g", "daemon off;"]

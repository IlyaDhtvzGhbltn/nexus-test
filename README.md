# Artifact Repository (MVP) — npm Registry

Прототип системы хранения артефактов (аналог Nexus/Artifactory) с поддержкой
**протокола npm Registry**: репозитории **hosted** (публикация через `npm publish`)
и **proxy** (кэширующий прокси к внешнему реестру, например registry.npmjs.org).

## Стек

- **Backend:** Python 3.12, FastAPI, Tortoise-ORM (async), PyJWT, httpx
- **Database:** PostgreSQL 16 (пользователи, RBAC, метаданные пакетов: name/version/dependencies)
- **Frontend:** React 18 + Vite + TypeScript + MUI
- **Blob storage:** абстракция `IStorageProvider`, реализация `LocalStorageProvider` (локальный диск)

## Структура

```
.
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            # приложение, lifespan (init БД + сид)
│       ├── config.py          # настройки (env)
│       ├── db.py              # TORTOISE_ORM конфиг (используется aerich)
│       ├── models.py          # User, Role, Repository, Permission, Package, PackageVersion
│       ├── schemas.py         # Pydantic-схемы
│       ├── security.py        # JWT, bcrypt, RBAC-зависимости
│       ├── seed.py            # роли ADMIN/DEVELOPER/CI_BOT + первый админ
│       ├── storage/
│       │   ├── base.py        # IStorageProvider (интерфейс)
│       │   ├── local.py       # LocalStorageProvider (./storage)
│       │   └── __init__.py    # get_storage() — точка подмены провайдера
│       └── routers/
│           ├── auth.py        # POST /api/auth/login, GET /api/auth/me
│           ├── users.py       # CRUD пользователей + роли (ADMIN)
│           ├── repositories.py# CRUD репозиториев, permissions, список пакетов (ADMIN)
│           └── npm.py         # npm Registry API: login/publish/packument/tarball/search
└── frontend/
    ├── Dockerfile
    └── src/                   # Login, Users, Repositories (+пакеты, +permissions)
```

## Запуск

```bash
docker compose up --build
```

- Админ-панель: http://localhost:5173 (логин `admin` / пароль `admin`)
- API: http://localhost:8000

## Использование с npm CLI

Registry URL репозитория: `http://localhost:8000/npm/<repo_name>/`

```bash
# 1. В админ-панели создать hosted-репозиторий, например "npm-internal"

# 2. Логин (npm получит JWT через PUT /-/user/org.couchdb.user:<login>)
npm login --registry http://localhost:8000/npm/npm-internal/

# 3. Публикация пакета (требует право WRITE или роль ADMIN)
npm publish --registry http://localhost:8000/npm/npm-internal/

# 4. Установка (требует READ)
npm install mylib --registry http://localhost:8000/npm/npm-internal/

# 5. Поиск
npm search mylib --registry http://localhost:8000/npm/npm-internal/
```

Для proxy-репозитория (upstream `https://registry.npmjs.org`) те же команды
install/search работают через кэш: первый запрос tarball качается с upstream и
сохраняется через `IStorageProvider`, повторные отдаются локально — в том числе
когда upstream недоступен (packument при этом собирается из закэшированных версий).

CI-сценарий без интерактивного логина — токен в `.npmrc`:

```
//localhost:8000/npm/npm-internal/:_authToken=<JWT из POST /api/auth/login>
```

## Реализованные эндпоинты npm Registry

| Метод и путь (относительно `/npm/{repo}/`) | Назначение |
|---|---|
| `PUT /-/user/org.couchdb.user:{login}` | `npm login` → выдаёт JWT |
| `GET /-/whoami`, `GET /-/ping` | служебные |
| `GET /-/v1/search?text=…` | поиск (hosted — по БД, proxy — passthrough) |
| `PUT /{package}` | `npm publish` (JSON c base64-tgz во `_attachments`) |
| `GET /{package}` | packument (hosted — из БД; proxy — с upstream, tarball-URL переписываются на прокси) |
| `GET /{package}/{version}` | манифест версии (понимает и dist-tag: `/{package}/latest`) |
| `GET /{package}/-/{file}.tgz` | скачивание tarball (proxy кэширует при первом запросе) |

Scoped-пакеты (`@scope/name`, URL-encoded `%2f`) поддерживаются всеми роутами.

## Метаданные в PostgreSQL

При публикации и при кэшировании через прокси из tgz извлекается
`package/package.json`; в БД сохраняются:

- `packages` — имя пакета, dist-tags;
- `package_versions` — версия, описание, **dependencies (JSON)**, полный манифест,
  размер, sha1/sha512, кто загрузил, ключ блоба в хранилище.

Просмотр — в админ-панели (иконка «Packages» у репозитория) или
`GET /api/repositories/{id}/packages`.

## RBAC

| Действие | Требование |
|---|---|
| `npm publish` (PUT пакета) | право **WRITE** на репозиторий (или роль ADMIN) |
| packument / tarball / search (GET) | право **READ** (или ADMIN) |
| `/api/users`, `/api/repositories`, permissions | роль **ADMIN** |

Права назначаются в админ-панели: связка *Роль + Репозиторий + READ/WRITE*.
По умолчанию существует единственная встроенная роль `ADMIN` (полный доступ,
удалить нельзя). Остальные роли админ создаёт сам на вкладке **Roles**;
сама по себе роль ничего не даёт — доступ появляется после выдачи ей
READ/WRITE на конкретный репозиторий.

## Архитектура хранилища

Бизнес-логика работает только с интерфейсом `IStorageProvider`
(`upload_file`, `download_file`, `exists`, `delete_file`). Провайдер выбирается
переменной окружения `STORAGE_PROVIDER`:

- `minio` (в docker-compose по умолчанию) — общее S3-хранилище
  (`app/storage/minio.py`): все ноды бэкенда видят одни и те же файлы,
  это обязательное условие горизонтального масштабирования. Загрузка потоковая
  (multipart), недокачанные файлы не становятся видимыми.
  Настройки: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`,
  `MINIO_BUCKET`. Веб-консоль MinIO: http://localhost:9001 (minioadmin/minioadmin).
- `local` — диск текущей ноды (`app/storage/local.py`), годится для простого
  запуска в один бэкенд без MinIO.

## Миграции

Для MVP схема создаётся при старте (`generate_schemas`).
Для продакшена — aerich (dev-инструмент, в requirements не входит):

```bash
cd backend
pip install aerich
aerich init -t app.db.TORTOISE_ORM
aerich init-db          # первая миграция
aerich migrate && aerich upgrade   # последующие изменения
```

## Ограничения MVP / что дальше

- Publish принимает ровно одну версию + одно вложение за запрос (стандартное
  поведение npm CLI); unpublish/deprecate не реализованы.
- Proxy-tarball отдаётся клиенту потоково (tee: одновременно клиенту и в
  хранилище), память на запрос ограничена; одновременные запросы одного файла
  порождают одно скачивание с upstream (single-flight, в пределах процесса —
  межнодовая блокировка через Redis запланирована).
- Packument у proxy не кэшируется (живой запрос + офлайн-фолбэк из БД) —
  следующий шаг плана.
- Нет refresh-токенов и ревокации JWT.

## Как проверить работу проекта (пошагово)

Понадобятся: Docker (с docker compose) и Node.js с npm на вашей машине.

### Шаг 1. Запустить проект

```bash
docker compose up --build
```

Дождитесь, пока в логах появится строка `Uvicorn running on http://0.0.0.0:8000`.
Первый запуск может занять несколько минут (скачиваются образы и зависимости).

### Шаг 2. Войти в админ-панель

Откройте в браузере http://localhost:5173 и войдите: логин `admin`, пароль `admin`.
Если страница входа открылась и пустила вас внутрь — авторизация и база данных работают.

### Шаг 3. Создать hosted-репозиторий

На вкладке **Repositories** нажмите **New repository**, введите имя `npm-internal`,
тип `hosted`, нажмите **Create**. Репозиторий появится в таблице с эндпоинтом
`/npm/npm-internal/`.

### Шаг 4. Опубликовать тестовый пакет через npm

В любой пустой папке на вашей машине выполните:

```bash
mkdir hello-pkg && cd hello-pkg && npm init -y
```

Затем залогиньтесь в наш реестр (введите `admin` / `admin`, поле email — любое):

```bash
npm login --registry http://localhost:8000/npm/npm-internal/
```

И опубликуйте пакет:

```bash
npm publish --registry http://localhost:8000/npm/npm-internal/
```

Ожидаемый результат: npm напечатает `+ hello-pkg@1.0.0` без ошибок.

### Шаг 5. Убедиться, что пакет и метаданные сохранились

В админ-панели на вкладке **Repositories** нажмите иконку 📦 (**Packages**)
у репозитория `npm-internal`. В диалоге должен быть пакет `hello-pkg`
версии `1.0.0` с пометкой `latest`. Если добавить в `package.json` зависимости
и опубликовать новую версию — они появятся в колонке Dependencies
(это данные, извлечённые из tgz и сохранённые в PostgreSQL).

### Шаг 6. Установить пакет обратно

В другой пустой папке:

```bash
mkdir consumer && cd consumer && npm init -y
npm install hello-pkg --registry http://localhost:8000/npm/npm-internal/
```

Ожидаемый результат: пакет установился, в `node_modules/hello-pkg` лежат ваши файлы.

### Шаг 7. Проверить proxy-репозиторий

В админ-панели создайте ещё один репозиторий: имя `npmjs-proxy`, тип `proxy`,
Upstream URL `https://registry.npmjs.org`. Затем установите через него любой
публичный пакет:

```bash
npm install left-pad --registry http://localhost:8000/npm/npmjs-proxy/
```

Первый запрос скачает пакет с npmjs.org и закэширует его. Проверка кэша:
откройте **Packages** у `npmjs-proxy` — там появился `left-pad` с версией и
зависимостями. Повторная установка (удалите `node_modules` и `package-lock.json`,
затем снова `npm install`) отдаст файл уже из локального хранилища — это видно
по логам бэкенда (нет обращения к upstream).

### Шаг 8. Проверить разграничение прав (RBAC)

1. На вкладке **Roles** создайте роль `DEVELOPER`, затем на вкладке **Users**
   создайте пользователя `dev1` и отметьте ему эту роль.
2. Попробуйте получить пакет под ним — должно быть отказано (нет прав).
   Залогиньтесь под `dev1` и запросите пакет:

```bash
npm login --registry http://localhost:8000/npm/npm-internal/
```

```bash
npm view hello-pkg --registry http://localhost:8000/npm/npm-internal/
```

   Ожидаемый результат: ошибка `403 Forbidden — READ access to 'npm-internal' denied`.
3. Вернитесь в панель, у репозитория `npm-internal` нажмите иконку щита
   (**Permissions**) и добавьте: роль `DEVELOPER`, доступ `READ`.
4. Повторите запрос — теперь пакет доступен. Для публикации под `dev1`
   аналогично потребуется добавить доступ `WRITE`.

### Если что-то пошло не так

- Логи бэкенда: `docker compose logs backend`
- Проверка, что API живо: http://localhost:8000/api/health → `{"status":"ok"}`
- Список эндпоинтов — в таблице «Реализованные эндпоинты npm Registry» выше
  и в коде роутеров (`backend/app/routers/`)
- Полный сброс (удалит БД и все пакеты): `docker compose down -v`

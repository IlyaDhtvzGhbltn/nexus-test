"""Реализация npm Registry API поверх hosted/proxy репозиториев.

Registry URL для клиента: http://<host>:8000/npm/<repo_name>/
    npm login   --registry http://localhost:8000/npm/<repo>/   (PUT /-/user/…)
    npm publish --registry …                                    (PUT /<package>)
    npm install --registry …            (GET /<package> — packument, GET tarball)
    npm search  --registry …                                    (GET /-/v1/search)

Порядок регистрации роутов важен: сервисные пути ("-/…"), затем scoped-роуты
(@scope/name), затем обычные — иначе catch-all сегменты перехватят чужие запросы.
"""

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import logging
import re
import tarfile
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.models import AccessType, Package, PackageVersion, Repository, RepoType, User
from app.security import create_access_token, get_current_user, require_repo_access, verify_password
from app.storage import IStorageProvider, get_storage

router = APIRouter()

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024
# Сколько первых байт tarball держать для извлечения package.json.
# Файлы крупнее получают метаданные из packument (фолбэк), память на запрос ограничена.
PROXY_EXTRACT_CAP = 8 * 1024 * 1024
NAME_RE = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.tgz$")

read_access = require_repo_access(AccessType.READ)
write_access = require_repo_access(AccessType.WRITE)


# --- Утилиты -------------------------------------------------------------------

def _check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail=f"Invalid package name: {name!r}")
    return name


def _tarball_filename(name: str, version: str) -> str:
    return f"{name.split('/')[-1]}-{version}.tgz"


def _storage_key(repo: Repository, name: str, filename: str) -> str:
    return f"{repo.name}/{name}/{filename}"


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _tarball_url(request: Request, repo: Repository, name: str, filename: str) -> str:
    return f"{_base_url(request)}/npm/{repo.name}/{name}/-/{filename}"


async def _iter_bytes(data: bytes) -> AsyncIterator[bytes]:
    for i in range(0, len(data), CHUNK):
        yield data[i : i + CHUNK]


def _extract_package_json(data: bytes) -> dict | None:
    """Достаёт package.json из tgz (npm кладёт его в package/package.json)."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                parts = member.name.split("/")
                if len(parts) == 2 and parts[1] == "package.json":
                    extracted = tf.extractfile(member)
                    if extracted is not None:
                        return json.loads(extracted.read())
    except (tarfile.TarError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return None


def _sort_versions(versions: list[str]) -> list[str]:
    def key(v: str):
        main = v.split("-")[0].split("+")[0]
        try:
            return (0, tuple(int(x) for x in main.split(".")), v)
        except ValueError:
            return (1, (), v)

    return sorted(versions, key=key)


async def _save_version_metadata(
    repo: Repository,
    name: str,
    version: str,
    manifest: dict,
    blob_key: str,
    size: int,
    shasum: str,
    integrity: str,
    dist_tags: dict | None = None,
    user: User | None = None,
) -> PackageVersion:
    pkg, _ = await Package.get_or_create(repository=repo, name=name)
    if dist_tags:
        pkg.dist_tags = {**(pkg.dist_tags or {}), **dist_tags}
        await pkg.save()
    pv, _ = await PackageVersion.update_or_create(
        package=pkg,
        version=version,
        defaults={
            "description": manifest.get("description"),
            "dependencies": manifest.get("dependencies") or {},
            "manifest": manifest,
            "filename": _tarball_filename(name, version),
            "storage_key": blob_key,
            "size": size,
            "shasum": shasum,
            "integrity": integrity,
            "uploaded_by": user,
        },
    )
    return pv


def _version_doc(request: Request, repo: Repository, pv: PackageVersion, name: str) -> dict:
    doc = dict(pv.manifest)
    doc.setdefault("name", name)
    doc.setdefault("version", pv.version)
    doc["dist"] = {
        "tarball": _tarball_url(request, repo, name, pv.filename),
        "shasum": pv.shasum,
        "integrity": pv.integrity,
    }
    return doc


async def _packument_from_db(request: Request, repo: Repository, name: str) -> dict | None:
    pkg = await Package.get_or_none(repository=repo, name=name)
    if pkg is None:
        return None
    version_rows = await PackageVersion.filter(package=pkg)
    if not version_rows:
        return None
    versions = {pv.version: _version_doc(request, repo, pv, name) for pv in version_rows}
    dist_tags = dict(pkg.dist_tags or {})
    dist_tags.setdefault("latest", _sort_versions(list(versions))[-1])
    return {"_id": name, "name": name, "dist-tags": dist_tags, "versions": versions}


def _upstream_root(repo: Repository) -> str:
    return (repo.upstream_url or "").rstrip("/")


def _quote_name(name: str) -> str:
    return quote(name, safe="@")  # @scope/name -> @scope%2Fname


async def _fetch_upstream_packument(repo: Repository, name: str) -> dict:
    url = f"{_upstream_root(repo)}/{_quote_name(name)}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream unavailable: {exc}") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Package '{name}' not found on upstream")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Upstream returned {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Upstream returned invalid JSON") from exc


def _rewrite_packument(request: Request, repo: Repository, packument: dict) -> dict:
    """Подменяем dist.tarball на наши URL — клиент качает через прокси."""
    name = packument.get("name", "")
    for version_doc in (packument.get("versions") or {}).values():
        dist = version_doc.get("dist") or {}
        upstream_tarball = dist.get("tarball") or ""
        filename = upstream_tarball.rstrip("/").rsplit("/", 1)[-1] or _tarball_filename(
            name, version_doc.get("version", "")
        )
        dist["tarball"] = _tarball_url(request, repo, name, filename)
        version_doc["dist"] = dist
    return packument


async def _serve_blob(storage: IStorageProvider, pv: PackageVersion) -> StreamingResponse:
    return StreamingResponse(
        storage.download_file(pv.storage_key),
        media_type="application/octet-stream",
        headers={"Content-Length": str(pv.size), "X-Checksum-Sha1": pv.shasum or ""},
    )


# --- Сервисные эндпоинты (npm login / whoami / ping / search) --------------------

@router.put("/npm/{repo_name}/-/user/{userdoc}")
async def npm_login(repo_name: str, userdoc: str, body: dict = Body(...)):
    """`npm login`: npm шлёт PUT /-/user/org.couchdb.user:<login> с паролем,
    в ответ ждёт token — выдаём наш JWT."""
    login = body.get("name") or ""
    password = body.get("password") or ""
    user = await User.get_or_none(login=login)
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect login or password")
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"ok": True, "id": f"org.couchdb.user:{login}", "token": create_access_token(user)},
    )


@router.get("/npm/{repo_name}/-/whoami")
async def npm_whoami(repo_name: str, user: User = Depends(get_current_user)):
    return {"username": user.login}


@router.get("/npm/{repo_name}/-/ping")
async def npm_ping(repo_name: str):
    return {}


@router.get("/npm/{repo_name}/-/v1/search")
async def npm_search(
    request: Request,
    text: str = "",
    size: int = 20,
    repo: Repository = Depends(read_access),
):
    if repo.type == RepoType.PROXY:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0)) as client:
                response = await client.get(
                    f"{_upstream_root(repo)}/-/v1/search",
                    params=dict(request.query_params),
                )
            return JSONResponse(status_code=response.status_code, content=response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Upstream search failed: {exc}") from exc

    packages = (
        await Package.filter(repository=repo, name__icontains=text)
        .prefetch_related("versions")
        .limit(max(1, min(size, 250)))
    )
    now = datetime.now(timezone.utc).isoformat()
    objects = []
    for pkg in packages:
        version_rows = list(pkg.versions)
        if not version_rows:
            continue
        latest_version = (pkg.dist_tags or {}).get("latest") or _sort_versions(
            [pv.version for pv in version_rows]
        )[-1]
        latest = next((pv for pv in version_rows if pv.version == latest_version), version_rows[-1])
        objects.append(
            {
                "package": {
                    "name": pkg.name,
                    "version": latest.version,
                    "description": latest.description,
                    "date": latest.created_at.isoformat(),
                    "links": {},
                },
                "score": {"final": 1, "detail": {"quality": 1, "popularity": 1, "maintenance": 1}},
                "searchScore": 1,
            }
        )
    return {"objects": objects, "total": len(objects), "time": now}


# --- Single-flight: один файл качается с upstream максимум одним запросом ----------
# Замок per-process; при нескольких нодах каждая качает максимум один раз
# (честная межнодовая блокировка — через Redis, шаг 6 плана).

_download_locks: dict[str, list] = {}  # key -> [asyncio.Lock, кол-во ожидающих]


async def _acquire_download_lock(key: str) -> list:
    entry = _download_locks.get(key)
    if entry is None:
        entry = _download_locks[key] = [asyncio.Lock(), 0]
    entry[1] += 1
    await entry[0].acquire()
    return entry


def _release_download_lock(key: str, entry: list) -> None:
    entry[0].release()
    entry[1] -= 1
    if entry[1] <= 0:
        _download_locks.pop(key, None)


# --- Tarball (scoped раньше unscoped) --------------------------------------------

_EOF = object()


async def _put_or_fail(queue: asyncio.Queue, item, upload_task: asyncio.Task) -> None:
    """queue.put, который не зависнет, если заливка в хранилище умерла."""
    put_task = asyncio.ensure_future(queue.put(item))
    await asyncio.wait({put_task, upload_task}, return_when=asyncio.FIRST_COMPLETED)
    if put_task.done():
        put_task.result()
        return
    put_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await put_task
    upload_task.result()  # заливка завершилась раньше потока — почти наверняка ошибкой
    raise RuntimeError("storage upload finished before the upstream stream ended")


async def _cached_version(
    repo: Repository, name: str, filename: str, storage: IStorageProvider
) -> PackageVersion | None:
    pkg = await Package.get_or_none(repository=repo, name=name)
    if pkg is None:
        return None
    pv = await PackageVersion.get_or_none(package=pkg, filename=filename)
    if pv is not None and await storage.exists(pv.storage_key):
        return pv
    return None


async def _stream_and_cache(
    repo: Repository,
    name: str,
    version: str,
    key: str,
    storage: IStorageProvider,
    client: httpx.AsyncClient,
    response: httpx.Response,
    lock_entry: list,
) -> AsyncIterator[bytes]:
    """Tee-стриминг: каждый чанк с upstream уходит клиенту и в хранилище одновременно.

    Файл целиком в памяти не появляется. Хранилище кормится через очередь
    с backpressure; при любом обрыве заливка отменяется (недокачанный блоб
    не становится видимым), при полном успехе — пишутся метаданные в БД.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)

    async def _queue_stream() -> AsyncIterator[bytes]:
        while True:
            item = await queue.get()
            if item is _EOF:
                return
            yield item

    upload_task = asyncio.create_task(storage.upload_file(key, _queue_stream()))
    sha1 = hashlib.sha1()
    sha512 = hashlib.sha512()
    size = 0
    head = bytearray()  # первые байты — для извлечения package.json
    completed = False
    try:
        async for chunk in response.aiter_bytes(CHUNK):
            sha1.update(chunk)
            sha512.update(chunk)
            size += len(chunk)
            if size <= PROXY_EXTRACT_CAP:
                head.extend(chunk)
            await _put_or_fail(queue, chunk, upload_task)
            yield chunk
        await _put_or_fail(queue, _EOF, upload_task)
        blob = await upload_task

        # Метаданные пишем ДО освобождения замка: ждущие запросы после пробуждения
        # проверяют кэш по БД и обязаны увидеть запись. Ответ клиенту уже ушёл,
        # поэтому ошибка метаданных стрим не роняет — только лог.
        try:
            manifest = _extract_package_json(bytes(head)) if size <= PROXY_EXTRACT_CAP else None
            if manifest is None:
                # Файл больше лимита буфера — берём манифест из packument
                try:
                    packument = await _fetch_upstream_packument(repo, name)
                    manifest = (packument.get("versions") or {}).get(version)
                except HTTPException:
                    manifest = None
            manifest = dict(manifest) if manifest else {"name": name, "version": version}
            manifest.pop("dist", None)
            await _save_version_metadata(
                repo,
                name,
                manifest.get("version") or version,
                manifest,
                blob.key,
                blob.size,
                shasum=sha1.hexdigest(),
                integrity="sha512-" + base64.b64encode(sha512.digest()).decode(),
            )
        except Exception:
            logger.exception("Failed to store metadata for cached tarball %s", key)
        completed = True
    finally:
        if not completed:
            upload_task.cancel()
            with contextlib.suppress(BaseException):
                await upload_task
        await response.aclose()
        await client.aclose()
        _release_download_lock(key, lock_entry)


async def _download_tarball(
    request: Request,
    repo: Repository,
    name: str,
    filename: str,
    storage: IStorageProvider,
):
    _check_name(name)
    if not FILENAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid tarball filename")

    pv = await _cached_version(repo, name, filename, storage)
    if pv is not None:
        return await _serve_blob(storage, pv)

    if repo.type == RepoType.HOSTED:
        raise HTTPException(status_code=404, detail="Tarball not found")

    # Proxy cache miss
    basename = name.split("/")[-1]
    if not (filename.startswith(basename + "-") and filename.endswith(".tgz")):
        raise HTTPException(status_code=400, detail="Tarball filename does not match package")
    version = filename[len(basename) + 1 : -len(".tgz")]
    key = _storage_key(repo, name, filename)

    lock_entry = await _acquire_download_lock(key)
    try:
        # Пока ждали замок, файл мог скачать параллельный запрос
        pv = await _cached_version(repo, name, filename, storage)
        if pv is not None:
            _release_download_lock(key, lock_entry)
            return await _serve_blob(storage, pv)

        url = f"{_upstream_root(repo)}/{_quote_name(name)}/-/{filename}"
        client = httpx.AsyncClient(
            follow_redirects=True, timeout=httpx.Timeout(60.0, connect=10.0)
        )
        try:
            response = await client.send(client.build_request("GET", url), stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"Upstream unavailable: {exc}") from exc
        if response.status_code == 404:
            await response.aclose()
            await client.aclose()
            raise HTTPException(status_code=404, detail="Tarball not found on upstream")
        if response.status_code != 200:
            await response.aclose()
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"Upstream returned {response.status_code}")
    except BaseException:
        _release_download_lock(key, lock_entry)
        raise

    return StreamingResponse(
        _stream_and_cache(repo, name, version, key, storage, client, response, lock_entry),
        media_type="application/octet-stream",
    )


@router.get("/npm/{repo_name}/@{scope}/{pkg_name}/-/{filename}")
async def tarball_scoped(
    request: Request,
    scope: str,
    pkg_name: str,
    filename: str,
    repo: Repository = Depends(read_access),
    storage: IStorageProvider = Depends(get_storage),
):
    return await _download_tarball(request, repo, f"@{scope}/{pkg_name}", filename, storage)


@router.get("/npm/{repo_name}/{pkg_name}/-/{filename}")
async def tarball(
    request: Request,
    pkg_name: str,
    filename: str,
    repo: Repository = Depends(read_access),
    storage: IStorageProvider = Depends(get_storage),
):
    return await _download_tarball(request, repo, pkg_name, filename, storage)


# --- Packument и манифест версии ---------------------------------------------------

async def _get_packument(request: Request, repo: Repository, name: str) -> dict:
    _check_name(name)
    if repo.type == RepoType.HOSTED:
        packument = await _packument_from_db(request, repo, name)
        if packument is None:
            raise HTTPException(status_code=404, detail=f"Package '{name}' not found")
        return packument

    try:
        upstream = await _fetch_upstream_packument(repo, name)
        return _rewrite_packument(request, repo, upstream)
    except HTTPException as exc:
        if exc.status_code == 502:
            # Upstream недоступен — офлайн-фолбэк из закэшированных версий
            cached = await _packument_from_db(request, repo, name)
            if cached is not None:
                return cached
        raise


async def _get_version_doc(request: Request, repo: Repository, name: str, version: str) -> dict:
    packument = await _get_packument(request, repo, name)
    versions = packument.get("versions") or {}
    if version in versions:
        return versions[version]
    resolved = (packument.get("dist-tags") or {}).get(version)  # npm позволяет GET /pkg/latest
    if resolved and resolved in versions:
        return versions[resolved]
    raise HTTPException(status_code=404, detail=f"Version '{version}' not found")


@router.get("/npm/{repo_name}/@{scope}/{pkg_name}/{version}")
async def version_doc_scoped(
    request: Request,
    scope: str,
    pkg_name: str,
    version: str,
    repo: Repository = Depends(read_access),
):
    return await _get_version_doc(request, repo, f"@{scope}/{pkg_name}", version)


@router.get("/npm/{repo_name}/@{scope}/{pkg_name}")
async def packument_scoped(
    request: Request,
    scope: str,
    pkg_name: str,
    repo: Repository = Depends(read_access),
):
    return await _get_packument(request, repo, f"@{scope}/{pkg_name}")


@router.get("/npm/{repo_name}/{pkg_name}/{version}")
async def version_doc(
    request: Request,
    pkg_name: str,
    version: str,
    repo: Repository = Depends(read_access),
):
    return await _get_version_doc(request, repo, pkg_name, version)


@router.get("/npm/{repo_name}/{pkg_name}")
async def packument(
    request: Request,
    pkg_name: str,
    repo: Repository = Depends(read_access),
):
    return await _get_packument(request, repo, pkg_name)


# --- Publish (hosted) ----------------------------------------------------------------

async def _publish(
    request: Request,
    repo: Repository,
    name: str,
    user: User,
    storage: IStorageProvider,
):
    if repo.type != RepoType.HOSTED:
        raise HTTPException(status_code=400, detail="Publish is allowed only to hosted repositories")
    _check_name(name)

    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid publish payload")

    if body.get("name") != name:
        raise HTTPException(status_code=400, detail="Package name mismatch")

    versions: dict = body.get("versions") or {}
    attachments: dict = body.get("_attachments") or {}
    if len(versions) != 1 or len(attachments) != 1:
        raise HTTPException(
            status_code=400, detail="Expected exactly one version and one attachment"
        )

    version, manifest = next(iter(versions.items()))
    (_, attachment) = next(iter(attachments.items()))
    try:
        data = base64.b64decode(attachment.get("data") or "", validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid base64 attachment")
    if not data:
        raise HTTPException(status_code=400, detail="Empty attachment")

    pkg = await Package.get_or_none(repository=repo, name=name)
    if pkg is not None and await PackageVersion.exists(package=pkg, version=version):
        raise HTTPException(
            status_code=409, detail=f"Cannot publish over existing version {version}"
        )

    filename = _tarball_filename(name, version)
    blob = await storage.upload_file(_storage_key(repo, name, filename), _iter_bytes(data))

    # Метаданные: приоритет — package.json из tgz, фолбэк — манифест из тела запроса
    package_json = _extract_package_json(data)
    stored_manifest = dict(manifest) if isinstance(manifest, dict) else {}
    stored_manifest.pop("dist", None)
    if package_json:
        stored_manifest["dependencies"] = package_json.get("dependencies") or stored_manifest.get(
            "dependencies"
        ) or {}
        stored_manifest.setdefault("description", package_json.get("description"))

    await _save_version_metadata(
        repo,
        name,
        version,
        stored_manifest,
        blob.key,
        blob.size,
        shasum=hashlib.sha1(data).hexdigest(),
        integrity="sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        dist_tags=body.get("dist-tags") or {},
        user=user,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"ok": True, "id": name, "rev": version, "success": True},
    )


@router.put("/npm/{repo_name}/@{scope}/{pkg_name}")
async def publish_scoped(
    request: Request,
    scope: str,
    pkg_name: str,
    repo: Repository = Depends(write_access),
    user: User = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage),
):
    return await _publish(request, repo, f"@{scope}/{pkg_name}", user, storage)


@router.put("/npm/{repo_name}/{pkg_name}")
async def publish(
    request: Request,
    pkg_name: str,
    repo: Repository = Depends(write_access),
    user: User = Depends(get_current_user),
    storage: IStorageProvider = Depends(get_storage),
):
    return await _publish(request, repo, pkg_name, user, storage)

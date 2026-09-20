import hashlib
from pathlib import Path
from typing import AsyncIterator

import aiofiles
import aiofiles.os

from app.storage.base import IStorageProvider, StoredBlob

CHUNK_SIZE = 1024 * 1024  # 1 MiB


class LocalStorageProvider(IStorageProvider):
    """Хранит блобы на локальном диске в base_dir (по умолчанию ./storage)."""

    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        # Защита от path traversal: итоговый путь обязан лежать внутри base_dir
        target = (self._base / key).resolve()
        if not target.is_relative_to(self._base):
            raise ValueError(f"Illegal storage key: {key!r}")
        return target

    async def upload_file(self, key: str, stream: AsyncIterator[bytes]) -> StoredBlob:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256()
        size = 0
        # Пишем во временный файл и атомарно переименовываем,
        # чтобы параллельный GET не увидел недокачанный блоб
        tmp = target.with_name(target.name + ".part")
        try:
            async with aiofiles.open(tmp, "wb") as f:
                async for chunk in stream:
                    digest.update(chunk)
                    size += len(chunk)
                    await f.write(chunk)
            await aiofiles.os.replace(tmp, target)
        except BaseException:  # включая CancelledError — обрыв не должен оставить .part
            if tmp.exists():
                await aiofiles.os.remove(tmp)
            raise

        return StoredBlob(key=key, size=size, sha256=digest.hexdigest())

    async def download_file(self, key: str) -> AsyncIterator[bytes]:
        target = self._resolve(key)
        if not target.is_file():
            raise FileNotFoundError(key)
        async with aiofiles.open(target, "rb") as f:
            while chunk := await f.read(CHUNK_SIZE):
                yield chunk

    async def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).is_file()
        except ValueError:
            return False

    async def delete_file(self, key: str) -> None:
        target = self._resolve(key)
        if target.is_file():
            await aiofiles.os.remove(target)

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class StoredBlob:
    """Результат загрузки блоба в хранилище."""

    key: str
    size: int
    sha256: str


class IStorageProvider(ABC):
    """Абстракция блоб-хранилища.

    Бизнес-логика (роуты hosted/proxy) работает только с этим интерфейсом
    и не знает, где физически лежат файлы. Ключ (key) — логический путь
    вида "<repo_name>/<artifact_path>".

    Реализации: LocalStorageProvider (MVP), в будущем MinioStorageProvider (S3 API).
    """

    @abstractmethod
    async def upload_file(self, key: str, stream: AsyncIterator[bytes]) -> StoredBlob:
        """Записать блоб из асинхронного потока байтов. Возвращает size и sha256."""

    @abstractmethod
    def download_file(self, key: str) -> AsyncIterator[bytes]:
        """Асинхронный поток байтов блоба. Бросает FileNotFoundError, если блоба нет."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Есть ли блоб с таким ключом."""

    @abstractmethod
    async def delete_file(self, key: str) -> None:
        """Удалить блоб; отсутствие блоба не считается ошибкой."""

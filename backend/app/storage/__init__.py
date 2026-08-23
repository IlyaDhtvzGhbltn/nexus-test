from app.config import get_settings
from app.storage.base import IStorageProvider
from app.storage.local import LocalStorageProvider

_provider: IStorageProvider | None = None


def get_storage() -> IStorageProvider:
    """FastAPI-зависимость: единая точка получения провайдера хранилища.

    Чтобы перейти на MinIO/S3, достаточно вернуть здесь MinioStorageProvider —
    бизнес-логика роутов не изменится.
    """
    global _provider
    if _provider is None:
        _provider = LocalStorageProvider(get_settings().storage_path)
    return _provider

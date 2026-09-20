from app.config import get_settings
from app.storage.base import IStorageProvider
from app.storage.local import LocalStorageProvider

_provider: IStorageProvider | None = None


def get_storage() -> IStorageProvider:
    """FastAPI-зависимость: единая точка получения провайдера хранилища.

    Выбор провайдера — переменной окружения STORAGE_PROVIDER:
      local — диск текущей ноды (dev/простой запуск),
      minio — общее S3-хранилище (обязателен для нескольких нод бэкенда).
    Бизнес-логика роутов от выбора не зависит.
    """
    global _provider
    if _provider is None:
        settings = get_settings()
        if settings.storage_provider == "minio":
            from app.storage.minio import MinioStorageProvider

            _provider = MinioStorageProvider(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                bucket=settings.minio_bucket,
                region=settings.minio_region,
            )
        else:
            _provider = LocalStorageProvider(settings.storage_path)
    return _provider

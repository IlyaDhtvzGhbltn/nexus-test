from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Конфигурация приложения. Все значения переопределяются переменными окружения."""

    # Обязателен (env DATABASE_URL) — дефолта с учётными данными нет намеренно
    database_url: str = ""

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 8

    # Провайдер блоб-хранилища: "local" (диск одной ноды) или "minio" (общий склад, S3 API)
    storage_provider: str = "local"

    # Куда LocalStorageProvider складывает блобы
    storage_path: str = "./storage"

    # Настройки MinioStorageProvider
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "artifacts"
    minio_region: str = "us-east-1"

    # Bootstrap-суперадмин, создаваемый при первом старте.
    # Пароль обязателен (минимум 12 символов) — дефолта нет намеренно.
    initial_admin_login: str = "admin"
    initial_admin_password: str = ""

    # Сколько дней хранить журналы аудита (требование: не менее 90)
    audit_retention_days: int = 90

    # RabbitMQ (пусто = события отключены: аудит пишется напрямую, сканирования нет)
    rabbitmq_url: str = ""
    scan_queue: str = "scan-tasks"
    audit_queue: str = "download-audit"

    # Jobber / Trivy
    trivy_path: str = "trivy"
    trivy_timeout_seconds: int = 300
    # Какие уровни уязвимостей отправляют версию в карантин
    quarantine_severities: str = "CRITICAL,HIGH"
    # Плановая перепроверка: раз в N часов проверять версии,
    # не сканированные дольше M дней
    rescan_interval_hours: int = 24
    rescan_max_age_days: int = 7

    # Разрешённые origin'ы для CORS (dev-фронтенд)
    cors_origins: str = "http://localhost:5173"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()

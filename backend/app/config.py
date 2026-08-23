from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Конфигурация приложения. Все значения переопределяются переменными окружения."""

    database_url: str = "postgres://artifact:artifact@localhost:5432/artifact_repo"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 8

    # Куда LocalStorageProvider складывает блобы
    storage_path: str = "./storage"

    # Учётка администратора, создаваемая при первом старте
    initial_admin_login: str = "admin"
    initial_admin_password: str = "admin"

    # Разрешённые origin'ы для CORS (dev-фронтенд)
    cors_origins: str = "http://localhost:5173"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()

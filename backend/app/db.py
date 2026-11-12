import importlib.util

from app.config import get_settings

settings = get_settings()

if not settings.database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. Provide it via environment "
        "(docker-compose reads it from .env, see .env.example)."
    )

_models = ["app.models"]
# aerich нужен только для миграций; приложение работает и без него
if importlib.util.find_spec("aerich") is not None:
    _models.append("aerich.models")

# Конфиг Tortoise-ORM. Используется и приложением, и aerich для миграций:
#   aerich init -t app.db.TORTOISE_ORM
#   aerich init-db / aerich migrate / aerich upgrade
TORTOISE_ORM = {
    "connections": {"default": settings.database_url},
    "apps": {
        "models": {
            "models": _models,
            "default_connection": "default",
        }
    },
}

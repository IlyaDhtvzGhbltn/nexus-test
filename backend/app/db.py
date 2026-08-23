import importlib.util

from app.config import get_settings

settings = get_settings()

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

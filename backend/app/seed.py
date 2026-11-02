import logging

from app.config import get_settings
from app.models import User
from app.security import hash_password

logger = logging.getLogger(__name__)

MIN_SUPERADMIN_PASSWORD_LEN = 12


async def seed_initial_data() -> None:
    """Создание bootstrap-суперадмина при первом старте (если юзеров ещё нет).

    Пароль обязан быть задан через INITIAL_ADMIN_PASSWORD и быть не короче
    12 символов — без этого аккаунт не создаётся. Рекомендуемый порядок работы:
    суперадмином создать персональные админ-аккаунты, затем деактивировать
    bootstrap-аккаунт (любой другой активный суперадмин может включить его обратно).
    """
    if await User.exists():
        return

    settings = get_settings()
    password = settings.initial_admin_password
    if len(password) < MIN_SUPERADMIN_PASSWORD_LEN:
        logger.error(
            "INITIAL_ADMIN_PASSWORD is missing or shorter than %d characters — "
            "bootstrap superadmin was NOT created. Set a strong password and restart.",
            MIN_SUPERADMIN_PASSWORD_LEN,
        )
        return

    await User.create(
        login=settings.initial_admin_login,
        hashed_password=hash_password(password),
        is_superadmin=True,
    )
    logger.warning(
        "Created bootstrap superadmin '%s'. Create personal admin accounts "
        "and deactivate this one.",
        settings.initial_admin_login,
    )

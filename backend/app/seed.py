import logging

from app.config import get_settings
from app.models import Role, User
from app.security import ADMIN_ROLE, hash_password

logger = logging.getLogger(__name__)

async def seed_initial_data() -> None:
    """Идемпотентный сид: роль ADMIN + первый администратор.

    Других ролей по умолчанию нет — их создаёт админ через /api/roles.
    """
    await Role.get_or_create(name=ADMIN_ROLE)

    settings = get_settings()
    if not await User.exists():
        admin = await User.create(
            login=settings.initial_admin_login,
            hashed_password=hash_password(settings.initial_admin_password),
        )
        admin_role = await Role.get(name=ADMIN_ROLE)
        await admin.roles.add(admin_role)
        logger.warning(
            "Created initial admin '%s' with default password — change it immediately!",
            settings.initial_admin_login,
        )

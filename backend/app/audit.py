"""Запись журналов аудита.

Обе функции best-effort: сбой записи аудита логируется, но не ломает
само действие (выдачу пакета или админ-операцию).
"""

import logging

from app.models import DownloadAuditLog, OperatorAuditLog, Repository, User

logger = logging.getLogger(__name__)


async def log_download(
    user: User,
    repo: Repository,
    package_name: str,
    package_version: str,
    user_agent: str | None,
) -> None:
    """Фиксирует успешную выдачу пакета клиенту."""
    try:
        await DownloadAuditLog.create(
            user=user,
            user_login=user.login,
            repository=repo,
            repository_name=repo.name,
            package_name=package_name,
            package_version=package_version,
            user_agent=(user_agent or "")[:512] or None,
        )
    except Exception:
        logger.exception(
            "Failed to write download audit log for %s@%s", package_name, package_version
        )


async def log_operator(
    actor: User, action: str, target: str, details: dict | None = None
) -> None:
    """Фиксирует действие оператора (admin API)."""
    try:
        await OperatorAuditLog.create(
            actor=actor,
            actor_login=actor.login,
            action=action,
            target=target[:512],
            details=details or {},
        )
    except Exception:
        logger.exception("Failed to write operator audit log for %s %s", action, target)

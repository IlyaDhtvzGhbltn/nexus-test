"""Запись журналов аудита.

Обе функции best-effort: сбой записи аудита логируется, но не ломает
само действие (выдачу пакета или админ-операцию).
"""

import logging

from app import events
from app.models import DownloadAuditLog, OperatorAuditLog, Repository, User

logger = logging.getLogger(__name__)


async def store_download_audit(payload: dict) -> None:
    """Записывает факт выдачи в БД. Вызывается напрямую (фолбэк) или Jobber'ом
    при разборе очереди download-audit."""
    await DownloadAuditLog.create(
        user_id=payload.get("user_id"),
        user_login=payload["user_login"],
        repository_id=payload.get("repository_id"),
        repository_name=payload["repository_name"],
        package_name=payload["package_name"],
        package_version=payload["package_version"],
        user_agent=payload.get("user_agent"),
    )


async def log_download(
    user: User,
    repo: Repository,
    package_name: str,
    package_version: str,
    user_agent: str | None,
) -> None:
    """Фиксирует успешную выдачу пакета клиенту.

    При включённом RabbitMQ запись уходит в очередь (не тормозит выдачу),
    иначе — синхронная вставка. Сбой аудита выдачу не ломает.
    """
    payload = {
        "user_id": user.id,
        "user_login": user.login,
        "repository_id": repo.id,
        "repository_name": repo.name,
        "package_name": package_name,
        "package_version": package_version,
        "user_agent": (user_agent or "")[:512] or None,
    }
    try:
        if await events.publish_download_audit(payload):
            return
        await store_download_audit(payload)
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


async def log_system(action: str, target: str, details: dict | None = None) -> None:
    """Фиксирует действие системы (сканер Jobber) в операторском журнале."""
    try:
        await OperatorAuditLog.create(
            actor=None,
            actor_login="jobber",
            action=action,
            target=target[:512],
            details=details or {},
        )
    except Exception:
        logger.exception("Failed to write system audit log for %s %s", action, target)

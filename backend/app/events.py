"""Публикация событий в RabbitMQ (best-effort).

Если RABBITMQ_URL не задан — события отключены: публикация молча возвращает
False, и вызывающий код использует синхронный фолбэк. Сбой брокера не должен
ломать выдачу или публикацию пакетов — недостающие сканирования подберёт
плановая перепроверка Jobber'а.
"""

import asyncio
import json
import logging

import aio_pika

from app.config import get_settings

logger = logging.getLogger(__name__)

_connection: aio_pika.abc.AbstractRobustConnection | None = None
_channel: aio_pika.abc.AbstractChannel | None = None
_lock = asyncio.Lock()


def enabled() -> bool:
    return bool(get_settings().rabbitmq_url)


async def _get_channel() -> aio_pika.abc.AbstractChannel:
    global _connection, _channel
    if _channel is not None and not _channel.is_closed:
        return _channel
    async with _lock:
        if _channel is not None and not _channel.is_closed:
            return _channel
        settings = get_settings()
        _connection = await aio_pika.connect_robust(settings.rabbitmq_url, timeout=5)
        _channel = await _connection.channel()
        # Очереди объявляет и издатель: сообщения не теряются, пока Jobber не поднялся
        await _channel.declare_queue(settings.scan_queue, durable=True)
        await _channel.declare_queue(settings.audit_queue, durable=True)
    return _channel


async def publish(queue_name: str, payload: dict) -> bool:
    if not enabled():
        return False
    try:
        channel = await _get_channel()
        await channel.default_exchange.publish(
            aio_pika.Message(
                json.dumps(payload).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key=queue_name,
        )
        return True
    except Exception:
        logger.exception("Failed to publish to queue '%s'", queue_name)
        return False


async def publish_scan_task(
    package_version_id: int, repository_id: int, package_name: str, version: str
) -> bool:
    """ArtifactStoredEvent: новый блоб сохранён — Jobber должен его проверить."""
    return await publish(
        get_settings().scan_queue,
        {
            "event": "artifact_stored",
            "package_version_id": package_version_id,
            "repository_id": repository_id,
            "package_name": package_name,
            "version": version,
        },
    )


async def publish_download_audit(payload: dict) -> bool:
    return await publish(get_settings().audit_queue, payload)


async def close() -> None:
    global _connection, _channel
    if _connection is not None:
        try:
            await _connection.close()
        except Exception:
            pass
    _connection = None
    _channel = None

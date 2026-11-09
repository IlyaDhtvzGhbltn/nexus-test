"""Jobber — асинхронный воркер карантина.

Потребляет из RabbitMQ:
  - scan-tasks       — проверка новых артефактов Trivy (event-driven);
  - download-audit   — запись журнала скачиваний (разгрузка бэкенда).

Плюс плановый цикл: раз в RESCAN_INTERVAL_HOURS ставит в очередь версии,
не сканированные дольше RESCAN_MAX_AGE_DAYS (перепроверка обновлёнными базами).

Запуск: python -m app.jobber.main (отдельный контейнер, код общий с бэкендом).
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import aio_pika
from tortoise import Tortoise
from tortoise.expressions import Q

from app import events
from app.audit import store_download_audit
from app.config import get_settings
from app.db import TORTOISE_ORM
from app.jobber.scanner import scan_package_version
from app.models import PackageVersion, QuarantineStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _handle_scan(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    async with message.process(ignore_processed=True):
        try:
            payload = json.loads(message.body)
        except ValueError:
            logger.error("Malformed scan message dropped: %r", message.body[:200])
            return
        pv_id = payload.get("package_version_id")
        if pv_id is not None:
            # Ошибка скана не роняет консьюмер: версия останется с last_scanned_at=NULL
            # и будет подхвачена плановой перепроверкой
            await scan_package_version(pv_id)


async def _handle_audit(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    async with message.process(ignore_processed=True):
        try:
            payload = json.loads(message.body)
            await store_download_audit(payload)
        except Exception:
            logger.exception("Failed to store download audit from queue")


async def _rescan_loop() -> None:
    settings = get_settings()
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.rescan_max_age_days)
            # UNKNOWN проверяется при каждом обходе (это «не имеет валидного вердикта»),
            # CLEAN — только если скан старше rescan_max_age_days
            stale_ids = await PackageVersion.filter(
                Q(quarantine_status=QuarantineStatus.UNKNOWN)
                | (
                    Q(quarantine_status=QuarantineStatus.CLEAN)
                    & (Q(last_scanned_at__isnull=True) | Q(last_scanned_at__lt=cutoff))
                )
            ).values_list("id", flat=True)
            if stale_ids:
                logger.info("Rescan: queueing %d package versions", len(stale_ids))
            for pv_id in stale_ids:
                await events.publish(settings.scan_queue, {"package_version_id": pv_id})
        except Exception:
            logger.exception("Rescan scheduling failed")
        await asyncio.sleep(settings.rescan_interval_hours * 3600)


async def main() -> None:
    settings = get_settings()
    if not settings.rabbitmq_url:
        raise SystemExit("RABBITMQ_URL is required for the jobber")

    await Tortoise.init(config=TORTOISE_ORM)

    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)  # сканируем по одному

    scan_queue = await channel.declare_queue(settings.scan_queue, durable=True)
    audit_queue = await channel.declare_queue(settings.audit_queue, durable=True)
    await scan_queue.consume(_handle_scan)
    await audit_queue.consume(_handle_audit)

    rescan_task = asyncio.create_task(_rescan_loop())
    logger.info("Jobber started: consuming '%s' and '%s'",
                settings.scan_queue, settings.audit_queue)
    try:
        await asyncio.Future()  # работаем, пока не остановят
    finally:
        rescan_task.cancel()
        await connection.close()
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())

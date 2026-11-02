import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.config import get_settings
from app.db import TORTOISE_ORM
from app.models import DownloadAuditLog, OperatorAuditLog
from app.routers import audit, auth, npm, repositories, users
from app.seed import seed_initial_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AUDIT_CLEANUP_INTERVAL = 24 * 3600  # раз в сутки


async def _audit_cleanup_loop() -> None:
    """Чистка журналов аудита старше retention-срока (по умолчанию 90 дней)."""
    retention_days = max(1, get_settings().audit_retention_days)
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            removed = await DownloadAuditLog.filter(downloaded_at__lt=cutoff).delete()
            removed += await OperatorAuditLog.filter(created_at__lt=cutoff).delete()
            if removed:
                logger.info("Audit cleanup: removed %d records older than %d days",
                            removed, retention_days)
        except Exception:
            logger.exception("Audit cleanup failed")
        await asyncio.sleep(AUDIT_CLEANUP_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP: схема создаётся напрямую (generate_schemas). В продакшене — миграции aerich
    # (aerich init -t app.db.TORTOISE_ORM && aerich init-db / upgrade).
    async with RegisterTortoise(app, config=TORTOISE_ORM, generate_schemas=True):
        await seed_initial_data()
        cleanup_task = asyncio.create_task(_audit_cleanup_loop())
        try:
            yield
        finally:
            cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup_task


app = FastAPI(
    title="Artifact Repository",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(repositories.router)
app.include_router(audit.router)
app.include_router(npm.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}

"""Сканирование версии пакета Trivy.

Логика: скачать tgz из IStorageProvider во временную папку, распаковать,
подложить синтетический package-lock.json (сам пакет с точной версией — чтобы
Trivy проверил его по базе уязвимостей), запустить `trivy fs`, разобрать отчёт.

Вердикт: находки с уровнем из QUARANTINE_SEVERITIES (по умолчанию CRITICAL,HIGH)
переводят версию в QUARANTINED, иначе — CLEAN. WHITELISTED не трогается.
Ошибка сканирования оставляет статус как есть и не проставляет last_scanned_at —
такую версию подберёт следующая плановая перепроверка.
"""

import asyncio
import json
import logging
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import aiofiles

from app.audit import log_system
from app.config import get_settings
from app.models import PackageVersion, QuarantineStatus
from app.storage import get_storage

logger = logging.getLogger(__name__)

MAX_FINDINGS_STORED = 100


def _synthetic_lockfile(name: str, version: str) -> dict:
    """Минимальный package-lock.json v3: пакет с точной версией для базы Trivy."""
    return {
        "name": "scan-root",
        "version": "0.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {"name": "scan-root", "version": "0.0.0", "dependencies": {name: version}},
            f"node_modules/{name}": {"version": version},
        },
    }


def _run_trivy(target_dir: str) -> dict:
    """Синхронный запуск Trivy (вызывается через to_thread)."""
    settings = get_settings()
    result = subprocess.run(
        [
            settings.trivy_path, "fs",
            "--scanners", "vuln",
            "--format", "json",
            "--quiet",
            target_dir,
        ],
        capture_output=True,
        timeout=settings.trivy_timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"trivy exited with {result.returncode}: {result.stderr.decode(errors='replace')[:500]}"
        )
    return json.loads(result.stdout)


def _parse_findings(report: dict) -> list[dict]:
    findings = []
    for res in report.get("Results") or []:
        for vuln in res.get("Vulnerabilities") or []:
            findings.append(
                {
                    "id": vuln.get("VulnerabilityID"),
                    "package": vuln.get("PkgName"),
                    "installed": vuln.get("InstalledVersion"),
                    "severity": (vuln.get("Severity") or "UNKNOWN").upper(),
                    "title": (vuln.get("Title") or "")[:200],
                }
            )
    return findings


async def scan_package_version(pv_id: int) -> str | None:
    """Проверяет одну версию; возвращает итоговый статус или None (скип/ошибка)."""
    pv = await PackageVersion.get_or_none(id=pv_id).prefetch_related("package__repository")
    if pv is None:
        logger.info("Scan task for missing version id=%s — skipped", pv_id)
        return None
    name = pv.package.name
    repo_name = pv.package.repository.name
    label = f"{name}@{pv.version} in {repo_name}"

    if pv.quarantine_status == QuarantineStatus.WHITELISTED:
        logger.info("Skip scan of whitelisted %s", label)
        return None

    settings = get_settings()
    storage = get_storage()
    try:
        with tempfile.TemporaryDirectory(prefix="jobber_") as tmp:
            tmp_path = Path(tmp)
            tgz_path = tmp_path / "package.tgz"
            async with aiofiles.open(tgz_path, "wb") as f:
                async for chunk in storage.download_file(pv.storage_key):
                    await f.write(chunk)

            content_dir = tmp_path / "content"
            content_dir.mkdir()
            try:
                with tarfile.open(tgz_path, "r:gz") as tf:
                    tf.extractall(content_dir, filter="data")  # защита от traversal
            except (tarfile.TarError, OSError) as exc:
                logger.warning("Cannot extract %s: %s — scanning lockfile only", label, exc)
            tgz_path.unlink()

            meta_dir = tmp_path / "meta"
            meta_dir.mkdir()
            (meta_dir / "package-lock.json").write_text(
                json.dumps(_synthetic_lockfile(name, pv.version))
            )

            report = await asyncio.to_thread(_run_trivy, str(tmp_path))
    except Exception as exc:
        logger.error("Scan of %s failed: %s", label, exc)
        return None

    findings = _parse_findings(report)
    bad_levels = {s.strip().upper() for s in settings.quarantine_severities.split(",") if s.strip()}
    quarantine = any(f["severity"] in bad_levels for f in findings)
    new_status = QuarantineStatus.QUARANTINED if quarantine else QuarantineStatus.CLEAN

    old_status = pv.quarantine_status
    pv.scan_findings = findings[:MAX_FINDINGS_STORED]
    pv.last_scanned_at = datetime.now(timezone.utc)
    pv.quarantine_status = new_status
    await pv.save()

    if old_status != new_status:
        await log_system(
            "scan.result",
            label,
            {
                "from": old_status.value,
                "to": new_status.value,
                "findings": len(findings),
                "ids": [f["id"] for f in findings[:10]],
            },
        )
    logger.info("Scanned %s: %s (%d findings)", label, new_status.value, len(findings))
    return new_status.value

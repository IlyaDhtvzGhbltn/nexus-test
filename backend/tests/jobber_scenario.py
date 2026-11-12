"""Сценарий полного конвейера карантина: RabbitMQ + Jobber + настоящий Trivy.

Запускается как отдельный процесс (см. test_jobber_pipeline.py) — у него своё
окружение с включённым RabbitMQ, не конфликтующее с основным набором тестов.

Требования: доступный RabbitMQ (env RABBITMQ_URL), trivy в PATH или TRIVY_PATH,
интернет при первом запуске (Trivy качает базу уязвимостей).
"""

import asyncio
import hashlib
import json
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, TESTS_DIR)

ADMIN_PW = "pytest-superadmin-pw-1"
TMP = tempfile.mkdtemp(prefix="jobber_pipeline_")

assert os.environ.get("RABBITMQ_URL"), "RABBITMQ_URL обязателен для этого сценария"
os.environ["DATABASE_URL"] = "sqlite://" + os.path.join(TMP, "test.db").replace("\\", "/")
os.environ.setdefault("STORAGE_PATH", os.path.join(TMP, "storage"))
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef-0123456789"
os.environ["INITIAL_ADMIN_PASSWORD"] = ADMIN_PW
os.environ.setdefault("TRIVY_CACHE_DIR", os.path.join(tempfile.gettempdir(), "trivy-cache"))

import httpx  # noqa: E402
from tortoise import Tortoise  # noqa: E402

from app import events  # noqa: E402
from app.audit import store_download_audit  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import TORTOISE_ORM  # noqa: E402
from app.jobber.scanner import scan_package_version  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DownloadAuditLog, OperatorAuditLog  # noqa: E402
from app.seed import seed_initial_data  # noqa: E402
from helpers import make_tgz, publish_body  # noqa: E402

passed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed
    if not cond:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


async def drain_queue(queue_name: str) -> list[dict]:
    import aio_pika

    settings = get_settings()
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    messages = []
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(queue_name, durable=True)
        while True:
            message = await queue.get(fail=False)
            if message is None:
                break
            messages.append(json.loads(message.body))
            await message.ack()
    return messages


async def main() -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)
    await seed_initial_data()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/api/auth/login", data={"username": "admin", "password": ADMIN_PW})
        check("admin login", r.status_code == 200, r.text)
        admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = await client.post("/api/repositories", json={"name": "npm-hosted", "type": "hosted"},
                              headers=admin)
        check("create repo", r.status_code == 201, r.text)
        repo_id = r.json()["id"]

        # Чистый и заведомо уязвимый (реальный lodash 4.17.20) пакеты
        clean_tgz = make_tgz("mylib-internal", "1.0.0", {})
        r = await client.put("/npm/npm-hosted/mylib-internal",
                             json=publish_body("mylib-internal", "1.0.0", clean_tgz),
                             headers=admin)
        check("publish clean package", r.status_code == 201, r.text)

        vuln_tgz = make_tgz("lodash", "4.17.20", {})
        r = await client.put("/npm/npm-hosted/lodash",
                             json=publish_body("lodash", "4.17.20", vuln_tgz), headers=admin)
        check("publish vulnerable package", r.status_code == 201, r.text)

        # 1. События о сохранённых артефактах — в очереди
        scan_msgs = await drain_queue(get_settings().scan_queue)
        by_name = {m["package_name"]: m for m in scan_msgs}
        check("scan events published", {"mylib-internal", "lodash"} <= set(by_name),
              str(scan_msgs))
        check("scan event payload",
              by_name["lodash"]["version"] == "4.17.20"
              and by_name["lodash"]["repository_id"] == repo_id
              and by_name["lodash"]["event"] == "artifact_stored", str(by_name["lodash"]))
        clean_pv_id = by_name["mylib-internal"]["package_version_id"]
        vuln_pv_id = by_name["lodash"]["package_version_id"]

        # 2. Аудит скачивания через очередь
        r = await client.get("/npm/npm-hosted/mylib-internal/-/mylib-internal-1.0.0.tgz",
                             headers=admin)
        check("download works", r.status_code == 200)
        check("audit row queued, not yet in DB",
              await DownloadAuditLog.filter(package_name="mylib-internal").count() == 0)
        audit_msgs = await drain_queue(get_settings().audit_queue)
        check("audit message in queue",
              len(audit_msgs) == 1 and audit_msgs[0]["package_name"] == "mylib-internal"
              and audit_msgs[0]["user_login"] == "admin", str(audit_msgs))
        await store_download_audit(audit_msgs[0])
        r = await client.get("/api/audit/downloads?package=mylib-internal", headers=admin)
        check("audit row stored by jobber handler", len(r.json()) == 1, r.text)

        # 3. Настоящее сканирование Trivy
        print("... running trivy (первый запуск качает базу уязвимостей, ~1-2 мин)")
        check("clean package -> CLEAN",
              await scan_package_version(clean_pv_id) == "CLEAN")
        check("lodash 4.17.20 -> QUARANTINED",
              await scan_package_version(vuln_pv_id) == "QUARANTINED")

        r = await client.get("/api/security/versions?package=lodash", headers=admin)
        row = r.json()[0]
        check("findings stored",
              len(row["scan_findings"]) >= 1
              and any(f["severity"] in ("HIGH", "CRITICAL") for f in row["scan_findings"]),
              str(row["scan_findings"])[:300])
        check("last_scanned_at set", row["last_scanned_at"] is not None)

        # 4. Вердикт сканера блокирует выдачу
        r = await client.get("/npm/npm-hosted/lodash/-/lodash-4.17.20.tgz", headers=admin)
        check("scanner quarantine blocks download", r.status_code == 403, r.text)

        # 5. Решение сканера — в операторском журнале
        rows = await OperatorAuditLog.filter(action="scan.result")
        check("scan.result audited by 'jobber'",
              any(x.actor_login == "jobber" and "lodash@4.17.20" in x.target for x in rows))

        # 6. Whitelist игнорируется сканером
        r = await client.post("/api/security/whitelist",
                              json={"package_name": "lodash", "version": "4.17.20",
                                    "reason": "accepted risk for the test"}, headers=admin)
        check("whitelist vulnerable version", r.status_code == 201, r.text)
        check("scanner skips whitelisted", await scan_package_version(vuln_pv_id) is None)
        r = await client.get("/api/security/versions?package=lodash", headers=admin)
        check("status stays WHITELISTED", r.json()[0]["quarantine_status"] == "WHITELISTED")

    await events.close()
    await Tortoise.close_connections()
    print(f"\nALL {passed} CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())

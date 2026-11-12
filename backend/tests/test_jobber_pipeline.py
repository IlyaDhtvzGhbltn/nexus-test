"""Полный конвейер карантина (RabbitMQ + Trivy) — опциональный тяжёлый тест.

Запускается подпроцессом: сценарию нужен включённый RabbitMQ, а основной набор
работает с выключенным (настройки кэшируются на процесс — смешивать нельзя).

Пропускается, если не задан RABBITMQ_URL или не найден trivy:
    podman run -d --name rabbit-test -p 5673:5672 rabbitmq:4-alpine
    $env:RABBITMQ_URL = "amqp://guest:guest@localhost:5673/"
    pytest tests/test_jobber_pipeline.py -s
"""

import os
import shutil
import subprocess
import sys

import pytest

SCENARIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobber_scenario.py")


def test_jobber_pipeline():
    rabbitmq_url = os.environ.get("JOBBER_TEST_RABBITMQ_URL") or ""
    if not rabbitmq_url:
        pytest.skip("RABBITMQ_URL не задан — конвейерный тест пропущен")
    trivy = os.environ.get("TRIVY_PATH", "trivy")
    if shutil.which(trivy) is None:
        pytest.skip(f"trivy не найден ({trivy}) — конвейерный тест пропущен")

    env = dict(os.environ)
    env["RABBITMQ_URL"] = rabbitmq_url
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, SCENARIO],
        capture_output=True,
        encoding="utf-8",
        errors="replace",  # Windows-консоль по умолчанию cp1252
        timeout=900,  # первый запуск Trivy качает базу уязвимостей
        env=env,
    )
    assert result.returncode == 0, f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert "ALL" in result.stdout and "CHECKS PASSED" in result.stdout, result.stdout

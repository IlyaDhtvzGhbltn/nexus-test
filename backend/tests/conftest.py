"""Конфигурация тестов.

Окружение настраивается ДО импорта приложения (настройки кэшируются при старте):
- БД — одноразовый SQLite-файл (Postgres не нужен);
- хранилище — локальная папка; для прогона против MinIO задайте снаружи
  STORAGE_PROVIDER=minio и MINIO_ENDPOINT (см. README);
- RabbitMQ принудительно выключен: события не публикуются, аудит пишется
  синхронно. Полный конвейер с очередями проверяет test_jobber_pipeline
  (отдельный подпроцесс), которому исходный RABBITMQ_URL передаётся через
  JOBBER_TEST_RABBITMQ_URL.
"""

import http.server
import json
import os
import sys
import tempfile
import threading
import time
from threading import Lock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

ADMIN_PW = "pytest-superadmin-pw-1"
_TMP = tempfile.mkdtemp(prefix="artifact_tests_")

os.environ["JOBBER_TEST_RABBITMQ_URL"] = os.environ.get("RABBITMQ_URL", "")
os.environ["RABBITMQ_URL"] = ""
os.environ["DATABASE_URL"] = "sqlite://" + os.path.join(_TMP, "test.db").replace("\\", "/")
os.environ.setdefault("STORAGE_PATH", os.path.join(_TMP, "storage"))
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef-0123456789"
os.environ["INITIAL_ADMIN_PASSWORD"] = ADMIN_PW

import hashlib  # noqa: E402

import pytest  # noqa: E402

from helpers import make_tgz  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """TestClient с прогоном lifespan (создание схемы + сид суперадмина)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


class FakeUpstream:
    """Мини-реестр npm на локальном порту: packument + tgz для proxy-тестов.

    Считает обращения по путям (single-flight) и притормаживает отдачу
    solo-пакета, чтобы параллельные запросы гарантированно пересеклись.
    """

    def __init__(self) -> None:
        self.dir = os.path.join(_TMP, "upstream")
        self.hits: dict[str, int] = {}
        self._hits_lock = Lock()

        os.makedirs(os.path.join(self.dir, "left-pad", "-"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "solo", "-"), exist_ok=True)

        self.left_pad_tgz = make_tgz("left-pad", "1.3.0", {"wcwidth": "^1.0.0"})
        with open(os.path.join(self.dir, "left-pad", "-", "left-pad-1.3.0.tgz"), "wb") as f:
            f.write(self.left_pad_tgz)
        self.solo_tgz = make_tgz("solo", "1.0.0", {"dep-a": "^2.0.0"})
        with open(os.path.join(self.dir, "solo", "-", "solo-1.0.0.tgz"), "wb") as f:
            f.write(self.solo_tgz)
        # >8 МБ несжимаемых данных: проверка стриминга и фолбэка метаданных
        self.big_tgz = make_tgz("left-pad", "9.9.9", {}, payload=os.urandom(10 * 1024 * 1024))
        with open(os.path.join(self.dir, "left-pad", "-", "left-pad-9.9.9.tgz"), "wb") as f:
            f.write(self.big_tgz)

        upstream = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=upstream.dir, **kwargs)

            def do_GET(self):
                with upstream._hits_lock:
                    upstream.hits[self.path] = upstream.hits.get(self.path, 0) + 1
                if "solo-1.0.0.tgz" in self.path:
                    time.sleep(0.5)
                super().do_GET()

            def log_message(self, *args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._alive = True

        with open(os.path.join(self.dir, "left-pad", "index.html"), "w") as f:
            json.dump({
                "name": "left-pad",
                "dist-tags": {"latest": "1.3.0"},
                "versions": {"1.3.0": {
                    "name": "left-pad", "version": "1.3.0",
                    "dependencies": {"wcwidth": "^1.0.0"},
                    "dist": {
                        "tarball": f"{self.url}/left-pad/-/left-pad-1.3.0.tgz",
                        "shasum": hashlib.sha1(self.left_pad_tgz).hexdigest(),
                    },
                }},
            }, f)

    def shutdown(self) -> None:
        if self._alive:
            self._alive = False
            self._server.shutdown()


@pytest.fixture(scope="session")
def upstream():
    fake = FakeUpstream()
    yield fake
    fake.shutdown()

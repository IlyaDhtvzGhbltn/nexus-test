import base64
import hashlib
import io
import json
import tarfile


def make_tgz(name: str, version: str, dependencies: dict,
             payload: bytes = b"console.log('hi');") -> bytes:
    """Настоящий npm-tgz: package/package.json + package/index.js."""
    pj = json.dumps({
        "name": name,
        "version": version,
        "description": f"{name} test package",
        "dependencies": dependencies,
    }).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("package/package.json")
        info.size = len(pj)
        tf.addfile(info, io.BytesIO(pj))
        info2 = tarfile.TarInfo("package/index.js")
        info2.size = len(payload)
        tf.addfile(info2, io.BytesIO(payload))
    return buf.getvalue()


def publish_body(name: str, version: str, tgz: bytes, deps: dict | None = None) -> dict:
    """Тело PUT-запроса, которое шлёт npm publish (манифест + base64-вложение)."""
    filename = f"{name.split('/')[-1]}-{version}.tgz"
    return {
        "_id": name,
        "name": name,
        "dist-tags": {"latest": version},
        "versions": {
            version: {
                "name": name,
                "version": version,
                "description": f"{name} test package",
                "dependencies": deps or {},
                "dist": {
                    "tarball": f"http://example/{filename}",
                    "shasum": hashlib.sha1(tgz).hexdigest(),
                },
            }
        },
        "_attachments": {
            filename: {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(tgz).decode(),
                "length": len(tgz),
            }
        },
    }


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

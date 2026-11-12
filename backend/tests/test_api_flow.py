"""Интеграционный сценарий поверх HTTP API: RBAC, npm-протокол, прокси,
карантин, аудит. Портирован из smoke-набора, которым проверялся каждый этап.

Тесты последовательные и разделяют состояние через `ctx` — выполнять файл
целиком (pytest так и делает), поодиночке функции не самостоятельны.
"""

import concurrent.futures
import os

from conftest import ADMIN_PW
from helpers import bearer, make_tgz, publish_body

ctx: dict = {}


# ============ 1. Суперадмин и логин ============

def test_superadmin_login_and_me(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    ctx["admin"] = bearer(r.json()["access_token"])

    r = client.get("/api/auth/me", headers=ctx["admin"])
    assert r.json().get("is_superadmin") is True

    r = client.post("/api/auth/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_npm_login_issues_token(client):
    r = client.put("/npm/whatever/-/user/org.couchdb.user:admin",
                   json={"name": "admin", "password": ADMIN_PW})
    assert r.status_code == 201 and r.json().get("token"), r.text
    ctx["npm_admin"] = bearer(r.json()["token"])

    r = client.put("/npm/whatever/-/user/org.couchdb.user:admin",
                   json={"name": "admin", "password": "nope"})
    assert r.status_code == 401


# ============ 2. Роли: набор атомарных прав ============

def test_roles_crud(client):
    admin = ctx["admin"]
    r = client.get("/api/roles", headers=admin)
    assert r.json() == [], "по умолчанию ролей нет"

    r = client.post("/api/roles",
                    json={"name": "developer", "permissions": ["CREATE", "READ", "LIST"]},
                    headers=admin)
    assert r.status_code == 201, r.text
    assert set(r.json()["permissions"]) == {"CREATE", "READ", "LIST"}
    ctx["developer_id"] = r.json()["id"]

    r = client.post("/api/roles", json={"name": "developer", "permissions": []}, headers=admin)
    assert r.status_code == 409
    r = client.post("/api/roles", json={"name": "bad", "permissions": ["FLY"]}, headers=admin)
    assert r.status_code == 422

    for name, perms in [("reader", ["READ"]), ("updater", ["UPDATE"]),
                        ("deleter", ["DELETE"]), ("repo-admin", ["ADMIN"])]:
        r = client.post("/api/roles", json={"name": name, "permissions": perms}, headers=admin)
        assert r.status_code == 201, r.text
        ctx[f"{name.replace('-', '_')}_id"] = r.json()["id"]


# ============ 3. Репозитории и пользователи ============

def test_create_repositories_and_users(client, upstream):
    admin = ctx["admin"]
    r = client.post("/api/repositories", json={"name": "npm-hosted", "type": "hosted"},
                    headers=admin)
    assert r.status_code == 201, r.text
    assert r.json()["allow_overwrite"] is False
    ctx["hosted_id"] = r.json()["id"]

    r = client.post("/api/repositories",
                    json={"name": "npm-proxy", "type": "proxy", "upstream_url": upstream.url},
                    headers=admin)
    assert r.status_code == 201, r.text
    ctx["proxy_id"] = r.json()["id"]

    r = client.post("/api/users", json={"login": "dev1", "password": "devpass"}, headers=admin)
    assert r.status_code == 201, r.text
    ctx["dev1_id"] = r.json()["id"]
    r = client.post("/api/auth/login", data={"username": "dev1", "password": "devpass"})
    ctx["dev"] = bearer(r.json()["access_token"])

    r = client.post("/api/users", json={"login": "ci1", "password": "cipass1"}, headers=admin)
    ctx["ci1_id"] = r.json()["id"]
    r = client.post("/api/auth/login", data={"username": "ci1", "password": "cipass1"})
    ctx["ci"] = bearer(r.json()["access_token"])

    r = client.get("/api/users", headers=ctx["dev"])
    assert r.status_code == 403, "не-суперадмин не управляет пользователями"
    r = client.get("/api/repositories", headers=ctx["dev"])
    assert r.status_code == 403


# ============ 4. Назначения ролей и суммирование прав ============

def test_publish_rbac_and_overwrite_policy(client):
    admin, dev, npm_admin = ctx["admin"], ctx["dev"], ctx["npm_admin"]
    hosted_id, dev1_id = ctx["hosted_id"], ctx["dev1_id"]

    ctx["tgz"] = make_tgz("mylib", "1.0.0", {"lodash": "^4.17.21"})
    body = publish_body("mylib", "1.0.0", ctx["tgz"], {"lodash": "^4.17.21"})

    r = client.put("/npm/npm-hosted/mylib", json=body, headers=dev)
    assert r.status_code == 403, "publish без гранта должен быть запрещён (CREATE)"

    r = client.post(f"/api/repositories/{hosted_id}/access",
                    json={"user_id": dev1_id, "role_id": ctx["developer_id"]}, headers=admin)
    assert r.status_code == 201, r.text
    r = client.post(f"/api/repositories/{hosted_id}/access",
                    json={"user_id": dev1_id, "role_id": ctx["developer_id"]}, headers=admin)
    assert r.status_code == 409, "повторный грант"

    r = client.put("/npm/npm-hosted/mylib", json=body, headers=dev)
    assert r.status_code == 201, r.text

    # Перезапись: без allow_overwrite — 409 даже у суперадмина
    r = client.put("/npm/npm-hosted/mylib", json=body, headers=npm_admin)
    assert r.status_code == 409, r.text

    r = client.patch(f"/api/repositories/{hosted_id}", json={"allow_overwrite": True},
                     headers=admin)
    assert r.status_code == 200 and r.json()["allow_overwrite"] is True

    r = client.put("/npm/npm-hosted/mylib", json=body, headers=dev)
    assert r.status_code == 403, "перезапись требует UPDATE"

    r = client.post(f"/api/repositories/{hosted_id}/access",
                    json={"user_id": dev1_id, "role_id": ctx["updater_id"]}, headers=admin)
    assert r.status_code == 201
    r = client.put("/npm/npm-hosted/mylib", json=body, headers=dev)
    assert r.status_code == 201, "права двух ролей суммируются"


def test_read_vs_list_permissions(client):
    admin, dev, ci = ctx["admin"], ctx["dev"], ctx["ci"]

    r = client.post(f"/api/repositories/{ctx['hosted_id']}/access",
                    json={"user_id": ctx["ci1_id"], "role_id": ctx["reader_id"]}, headers=admin)
    assert r.status_code == 201

    r = client.get("/npm/npm-hosted/mylib", headers=ci)
    assert r.status_code == 200, "READ разрешает packument"
    r = client.get("/npm/npm-hosted/-/v1/search?text=mylib", headers=ci)
    assert r.status_code == 403, "поиск требует LIST, одного READ мало"
    r = client.get("/npm/npm-hosted/-/v1/search?text=mylib", headers=dev)
    assert r.status_code == 200 and r.json()["total"] == 1
    r = client.get("/npm/npm-hosted/mylib/-/mylib-1.0.0.tgz", headers=ci)
    assert r.status_code == 200 and r.content == ctx["tgz"], "READ разрешает tarball"


def test_repo_admin_permission(client):
    admin, dev = ctx["admin"], ctx["dev"]
    hosted_id = ctx["hosted_id"]

    r = client.patch(f"/api/repositories/{hosted_id}", json={"allow_overwrite": False},
                     headers=dev)
    assert r.status_code == 403, "настройки репозитория требуют ADMIN"
    r = client.post(f"/api/repositories/{hosted_id}/access",
                    json={"user_id": ctx["dev1_id"], "role_id": ctx["repo_admin_id"]},
                    headers=admin)
    assert r.status_code == 201
    r = client.patch(f"/api/repositories/{hosted_id}", json={"allow_overwrite": False},
                     headers=dev)
    assert r.status_code == 200 and r.json()["allow_overwrite"] is False


# ============ 5. npm-протокол ============

def test_npm_protocol_essentials(client):
    admin, dev, npm_admin = ctx["admin"], ctx["dev"], ctx["npm_admin"]

    r = client.put("/npm/npm-proxy/mylib",
                   json=publish_body("mylib", "1.0.0", ctx["tgz"]), headers=npm_admin)
    assert r.status_code == 400, "publish в proxy запрещён"

    tgz_scoped = make_tgz("@acme/utils", "2.1.0", {"mylib": "^1.0.0"})
    r = client.put("/npm/npm-hosted/@acme%2futils",
                   json=publish_body("@acme/utils", "2.1.0", tgz_scoped, {"mylib": "^1.0.0"}),
                   headers=npm_admin)
    assert r.status_code == 201, r.text
    r = client.get("/npm/npm-hosted/@acme%2futils", headers=admin)
    assert r.status_code == 200 and "2.1.0" in r.json()["versions"]
    r = client.get("/npm/npm-hosted/@acme/utils/-/utils-2.1.0.tgz", headers=admin)
    assert r.status_code == 200 and r.content == tgz_scoped

    r = client.get("/npm/npm-hosted/mylib", headers=dev)
    doc = r.json()
    assert doc["dist-tags"]["latest"] == "1.0.0"
    assert doc["versions"]["1.0.0"]["dependencies"] == {"lodash": "^4.17.21"}
    assert doc["versions"]["1.0.0"]["dist"]["integrity"].startswith("sha512-")
    r = client.get("/npm/npm-hosted/mylib/latest", headers=dev)
    assert r.status_code == 200 and r.json()["version"] == "1.0.0", "dist-tag как версия"
    r = client.get("/npm/npm-hosted/no-such-pkg", headers=admin)
    assert r.status_code == 404

    big_tgz = make_tgz("bigpkg", "1.0.0", {}, payload=os.urandom(10 * 1024 * 1024))
    ctx["big_tgz"] = big_tgz
    r = client.put("/npm/npm-hosted/bigpkg",
                   json=publish_body("bigpkg", "1.0.0", big_tgz), headers=npm_admin)
    assert r.status_code == 201, r.text
    r = client.get("/npm/npm-hosted/bigpkg/-/bigpkg-1.0.0.tgz", headers=admin)
    assert r.status_code == 200 and r.content == big_tgz


def test_metadata_persisted_and_delete_permission(client):
    admin, dev = ctx["admin"], ctx["dev"]
    hosted_id = ctx["hosted_id"]

    r = client.get(f"/api/repositories/{hosted_id}/packages", headers=admin)
    pkgs = {p["name"]: p for p in r.json()}
    assert set(pkgs) == {"mylib", "@acme/utils", "bigpkg"}
    assert pkgs["mylib"]["versions"][0]["dependencies"] == {"lodash": "^4.17.21"}, \
        "зависимости извлечены из tgz в БД"

    bigpkg_pv_id = pkgs["bigpkg"]["versions"][0]["id"]
    r = client.delete(f"/api/package-versions/{bigpkg_pv_id}", headers=dev)
    assert r.status_code == 403, "удаление требует DELETE"
    r = client.post(f"/api/repositories/{hosted_id}/access",
                    json={"user_id": ctx["dev1_id"], "role_id": ctx["deleter_id"]},
                    headers=admin)
    assert r.status_code == 201
    r = client.delete(f"/api/package-versions/{bigpkg_pv_id}", headers=dev)
    assert r.status_code == 204, r.text
    r = client.get(f"/api/repositories/{hosted_id}/packages", headers=admin)
    assert "bigpkg" not in {p["name"] for p in r.json()}, "пустой пакет удалён с версией"
    r = client.get("/npm/npm-hosted/bigpkg/-/bigpkg-1.0.0.tgz", headers=admin)
    assert r.status_code == 404, "удалённый tarball недоступен"


# ============ 6. Карантин (hosted) ============

def test_hosted_quarantine_flow(client):
    admin, dev = ctx["admin"], ctx["dev"]
    hosted_id = ctx["hosted_id"]

    r = client.get("/api/security/versions", headers=dev)
    assert r.status_code == 403, "security API — только суперадмин"

    tgz_110 = make_tgz("mylib", "1.1.0", {})
    r = client.put("/npm/npm-hosted/mylib",
                   json=publish_body("mylib", "1.1.0", tgz_110), headers=dev)
    assert r.status_code == 201, r.text

    r = client.get(f"/api/repositories/{hosted_id}/packages", headers=admin)
    mylib_versions = {v["version"]: v for p in r.json() if p["name"] == "mylib"
                      for v in p["versions"]}
    assert mylib_versions["1.0.0"]["quarantine_status"] == "UNKNOWN", "статус по умолчанию"
    mylib_100_id = mylib_versions["1.0.0"]["id"]

    r = client.post(f"/api/security/versions/{mylib_100_id}/status",
                    json={"status": "QUARANTINED"}, headers=admin)
    assert r.status_code == 200 and r.json()["quarantine_status"] == "QUARANTINED"

    r = client.get("/npm/npm-hosted/mylib/-/mylib-1.0.0.tgz", headers=admin)
    assert r.status_code == 403, "карантин блокирует даже суперадмина"
    r = client.get("/npm/npm-hosted/mylib", headers=dev)
    assert "1.0.0" not in r.json()["versions"] and "1.1.0" in r.json()["versions"], \
        "карантинная версия скрыта из packument"
    assert r.json()["dist-tags"]["latest"] == "1.1.0", "dist-tags пересчитаны"
    r = client.get("/npm/npm-hosted/mylib/-/mylib-1.1.0.tgz", headers=dev)
    assert r.status_code == 200, "остальные версии отдаются"

    r = client.get("/api/security/versions?status_filter=QUARANTINED", headers=admin)
    assert [(x["package_name"], x["version"]) for x in r.json()] == [("mylib", "1.0.0")]

    r = client.post("/api/security/versions/999999/status",
                    json={"status": "CLEAN"}, headers=admin)
    assert r.status_code == 404
    r = client.post(f"/api/security/versions/{mylib_100_id}/status",
                    json={"status": "WHITELISTED"}, headers=admin)
    assert r.status_code == 422, "WHITELISTED — только через правило"

    r = client.post(f"/api/security/versions/{mylib_100_id}/status",
                    json={"status": "CLEAN"}, headers=admin)
    assert r.status_code == 200
    r = client.get("/npm/npm-hosted/mylib/-/mylib-1.0.0.tgz", headers=dev)
    assert r.status_code == 200 and r.content == ctx["tgz"], "CLEAN снова отдаётся"


# ============ 7. Proxy: стриминг, single-flight, карантин, офлайн ============

def test_proxy_requires_grant(client):
    r = client.get("/npm/npm-proxy/left-pad", headers=ctx["dev"])
    assert r.status_code == 403
    r = client.post(f"/api/repositories/{ctx['proxy_id']}/access",
                    json={"user_id": ctx["dev1_id"], "role_id": ctx["reader_id"]},
                    headers=ctx["admin"])
    assert r.status_code == 201


def test_proxy_packument_and_tarball(client, upstream):
    dev = ctx["dev"]
    r = client.get("/npm/npm-proxy/left-pad", headers=dev)
    assert r.status_code == 200, r.text
    t_url = r.json()["versions"]["1.3.0"]["dist"]["tarball"]
    assert "/npm/npm-proxy/left-pad/-/left-pad-1.3.0.tgz" in t_url, \
        "tarball-URL переписан на прокси"

    r = client.get("/npm/npm-proxy/left-pad/-/left-pad-1.3.0.tgz", headers=dev)
    assert r.status_code == 200 and r.content == upstream.left_pad_tgz, "cache miss -> upstream"


def test_proxy_single_flight(client, upstream):
    admin = ctx["admin"]
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(client.get, "/npm/npm-proxy/solo/-/solo-1.0.0.tgz",
                               headers=admin) for _ in range(2)]
        r1, r2 = [f.result() for f in futures]
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.content == upstream.solo_tgz and r2.content == upstream.solo_tgz
    assert upstream.hits.get("/solo/-/solo-1.0.0.tgz", 0) == 1, \
        "одновременные запросы -> одно скачивание с upstream"


def test_proxy_big_tarball_streamed(client, upstream):
    admin = ctx["admin"]
    r = client.get("/npm/npm-proxy/left-pad/-/left-pad-9.9.9.tgz", headers=admin)
    assert r.status_code == 200 and r.content == upstream.big_tgz
    r = client.get(f"/api/repositories/{ctx['proxy_id']}/packages", headers=admin)
    lp_versions = {v["version"]: v for p in r.json() if p["name"] == "left-pad"
                   for v in p["versions"]}
    assert lp_versions["9.9.9"]["size"] == len(upstream.big_tgz)
    assert lp_versions["1.3.0"]["dependencies"] == {"wcwidth": "^1.0.0"}, \
        "зависимости извлечены из проксированного tgz"
    ctx["lp_130_id"] = next(v["id"] for v in lp_versions.values() if v["version"] == "1.3.0")


def test_proxy_quarantine_and_whitelist(client, upstream):
    admin, dev = ctx["admin"], ctx["dev"]
    lp_id = ctx["lp_130_id"]

    r = client.post(f"/api/security/versions/{lp_id}/status",
                    json={"status": "QUARANTINED"}, headers=admin)
    assert r.status_code == 200
    r = client.get("/npm/npm-proxy/left-pad/-/left-pad-1.3.0.tgz", headers=dev)
    assert r.status_code == 403
    r = client.get("/npm/npm-proxy/left-pad", headers=dev)
    assert r.status_code == 404, "все версии upstream-packument в карантине -> 404"

    r = client.post("/api/security/whitelist",
                    json={"package_name": "left-pad", "version": "1.3.0",
                          "reason": "false positive, approved"}, headers=admin)
    assert r.status_code == 201, r.text
    rule_id = r.json()["id"]
    r = client.post("/api/security/whitelist",
                    json={"package_name": "left-pad", "version": "1.3.0", "reason": "dup"},
                    headers=admin)
    assert r.status_code == 409

    r = client.get("/api/security/versions?package=left-pad", headers=admin)
    assert next(x["quarantine_status"] for x in r.json()
                if x["version"] == "1.3.0") == "WHITELISTED"
    r = client.get("/npm/npm-proxy/left-pad/-/left-pad-1.3.0.tgz", headers=dev)
    assert r.status_code == 200 and r.content == upstream.left_pad_tgz
    r = client.post(f"/api/security/versions/{lp_id}/status",
                    json={"status": "QUARANTINED"}, headers=admin)
    assert r.status_code == 400, "whitelisted меняется только удалением правила"

    r = client.delete(f"/api/security/whitelist/{rule_id}", headers=admin)
    assert r.status_code == 204
    r = client.get("/api/security/versions?package=left-pad", headers=admin)
    assert next(x["quarantine_status"] for x in r.json()
                if x["version"] == "1.3.0") == "UNKNOWN"


def test_proxy_offline_fallback(client, upstream):
    admin, dev = ctx["admin"], ctx["dev"]
    upstream.shutdown()

    r = client.get("/npm/npm-proxy/left-pad/-/left-pad-1.3.0.tgz", headers=dev)
    assert r.status_code == 200 and r.content == upstream.left_pad_tgz, \
        "кэш работает при упавшем upstream"
    r = client.get("/npm/npm-proxy/left-pad", headers=dev)
    assert r.status_code == 200 and "1.3.0" in r.json()["versions"], \
        "packument собирается из БД офлайн"
    r = client.get("/npm/npm-proxy/never-cached", headers=admin)
    assert r.status_code == 502, "незакэшированное при упавшем upstream -> 502"

    # Офлайн-фолбэк тоже фильтрует карантин
    r = client.post(f"/api/security/versions/{ctx['lp_130_id']}/status",
                    json={"status": "QUARANTINED"}, headers=admin)
    assert r.status_code == 200
    r = client.get("/npm/npm-proxy/left-pad", headers=dev)
    assert r.status_code == 200
    assert "1.3.0" not in r.json()["versions"] and "9.9.9" in r.json()["versions"]


# ============ 8. Аудит ============

def test_download_audit(client):
    admin, dev = ctx["admin"], ctx["dev"]

    r = client.get("/api/audit/downloads", headers=dev)
    assert r.status_code == 403

    r = client.get("/api/audit/downloads?package=mylib", headers=admin)
    rows = r.json()
    assert any(x["user_login"] == "ci1" and x["package_name"] == "mylib"
               and x["package_version"] == "1.0.0"
               and x["repository_name"] == "npm-hosted" for x in rows), rows[:3]
    assert all(x.get("user_agent") for x in rows), "user-agent фиксируется"

    r = client.get("/api/audit/downloads?package=left-pad&version=1.3.0", headers=admin)
    downloaders = {x["user_login"] for x in r.json()}
    assert "dev1" in downloaders, "«кто успел скачать заражённую версию»"

    before = len(client.get("/api/audit/downloads?package=solo", headers=admin).json())
    r = client.get("/npm/npm-proxy/solo/-/solo-1.0.0.tgz", headers=admin)
    assert r.status_code == 200
    after = len(client.get("/api/audit/downloads?package=solo", headers=admin).json())
    assert after == before + 1, "каждая выдача = новая строка"


def test_operator_audit(client):
    admin = ctx["admin"]
    r = client.get("/api/audit/operations", headers=admin)
    actions = {x["action"] for x in r.json()}
    assert {"user.create", "role.create", "repository.create", "grant.create",
            "repository.update", "version.delete", "quarantine.status_change",
            "whitelist.add", "whitelist.remove"} <= actions, actions

    r = client.get("/api/audit/operations?action=version.delete", headers=admin)
    assert r.json() and r.json()[0]["actor_login"] == "dev1"
    assert "bigpkg@1.0.0" in r.json()[0]["target"]


# ============ 9. Защита суперадмина ============

def test_superadmin_self_protection(client):
    admin = ctx["admin"]
    r = client.patch("/api/users/1", json={"is_active": False}, headers=admin)
    assert r.status_code == 400, "нельзя деактивировать себя"
    r = client.patch("/api/users/1", json={"is_superadmin": False}, headers=admin)
    assert r.status_code == 400, "нельзя снять с себя суперадмина"
    r = client.delete("/api/users/1", headers=admin)
    assert r.status_code == 400, "нельзя удалить себя"

    r = client.post("/api/users",
                    json={"login": "admin2", "password": "second-admin-pw",
                          "is_superadmin": True}, headers=admin)
    assert r.status_code == 201, r.text
    admin2_id = r.json()["id"]
    r = client.post("/api/auth/login", data={"username": "admin2", "password": "second-admin-pw"})
    admin2 = bearer(r.json()["access_token"])

    # bootstrap-сценарий: второй админ деактивирует bootstrap-аккаунт
    r = client.patch("/api/users/1", json={"is_active": False}, headers=admin2)
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", data={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 401, "деактивированный не логинится"
    r = client.get("/api/users", headers=admin)
    assert r.status_code == 401, "старый токен деактивированного отвергается"

    r = client.patch(f"/api/users/{admin2_id}", json={"is_active": False}, headers=admin2)
    assert r.status_code == 400
    r = client.patch(f"/api/users/{admin2_id}", json={"is_superadmin": False}, headers=admin2)
    assert r.status_code == 400, "последний активный суперадмин защищён"

    r = client.patch("/api/users/1", json={"is_active": True}, headers=admin2)
    assert r.status_code == 200 and r.json()["is_active"] is True, \
        "любой действующий суперадмин включает bootstrap обратно"
    # восстановить токен admin для возможных последующих тестов
    r = client.post("/api/auth/login", data={"username": "admin", "password": ADMIN_PW})
    ctx["admin"] = bearer(r.json()["access_token"])


# ============ 10. Аноним ============

def test_anonymous_access(client):
    r = client.get("/npm/npm-hosted/mylib")
    assert r.status_code == 401
    r = client.get("/npm/npm-hosted/-/ping")
    assert r.status_code == 200, "ping публичный"

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

from memora.app import create_app
from memora.store import Store


def test_sms_login_roles_and_authorization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codes = iter(["123456", "654321"])

    async def fake_deliver_sms(*_args: object) -> None:
        return None

    monkeypatch.setattr("memora.app.generate_code", lambda: next(codes))
    monkeypatch.setattr("memora.app.deliver_sms", fake_deliver_sms)
    asyncio.run(_exercise_auth(tmp_path))


def test_personal_resource_isolation_and_project_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codes = iter(["111111", "222222"])

    async def fake_deliver_sms(*_args: object) -> None:
        return None

    monkeypatch.setattr("memora.app.generate_code", lambda: next(codes))
    monkeypatch.setattr("memora.app.deliver_sms", fake_deliver_sms)
    asyncio.run(_exercise_project_access(tmp_path))


def test_first_admin_claims_legacy_unscoped_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_deliver_sms(*_args: object) -> None:
        return None

    monkeypatch.setattr("memora.app.generate_code", lambda: "333333")
    monkeypatch.setattr("memora.app.deliver_sms", fake_deliver_sms)
    asyncio.run(_exercise_legacy_claim(tmp_path))


def test_account_password_login_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_deliver_sms(*_args: object) -> None:
        return None

    monkeypatch.setattr("memora.app.generate_code", lambda: "123456")
    monkeypatch.setattr("memora.app.deliver_sms", fake_deliver_sms)
    asyncio.run(_exercise_password_login(tmp_path))


def test_account_registration_and_optional_phone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_deliver_sms(*_args: object) -> None:
        return None

    monkeypatch.setattr("memora.app.generate_code", lambda: "456789")
    monkeypatch.setattr("memora.app.deliver_sms", fake_deliver_sms)
    asyncio.run(_exercise_account_registration(tmp_path))


def test_legacy_users_table_gains_password_columns(tmp_path: Path) -> None:
    database = tmp_path / "legacy-auth.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'member', status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT
        )"""
    )
    connection.commit()
    connection.close()

    store = Store(database)
    columns = {row["name"] for row in store.db.execute("PRAGMA table_info(users)")}
    assert {"username", "password_hash"}.issubset(columns)
    phone_column = next(row for row in store.db.execute("PRAGMA table_info(users)") if row["name"] == "phone")
    assert phone_column["notnull"] == 0
    assert list(store.db.execute("PRAGMA foreign_key_check")) == []
    store.close()


async def _exercise_account_registration(tmp_path: Path) -> None:
    store = Store(":memory:")
    app = create_app(data_dir=tmp_path, store=store, auth_enabled=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unrestricted_username = "项目 负责人@甲" * 20
        unrestricted_password = "密碼 🔐 !@#$%^&*()" * 20
        registered = await client.post(
            "/api/auth/register",
            json={"username": unrestricted_username, "password": unrestricted_password},
        )
        assert registered.status_code == 201
        assert registered.json()["user"]["username"] == unrestricted_username
        assert registered.json()["user"]["phone"] is None
        assert registered.json()["user"]["role"] == "admin"

        duplicate = await client.post(
            "/api/auth/register",
            json={"username": unrestricted_username, "password": "另一个 密码 <>?{}[]"},
        )
        assert duplicate.status_code == 409

        sent = await client.post("/api/auth/sms/send", json={"phone": "13800138000"})
        assert sent.status_code == 200
        bound = await client.put(
            "/api/account/phone",
            json={"phone": "13800138000", "code": "456789"},
        )
        assert bound.status_code == 200
        assert bound.json()["phone"] == "13800138000"

        await client.post("/api/auth/logout")
        password_login = await client.post(
            "/api/auth/password/login",
            json={"account": unrestricted_username, "password": unrestricted_password},
        )
        assert password_login.status_code == 200
    store.close()


async def _exercise_password_login(tmp_path: Path) -> None:
    store = Store(":memory:")
    app = create_app(data_dir=tmp_path, store=store, auth_enabled=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/auth/sms/send", json={"phone": "13800138000"})
        sms_login = await client.post(
            "/api/auth/sms/login", json={"phone": "13800138000", "code": "123456"}
        )
        assert sms_login.status_code == 200
        assert sms_login.json()["user"]["hasPassword"] is False

        configured = await client.put(
            "/api/account/credentials",
            json={"username": "Admin.User", "password": "correct horse battery staple"},
        )
        assert configured.status_code == 200
        assert configured.json()["username"] == "admin.user"
        assert configured.json()["hasPassword"] is True
        stored = store.db.execute(
            "SELECT username,password_hash FROM users WHERE phone='13800138000'"
        ).fetchone()
        assert stored is not None
        assert stored["username"] == "admin.user"
        assert stored["password_hash"].startswith("scrypt$")
        assert "correct horse" not in stored["password_hash"]

        assert (await client.post("/api/auth/logout")).status_code == 204
        wrong = await client.post(
            "/api/auth/password/login",
            json={"account": "admin.user", "password": "wrong-password"},
        )
        assert wrong.status_code == 401
        logged_in = await client.post(
            "/api/auth/password/login",
            json={"account": "ADMIN.USER", "password": "correct horse battery staple"},
        )
        assert logged_in.status_code == 200
        assert logged_in.json()["user"]["username"] == "admin.user"

        missing_current = await client.put(
            "/api/account/credentials",
            json={"username": "admin.user", "password": "a different secure password"},
        )
        assert missing_current.status_code == 401
        changed = await client.put(
            "/api/account/credentials",
            json={
                "username": "admin.user",
                "currentPassword": "correct horse battery staple",
                "password": "a different secure password",
            },
        )
        assert changed.status_code == 200
        await client.post("/api/auth/logout")
        old_password = await client.post(
            "/api/auth/password/login",
            json={"account": "13800138000", "password": "correct horse battery staple"},
        )
        assert old_password.status_code == 401
        new_password = await client.post(
            "/api/auth/password/login",
            json={"account": "13800138000", "password": "a different secure password"},
        )
        assert new_password.status_code == 200
    store.close()


async def _exercise_auth(tmp_path: Path) -> None:
    store = Store(":memory:")
    app = create_app(data_dir=tmp_path, store=store, auth_enabled=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthenticated = await client.get("/api/projects")
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["errorDetail"]["code"] == "authentication_required"

        sent = await client.post("/api/auth/sms/send", json={"phone": "138 0013 8000"})
        assert sent.status_code == 200
        assert "debugCode" not in sent.json()

        bad_login = await client.post("/api/auth/sms/login", json={"phone": "13800138000", "code": "000000"})
        assert bad_login.status_code == 401

        first_login = await client.post(
            "/api/auth/sms/login", json={"phone": "13800138000", "code": "123456"}
        )
        assert first_login.status_code == 200
        first = first_login.json()
        assert first["user"]["role"] == "admin"
        assert first["isNewUser"] is True
        admin_token = first["token"]
        assert "memora_session" in first_login.cookies
        stored_session = store.db.execute("SELECT token_hash FROM auth_sessions").fetchone()
        assert stored_session is not None
        assert stored_session["token_hash"] != admin_token

        reused = await client.post("/api/auth/sms/login", json={"phone": "13800138000", "code": "123456"})
        assert reused.status_code == 401

        last_admin = await client.patch(
            f"/api/admin/users/{first['user']['id']}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "member"},
        )
        assert last_admin.status_code == 409

        await client.post("/api/auth/sms/send", json={"phone": "13900139000"})
        second_login = await client.post(
            "/api/auth/sms/login", json={"phone": "13900139000", "code": "654321"}
        )
        assert second_login.status_code == 200
        second = second_login.json()
        assert second["user"]["role"] == "member"

        member_forbidden = await client.get("/api/admin/users")
        assert member_forbidden.status_code == 403
        member_allowed = await client.get("/api/projects")
        assert member_allowed.status_code == 200

        promoted = await client.patch(
            f"/api/admin/users/{second['user']['id']}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "admin"},
        )
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "admin"

        users = await client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
        assert users.status_code == 200
        assert [user["role"] for user in users.json()] == ["admin", "admin"]

        logged_out = await client.post("/api/auth/logout")
        assert logged_out.status_code == 204
        assert (await client.get("/api/projects")).status_code == 401
    store.close()


async def _exercise_project_access(tmp_path: Path) -> None:
    store = Store(":memory:")
    app = create_app(data_dir=tmp_path, store=store, auth_enabled=True)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as owner,
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as member,
    ):
        await owner.post("/api/auth/sms/send", json={"phone": "13800138000"})
        owner_login = (
            await owner.post("/api/auth/sms/login", json={"phone": "13800138000", "code": "111111"})
        ).json()
        assert "defaultWorkspaceId" not in owner_login
        project = (await owner.post("/api/projects", json={"name": "私有研发项目"})).json()
        private_conversation = (await owner.post("/api/conversations", json={})).json()
        owner_memory = await owner.post(
            "/api/memories",
            json={"type": "fact", "subject": "私有事实", "content": "仅所有者可见"},
        )
        assert owner_memory.status_code == 201

        await member.post("/api/auth/sms/send", json={"phone": "13900139000"})
        member_login = (
            await member.post("/api/auth/sms/login", json={"phone": "13900139000", "code": "222222"})
        ).json()
        assert "defaultWorkspaceId" not in member_login
        own_project = (await member.post("/api/projects", json={"name": "成员自己的项目"})).json()
        assert own_project["created_by"] == member_login["user"]["id"]
        assert (await member.delete(f"/api/projects/{own_project['id']}")).status_code == 204
        assert (await member.get("/api/projects")).json() == []
        assert (await member.get("/api/conversations")).json() == []
        assert (await member.get("/api/memories?scope=ordinary")).json() == []
        assert (await member.get(f"/api/projects/{project['id']}")).status_code == 403

        added = await owner.post(
            f"/api/projects/{project['id']}/members",
            json={"phone": "13900139000", "role": "viewer"},
        )
        assert added.status_code == 201
        assert added.json()["role"] == "viewer"
        member_memory = await member.post(
            "/api/memories",
            json={"type": "fact", "subject": "私有事实", "content": "仅成员自己可见"},
        )
        assert member_memory.status_code == 201
        owner_versions = await owner.get(f"/api/memories/{owner_memory.json()['id']}/versions")
        assert [item["id"] for item in owner_versions.json()] == [owner_memory.json()["id"]]
        assert (
            await owner.get(
                f"/api/memories/{member_memory.json()['id']}/versions",
            )
        ).status_code == 403
        shared_projects = (await member.get("/api/projects")).json()
        assert [(item["id"], item["access_role"]) for item in shared_projects] == [(project["id"], "viewer")]
        assert (await member.get("/api/workspaces")).status_code == 404
        assert (
            await member.get("/api/integrations/tencent-meeting/records")
        ).status_code == 403
        assert (
            await member.post(
                f"/api/projects/{project['id']}/conversations",
                json={},
            )
        ).status_code == 403
        assert (
            await member.get(f"/api/conversations/{private_conversation['id']}")
        ).status_code == 403

        promoted = await owner.post(
            f"/api/projects/{project['id']}/members",
            json={"phone": "13900139000", "role": "editor"},
        )
        assert promoted.status_code == 201
        assert promoted.json()["role"] == "editor"
        created = await member.post(f"/api/projects/{project['id']}/conversations", json={})
        assert created.status_code == 201
        assert created.json()["project_id"] == project["id"]
    store.close()


async def _exercise_legacy_claim(tmp_path: Path) -> None:
    store = Store(":memory:")
    legacy_project = store.create_project("历史项目")
    legacy_conversation = store.create_conversation("历史对话")
    legacy_memory = store.add_memory(
        {
            "type": "fact",
            "subject": "历史事实",
            "content": "升级前的内容",
            "source_type": "manual",
            "source_id": None,
        }
    )
    app = create_app(data_dir=tmp_path, store=store, auth_enabled=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/auth/sms/send", json={"phone": "13700137000"})
        login = await client.post("/api/auth/sms/login", json={"phone": "13700137000", "code": "333333"})
        assert "defaultWorkspaceId" not in login.json()
        assert [item["id"] for item in (await client.get("/api/projects")).json()] == [legacy_project["id"]]
        assert [item["id"] for item in (await client.get("/api/conversations")).json()] == [
            legacy_conversation["id"]
        ]
        assert [item["id"] for item in (await client.get("/api/memories?scope=ordinary")).json()] == [
            legacy_memory["id"]
        ]
        migrated_project = store.get_project(legacy_project["id"])
        migrated_conversation = store.get_conversation(legacy_conversation["id"])
        migrated_memory = store.get_memory(legacy_memory["id"])
        user_id = login.json()["user"]["id"]
        assert migrated_project and migrated_project["created_by"] == user_id
        assert migrated_conversation and migrated_conversation["created_by"] == user_id
        assert migrated_memory and migrated_memory["created_by"] == user_id
        assert store.project_role(legacy_project["id"], user_id) == "owner"
    store.close()

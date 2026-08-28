from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

from memora.app import create_app
from memora.services.errors import AgentError
from memora.services.provider import (
    ProviderError,
    provider_health,
    reset_circuits,
    retry_async,
)
from memora.services.tasks import TaskManager
from memora.store import Store


def test_reliability_schema_migrates_execution_columns(tmp_path: Path) -> None:
    database = tmp_path / "legacy-reliability.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY,title TEXT NOT NULL DEFAULT 'legacy')"
    )
    connection.execute(
        """CREATE TABLE messages (
        id INTEGER PRIMARY KEY,conversation_id INTEGER,role TEXT,content TEXT,
        sources_json TEXT DEFAULT '[]',artifact_id INTEGER)"""
    )
    connection.execute(
        """CREATE TABLE artifacts (
        id INTEGER PRIMARY KEY,conversation_id INTEGER,kind TEXT,name TEXT,file_path TEXT,
        metadata_json TEXT DEFAULT '{}')"""
    )
    connection.commit()
    connection.close()
    store = Store(database)
    assert "execution_id" in {row["name"] for row in store._all("PRAGMA table_info(messages)")}
    assert "execution_id" in {row["name"] for row in store._all("PRAGMA table_info(artifacts)")}
    assert {"resolved_at", "resolution"} <= {
        row["name"] for row in store._all("PRAGMA table_info(email_deliveries)")
    }
    store.close()


def test_provider_retry_and_circuit_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def no_wait(_: float) -> None:
        return None

    async def eventually_succeeds() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderError(
                "temporary failure",
                provider="test-provider",
                code="temporary",
                retryable=True,
            )
        return "ok"

    monkeypatch.setattr("memora.services.provider.asyncio.sleep", no_wait)
    reset_circuits()
    assert (
        asyncio.run(
            retry_async(
                eventually_succeeds,
                provider="test-provider",
                operation_name="generate",
                max_attempts=3,
            )
        )
        == "ok"
    )
    assert attempts == 3

    async def always_fails() -> str:
        raise ProviderError(
            "down",
            provider="broken-provider",
            code="connection_failed",
            retryable=True,
        )

    for _ in range(5):
        with pytest.raises(ProviderError):
            asyncio.run(
                retry_async(
                    always_fails,
                    provider="broken-provider",
                    operation_name="generate",
                    max_attempts=1,
                )
            )
    state = next(item for item in provider_health() if item["provider"] == "broken-provider")
    assert state["status"] == "circuit_open"
    with pytest.raises(ProviderError, match="熔断"):
        asyncio.run(
            retry_async(
                always_fails,
                provider="broken-provider",
                operation_name="generate",
                max_attempts=1,
            )
        )
    reset_circuits()


def test_persistent_task_and_email_idempotency(tmp_path: Path) -> None:
    store = Store(tmp_path / "reliability.db")
    task, created = store.enqueue_task(
        task_id="task-1",
        kind="message",
        payload={"content": "hello"},
        idempotency_key="same-request",
        trace_id="trace-1",
    )
    duplicate, duplicate_created = store.enqueue_task(
        task_id="task-2",
        kind="message",
        payload={"content": "ignored"},
        idempotency_key="same-request",
        trace_id="trace-2",
    )
    assert created is True
    assert duplicate_created is False
    assert duplicate["id"] == task["id"] == "task-1"
    assert store.claim_task("task-1")["status"] == "running"
    failed, retrying = store.fail_task("task-1", {"code": "invalid"}, 0, retryable=False)
    assert retrying is False
    assert failed["status"] == "failed"

    store.enqueue_task(
        task_id="task-delayed",
        kind="message",
        payload={},
        idempotency_key="delayed-request",
        trace_id="trace-delayed",
    )
    assert store.claim_task("task-delayed")["status"] == "running"
    _, retrying = store.fail_task("task-delayed", {"code": "temporary"}, 60)
    assert retrying is True
    assert "task-delayed" in {item["id"] for item in store.recover_tasks()}

    delivery, claimed = store.claim_email_delivery(
        delivery_id="delivery-1",
        idempotency_key="email-request",
        source_type="artifact",
        source_id=3,
        provider="smtp",
        recipient="user@example.com",
        subject="subject",
        body_hash="body-hash",
    )
    assert claimed is True
    store.complete_email_delivery(delivery["id"], {"messageId": "message-1"})
    duplicate_delivery, claimed_again = store.claim_email_delivery(
        delivery_id="delivery-2",
        idempotency_key="email-request",
        source_type="artifact",
        source_id=3,
        provider="smtp",
        recipient="user@example.com",
        subject="subject",
        body_hash="body-hash",
    )
    assert claimed_again is False
    assert duplicate_delivery["id"] == "delivery-1"
    assert duplicate_delivery["status"] == "sent"
    failed_delivery, _ = store.claim_email_delivery(
        delivery_id="delivery-failed",
        idempotency_key="email-failed-request",
        source_type="todo",
        source_id=8,
        provider="smtp",
        recipient="user@example.com",
        subject="failed subject",
        body_hash="failed-body-hash",
    )
    store.fail_email_delivery(failed_delivery["id"], {"code": "connection_failed", "message": "timeout"})
    failures = store.list_email_deliveries(status="failed", active_only=True)
    assert [item["id"] for item in failures] == ["delivery-failed"]
    resolved = store.resolve_email_delivery("delivery-failed")
    assert resolved["resolution"] == "acknowledged"
    assert store.list_email_deliveries(status="failed", active_only=True) == []
    store.close()


def test_retry_exhaustion_enters_dead_letter_and_compensates(tmp_path: Path) -> None:
    asyncio.run(_exercise_dead_letter(tmp_path))


async def _exercise_dead_letter(tmp_path: Path) -> None:
    store = Store(tmp_path / "dead-letter.db")
    manager = TaskManager(store)
    compensated = 0

    async def fail(_: dict, __: dict) -> dict:
        raise AgentError(
            "provider unavailable",
            code="provider_unavailable",
            category="provider",
            status_code=503,
            retryable=True,
            stage="execution",
        )

    async def compensate(_: dict, __: dict) -> dict:
        nonlocal compensated
        compensated += 1
        return {"removed": True}

    manager.register("failing", fail)
    manager.register_compensator("failing", compensate)
    store.enqueue_task(
        task_id="dead-task",
        kind="failing",
        payload={},
        idempotency_key="dead-request",
        trace_id="dead-trace",
        max_attempts=1,
    )
    store.create_trace("dead-trace", task_id="dead-task")
    await manager.run("dead-task")
    task = store.get_task("dead-task")
    dead_letter = store.get_dead_letter("dead-task")
    assert task["status"] == "dead_letter"
    assert dead_letter["compensation_status"] == "completed"
    assert dead_letter["compensation_result"] == {"removed": True}
    assert compensated == 1
    assert store.get_trace("dead-trace")["status"] == "dead_letter"
    app = create_app(data_dir=tmp_path, store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        task_response = await client.get("/api/tasks?status=dead_letter")
        dead_response = await client.get("/api/dead-letters")
        assert task_response.status_code == dead_response.status_code == 200
        assert task_response.json()[0]["id"] == "dead-task"
        assert dead_response.json()[0]["compensationStatus"] == "completed"
    await app.state.task_manager.shutdown()
    retried = store.retry_task("dead-task")
    assert retried["status"] == "queued"
    assert store.get_dead_letter("dead-task")["resolution"] == "retried"
    await manager.shutdown()
    store.close()


def test_execution_rollback_removes_only_matching_records(tmp_path: Path) -> None:
    store = Store(tmp_path / "compensation.db")
    conversation = store.create_conversation("rollback")
    matching = store.add_message(conversation["id"], "user", "partial", execution_id="execution-1")
    retained = store.add_message(conversation["id"], "user", "keep")
    artifact_path = tmp_path / "partial.pptx"
    artifact = store.add_artifact(
        conversation_id=conversation["id"],
        kind="pptx",
        name="partial.pptx",
        file_path=str(artifact_path),
        metadata={},
        execution_id="execution-1",
    )
    result = store.rollback_execution("execution-1")
    assert result["messageIds"] == [matching["id"]]
    assert result["artifactIds"] == [artifact["id"]]
    assert [item["id"] for item in store.list_messages(conversation["id"])] == [retained["id"]]
    assert store.get_artifact(artifact["id"]) is None
    store.close()


def test_message_task_is_idempotent_and_traceable(tmp_path: Path) -> None:
    asyncio.run(_exercise_message_task(tmp_path))


def test_email_api_does_not_send_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = 0

    async def fake_inbox(inbox_id: str = "") -> str:
        return inbox_id or "test@agentmail.to"

    async def fake_send(inbox_id: str, to: str, subject: str, body: str) -> dict[str, object]:
        nonlocal sent
        sent += 1
        return {
            "provider": "agentmail",
            "messageId": "email-1",
            "accepted": [to],
            "rejected": [],
            "from": inbox_id,
        }

    monkeypatch.setattr("memora.app.agentmail_configured", lambda: True)
    monkeypatch.setattr("memora.app.ensure_agentmail_inbox", fake_inbox)
    monkeypatch.setattr("memora.app.send_agentmail_message", fake_send)
    asyncio.run(_exercise_email_idempotency(tmp_path, sent_count=lambda: sent))


async def _exercise_email_idempotency(tmp_path: Path, sent_count) -> None:
    store = Store(tmp_path / "email-api.db")
    project = store.create_project("Email project")
    document = store.add_document(
        name="meeting.txt",
        mime_type="text/plain",
        kind="meeting",
        text="meeting source",
        metadata={},
    )
    meeting = store.create_meeting(
        document["id"],
        {
            "title": "Weekly meeting",
            "summary": "",
            "participants": [],
            "dates": [],
            "locations": [],
            "topics": [],
            "risks": [],
            "decisions": [],
        },
        project["id"],
    )
    todo = store.add_todo(meeting["id"], {"title": "Follow up"})
    app = create_app(data_dir=tmp_path, store=store)
    transport = httpx.ASGITransport(app=app)
    payload = {
        "provider": "agentmail",
        "to": "recipient@example.com",
        "subject": "Follow up",
        "body": "Please follow up",
        "idempotencyKey": "email-once",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(f"/api/todos/{todo['id']}/send-email", json=payload)
        second = await client.post(f"/api/todos/{todo['id']}/send-email", json=payload)
        assert first.status_code == second.status_code == 200
        assert first.json()["idempotent"] is False
        assert second.json()["idempotent"] is True
        assert second.json()["deliveryId"] == first.json()["deliveryId"]
        assert sent_count() == 1
    await app.state.task_manager.shutdown()
    store.close()


async def _exercise_message_task(tmp_path: Path) -> None:
    store = Store(tmp_path / "task-api.db")
    app = create_app(data_dir=tmp_path, store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        conversation = (await client.post("/api/conversations", json={"title": "可靠性测试"})).json()
        payload = {"content": "请帮我整理项目计划", "idempotencyKey": "message-request-1"}
        first = await client.post(f"/api/conversations/{conversation['id']}/message-tasks", json=payload)
        second = await client.post(f"/api/conversations/{conversation['id']}/message-tasks", json=payload)
        assert first.status_code == second.status_code == 202
        first_task = first.json()
        assert second.json()["id"] == first_task["id"]
        assert second.json()["idempotent"] is True

        task = first_task
        for _ in range(100):
            if task["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.01)
            task = (await client.get(task["pollUrl"])).json()
        assert task["status"] == "completed", task
        assert task["result"]["message"]["role"] == "assistant"

        conversation_detail = (await client.get(f"/api/conversations/{conversation['id']}")).json()
        assert [message["role"] for message in conversation_detail["messages"]] == [
            "user",
            "assistant",
        ]
        trace = (await client.get(f"/api/traces/{task['traceId']}")).json()
        assert trace["status"] == "completed"
        assert {event["stage"] for event in trace["events"]} >= {
            "task",
            "routing",
            "context",
            "workflow",
            "persistence",
        }
    await app.state.task_manager.shutdown()
    store.close()

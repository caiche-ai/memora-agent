from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..store import Store
from .errors import AgentError
from .observability import trace_context
from .provider import ProviderError

TaskHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]
TaskCompensator = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


class TaskManager:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.handlers: dict[str, TaskHandler] = {}
        self.compensators: dict[str, TaskCompensator] = {}
        self.runners: set[asyncio.Task[None]] = set()

    def register(self, kind: str, handler: TaskHandler) -> None:
        self.handlers[kind] = handler

    def register_compensator(self, kind: str, compensator: TaskCompensator) -> None:
        self.compensators[kind] = compensator

    async def compensate(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        dead_letter = self.store.get_dead_letter(task_id)
        if not task or not dead_letter:
            raise ValueError("Dead-letter task does not exist")
        compensator = self.compensators.get(str(task["kind"]))
        if not compensator:
            result = {"message": "No compensation is required for this task kind"}
            self.store.update_dead_letter_compensation(task_id, "skipped", result)
            self.store.add_trace_event(
                str(task.get("trace_id") or ""),
                stage="compensation",
                event="rollback",
                status="skipped",
                metadata=result,
            )
            return result
        try:
            result = await compensator(task.get("payload") or {}, task)
        except Exception as error:
            result = {"message": str(error), "exceptionType": type(error).__name__}
            self.store.update_dead_letter_compensation(task_id, "failed", result)
            self.store.add_trace_event(
                str(task.get("trace_id") or ""),
                stage="compensation",
                event="rollback",
                status="failed",
                metadata=result,
            )
            return result
        self.store.update_dead_letter_compensation(task_id, "completed", result)
        self.store.add_trace_event(
            str(task.get("trace_id") or ""),
            stage="compensation",
            event="rollback",
            status="completed",
            metadata=result,
        )
        return result

    async def _finish_failure(
        self,
        task: dict[str, Any],
        payload: dict[str, Any],
        retrying: bool,
    ) -> None:
        task_id = str(task["id"])
        trace_id = str(task.get("trace_id") or "")
        if retrying:
            delay = min(30, 2 ** max(0, int(task["attempts"]) - 1))
            self.schedule(task_id, delay)
            return
        updated = self.store.get_task(task_id) or task
        if updated.get("status") == "dead_letter":
            await self.compensate(task_id)
            self.store.finish_trace(trace_id, "dead_letter", payload)
        else:
            self.store.finish_trace(trace_id, "failed", payload)

    def enqueue(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        max_attempts: int = 3,
    ) -> tuple[dict[str, Any], bool]:
        task_id = uuid4().hex
        trace_id = uuid4().hex
        task, created = self.store.enqueue_task(
            task_id=task_id,
            kind=kind,
            payload=payload,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            max_attempts=max_attempts,
        )
        if created:
            self.store.create_trace(
                trace_id,
                task_id=task_id,
                metadata={"taskKind": kind, "idempotencyKey": idempotency_key},
            )
            self.schedule(task_id)
        return task, created

    def schedule(self, task_id: str, delay: float = 0) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if delay > 0:
            loop.call_later(delay, self.schedule, task_id)
            return
        runner = loop.create_task(self.run(task_id))
        self.runners.add(runner)
        runner.add_done_callback(self.runners.discard)

    async def run(self, task_id: str) -> None:
        task = self.store.claim_task(task_id)
        if not task:
            return
        trace_id = str(task.get("trace_id") or "")
        handler = self.handlers.get(str(task["kind"]))
        if not handler:
            error = {
                "code": "unknown_task_kind",
                "message": f"没有任务处理器：{task['kind']}",
                "retryable": False,
            }
            self.store.fail_task(task_id, error, 0, retryable=False)
            self.store.finish_trace(trace_id, "failed", error)
            return
        self.store.add_trace_event(
            trace_id,
            stage="task",
            event="execute",
            status="running",
            attempt=task["attempts"],
            metadata={"kind": task["kind"]},
        )
        try:
            with trace_context(trace_id, self.store.add_trace_event):
                result = await handler(task.get("payload") or {}, task)
            self.store.complete_task(task_id, result)
            self.store.add_trace_event(
                trace_id,
                stage="task",
                event="execute",
                status="completed",
                attempt=task["attempts"],
            )
            self.store.finish_trace(trace_id, "completed")
        except (AgentError, ProviderError) as error:
            payload = error.payload()
            retryable = bool(payload.get("retryable"))
            delay = min(30, 2 ** max(0, int(task["attempts"]) - 1)) if retryable else 0
            _, retrying = self.store.fail_task(task_id, payload, delay, retryable=retryable)
            self.store.add_trace_event(
                trace_id,
                stage="task",
                event="execute",
                status="retrying" if retrying else "failed",
                attempt=task["attempts"],
                metadata={"errorCode": payload.get("code")},
            )
            await self._finish_failure(task, payload, retrying)
        except Exception as error:
            payload = {
                "code": "task_execution_failed",
                "message": str(error) or "任务执行失败",
                "retryable": True,
                "exceptionType": type(error).__name__,
            }
            _, retrying = self.store.fail_task(
                task_id,
                payload,
                min(30, 2 ** max(0, int(task["attempts"]) - 1)),
            )
            self.store.add_trace_event(
                trace_id,
                stage="task",
                event="execute",
                status="retrying" if retrying else "failed",
                attempt=task["attempts"],
                metadata={"errorCode": payload["code"]},
            )
            await self._finish_failure(task, payload, retrying)

    def recover(self) -> int:
        tasks = self.store.recover_tasks()
        for task in tasks:
            delay = 0.0
            try:
                available_at = datetime.fromisoformat(str(task["available_at"]))
                if available_at.tzinfo is None:
                    available_at = available_at.replace(tzinfo=UTC)
                delay = max(0.0, (available_at - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                pass
            self.schedule(task["id"], delay)
        return len(tasks)

    async def shutdown(self) -> None:
        pending = list(self.runners)
        for runner in pending:
            runner.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..config import config
from .observability import emit_trace_event


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        code: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.retryable = retryable
        self.status_code = status_code

    def payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "statusCode": self.status_code,
        }


@dataclass
class CircuitState:
    failures: int = 0
    open_until: datetime | None = None


_circuits: dict[str, CircuitState] = {}


def _state(provider: str) -> CircuitState:
    return _circuits.setdefault(provider, CircuitState())


def reset_circuits() -> None:
    _circuits.clear()


def provider_health() -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    return [
        {
            "provider": provider,
            "status": "circuit_open" if state.open_until and state.open_until > now else "available",
            "failures": state.failures,
            "openUntil": state.open_until.isoformat() if state.open_until else None,
        }
        for provider, state in sorted(_circuits.items())
    ]


def _retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    provider: str,
    operation_name: str,
    max_attempts: int | None = None,
    retry_exceptions: tuple[type[BaseException], ...] = (OSError,),
) -> T:
    attempts = max(1, max_attempts or config.provider_max_attempts)
    circuit = _state(provider)
    now = datetime.now(UTC)
    if circuit.open_until and circuit.open_until > now:
        raise ProviderError(
            f"{provider} 服务暂时熔断，请稍后重试",
            provider=provider,
            code="circuit_open",
            retryable=True,
        )
    circuit.open_until = None
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        emit_trace_event(
            stage="provider",
            event=operation_name,
            status="running",
            attempt=attempt,
            metadata={"provider": provider},
        )
        try:
            result = await operation()
            circuit.failures = 0
            emit_trace_event(
                stage="provider",
                event=operation_name,
                status="completed",
                attempt=attempt,
                duration_ms=int((time.perf_counter() - started) * 1000),
                metadata={"provider": provider},
            )
            return result
        except ProviderError as error:
            last_error = error
            retryable = error.retryable
        except retry_exceptions as error:
            last_error = error
            retryable = True
        emit_trace_event(
            stage="provider",
            event=operation_name,
            status="retrying" if retryable and attempt < attempts else "failed",
            attempt=attempt,
            duration_ms=int((time.perf_counter() - started) * 1000),
            metadata={"provider": provider, "errorType": type(last_error).__name__},
        )
        if not retryable or attempt >= attempts:
            break
        await asyncio.sleep(config.provider_backoff_seconds * (2 ** (attempt - 1)))
    circuit.failures += 1
    if circuit.failures >= config.provider_circuit_threshold:
        circuit.open_until = datetime.now(UTC) + timedelta(seconds=config.provider_circuit_seconds)
    if isinstance(last_error, ProviderError):
        raise last_error
    raise ProviderError(
        f"{provider} 连接失败：{last_error}",
        provider=provider,
        code="connection_failed",
        retryable=True,
    ) from last_error


async def request_json(
    *,
    provider: str,
    operation_name: str,
    method: str,
    url: str,
    timeout: float,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async def request() -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    params=params,
                    files=files,
                )
        except httpx.HTTPError as error:
            raise ProviderError(
                f"{provider} 连接失败：{error}",
                provider=provider,
                code="connection_failed",
                retryable=True,
            ) from error
        if response.is_error:
            raise ProviderError(
                f"{provider} 请求失败 ({response.status_code}): {response.text[:300]}",
                provider=provider,
                code="http_error",
                retryable=_retryable_status(response.status_code),
                status_code=response.status_code,
            )
        try:
            value = response.json()
        except ValueError as error:
            raise ProviderError(
                f"{provider} 返回了无效 JSON",
                provider=provider,
                code="invalid_response",
                retryable=False,
                status_code=response.status_code,
            ) from error
        if not isinstance(value, dict):
            raise ProviderError(
                f"{provider} 返回格式无效",
                provider=provider,
                code="invalid_response",
                retryable=False,
            )
        return value

    return await retry_async(
        request,
        provider=provider,
        operation_name=operation_name,
        retry_exceptions=(httpx.HTTPError, OSError),
    )

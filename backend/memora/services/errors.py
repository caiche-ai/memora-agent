from __future__ import annotations

from typing import Any, Literal

ErrorCategory = Literal["validation", "routing", "context", "provider", "persistence", "internal"]


class AgentError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        category: ErrorCategory,
        status_code: int = 400,
        retryable: bool = False,
        stage: str = "request",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.stage = stage
        self.details = details or {}

    def payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "retryable": self.retryable,
            "stage": self.stage,
            "details": self.details,
        }

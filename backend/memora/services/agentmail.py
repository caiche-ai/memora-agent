from __future__ import annotations

import html
from typing import Any
from urllib.parse import quote

from ..config import AgentMailConfig, config
from .provider import ProviderError, request_json


def agentmail_configured(settings: AgentMailConfig | None = None) -> bool:
    return bool((settings or config.agentmail).api_key)


def _headers(settings: AgentMailConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"}


def _error_detail(error: Exception) -> str:
    return str(error)


async def ensure_agentmail_inbox(inbox_id: str = "", settings: AgentMailConfig | None = None) -> str:
    current = settings or config.agentmail
    selected = inbox_id or current.inbox_id
    if selected:
        return selected
    if not agentmail_configured(current):
        raise RuntimeError("AgentMail 尚未配置")
    try:
        data = await request_json(
            provider="agentmail",
            operation_name="create_inbox",
            method="POST",
            url=f"{current.base_url}/inboxes",
            timeout=30,
            headers=_headers(current),
            json_body={"client_id": "memora-system-mailer-v1", "display_name": config.app_name},
        )
        created = str(data.get("inbox_id") or data.get("email") or "").strip()
        if not created:
            raise RuntimeError("AgentMail 创建邮箱后未返回 inbox_id")
        return created
    except (ProviderError, ValueError, KeyError) as error:
        raise RuntimeError(f"AgentMail 邮箱初始化失败：{_error_detail(error)}") from error


async def send_agentmail_message(
    inbox_id: str,
    to: str,
    subject: str,
    body: str,
    settings: AgentMailConfig | None = None,
) -> dict[str, Any]:
    current = settings or config.agentmail
    if not agentmail_configured(current):
        raise RuntimeError("AgentMail 尚未配置")
    safe_inbox = quote(inbox_id, safe="@._+-")
    html_body = "<p>" + "</p><p>".join(html.escape(part) for part in body.split("\n\n")) + "</p>"
    recipients = [item.strip() for item in to.split(",") if item.strip()]
    try:
        data = await request_json(
            provider="agentmail",
            operation_name="send_email",
            method="POST",
            url=f"{current.base_url}/inboxes/{safe_inbox}/messages/send",
            timeout=30,
            headers=_headers(current),
            json_body={"to": recipients, "subject": subject, "text": body, "html": html_body},
        )
        return {
            "provider": "agentmail",
            "messageId": str(data.get("message_id") or ""),
            "threadId": str(data.get("thread_id") or ""),
            "accepted": recipients,
            "rejected": [],
            "from": inbox_id,
        }
    except (ProviderError, ValueError, KeyError) as error:
        raise RuntimeError(f"AgentMail 发送失败：{_error_detail(error)}") from error

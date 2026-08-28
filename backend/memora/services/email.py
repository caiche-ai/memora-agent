from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from ..config import SmtpConfig, config
from .provider import ProviderError, retry_async


def create_todo_email(todo: dict[str, Any]) -> dict[str, str]:
    levels = {"high": "高", "medium": "中", "low": "低"}
    lines = [
        "您好，",
        "",
        "会议中识别到以下待办，请及时确认并跟进：",
        "",
        f"待办：{todo['title']}",
        f"说明：{todo['description']}" if todo.get("description") else "",
        f"负责人：{todo['owner']}" if todo.get("owner") else "负责人：待确认",
        f"截止时间：{todo['due_date']}" if todo.get("due_date") else "截止时间：待确认",
        f"风险等级：{levels.get(todo.get('risk_level'), todo.get('risk_level', ''))}",
        f"来源会议：{todo['meeting_title']}" if todo.get("meeting_title") else "",
        "",
        "请回复确认处理计划。",
        "",
        f"—— {config.app_name}",
    ]
    return {"subject": f"[待办提醒] {todo['title']}", "body": "\n".join(lines)}


def smtp_configured(settings: SmtpConfig | None = None) -> bool:
    current = settings or config.smtp
    return bool(current.host and current.from_address)


def _connect(settings: SmtpConfig) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if settings.secure:
        client: smtplib.SMTP = smtplib.SMTP_SSL(settings.host, settings.port, timeout=30, context=context)
    else:
        client = smtplib.SMTP(settings.host, settings.port, timeout=30)
        client.starttls(context=context)
    if settings.user:
        client.login(settings.user, settings.password)
    return client


def _send_email(to: str, subject: str, body: str, settings: SmtpConfig) -> dict[str, Any]:
    message = EmailMessage()
    message["From"] = settings.from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with _connect(settings) as client:
        refused = client.send_message(message)
    return {
        "messageId": message.get("Message-ID", ""),
        "accepted": [address.strip() for address in to.split(",") if address.strip() not in refused],
        "rejected": list(refused),
    }


async def send_todo_email(
    to: str, subject: str, body: str, settings: SmtpConfig | None = None
) -> dict[str, Any]:
    current = settings or config.smtp
    if not smtp_configured(current):
        raise RuntimeError("SMTP 尚未配置，请先在前端邮件设置中完成配置")
    try:
        return await retry_async(
            lambda: asyncio.to_thread(_send_email, to, subject, body, current),
            provider="smtp",
            operation_name="send_email",
            retry_exceptions=(OSError, smtplib.SMTPException, ssl.SSLError),
        )
    except ProviderError as error:
        raise RuntimeError(f"邮件发送失败：{error}") from error


def _test_connection(settings: SmtpConfig) -> None:
    with _connect(settings) as client:
        code, message = client.noop()
        if code >= 400:
            raise RuntimeError(f"SMTP 服务器返回 {code}: {message.decode(errors='replace')}")


async def test_smtp_connection(settings: SmtpConfig) -> None:
    if not smtp_configured(settings):
        raise RuntimeError("请先填写 SMTP 服务器和发件人地址")
    try:
        await retry_async(
            lambda: asyncio.to_thread(_test_connection, settings),
            provider="smtp",
            operation_name="test_connection",
            retry_exceptions=(OSError, smtplib.SMTPException, ssl.SSLError),
        )
    except ProviderError as error:
        raise RuntimeError(f"SMTP 连接失败：{error}") from error

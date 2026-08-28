from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ..config import SmtpConfig, config
from ..store import Store

EMAIL_SETTING_KEY = "smtp_config"


def _cipher(data_dir: Path) -> Fernet:
    configured_key = os.getenv("SETTINGS_ENCRYPTION_KEY", "").strip()
    if configured_key:
        try:
            return Fernet(configured_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise RuntimeError("SETTINGS_ENCRYPTION_KEY 格式无效，必须是 Fernet 密钥") from error

    key_file = data_dir / ".settings.key"
    if not key_file.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            with key_file.open("xb") as stream:
                stream.write(Fernet.generate_key())
            try:
                key_file.chmod(0o600)
            except OSError:
                pass
        except FileExistsError:
            pass
    return Fernet(key_file.read_bytes().strip())


def save_smtp_settings(store: Store, data_dir: Path, settings: SmtpConfig) -> None:
    payload = json.dumps(asdict(settings), ensure_ascii=False).encode("utf-8")
    token = _cipher(data_dir).encrypt(payload).decode("ascii")
    store.set_setting(EMAIL_SETTING_KEY, token)


def delete_smtp_settings(store: Store) -> bool:
    return store.delete_setting(EMAIL_SETTING_KEY)


def load_stored_smtp_settings(store: Store, data_dir: Path) -> SmtpConfig | None:
    token = store.get_setting(EMAIL_SETTING_KEY)
    if not token:
        return None
    try:
        value: dict[str, Any] = json.loads(_cipher(data_dir).decrypt(token.encode("ascii")))
        return SmtpConfig(
            host=str(value.get("host") or ""),
            port=int(value.get("port") or 587),
            secure=bool(value.get("secure")),
            user=str(value.get("user") or ""),
            password=str(value.get("password") or ""),
            from_address=str(value.get("from_address") or ""),
        )
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("已保存的邮件配置无法解密，请检查 SETTINGS_ENCRYPTION_KEY") from error


def resolve_smtp_settings(store: Store, data_dir: Path) -> tuple[SmtpConfig, str]:
    stored = load_stored_smtp_settings(store, data_dir)
    if stored is not None:
        return stored, "frontend"
    if config.smtp.host or config.smtp.from_address:
        return config.smtp, "environment"
    return config.smtp, "none"


def public_smtp_settings(settings: SmtpConfig, source: str) -> dict[str, Any]:
    return {
        "host": settings.host,
        "port": settings.port,
        "secure": settings.secure,
        "user": settings.user,
        "fromAddress": settings.from_address,
        "passwordConfigured": bool(settings.password),
        "configured": bool(settings.host and settings.from_address),
        "source": source,
    }

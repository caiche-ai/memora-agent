from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path
from typing import Any

import httpx

from ..config import AuthConfig

PHONE_PATTERN = re.compile(r"^\+?[0-9]{6,20}$")
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1


def normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s()-]", "", str(value or "").strip())
    if not PHONE_PATTERN.fullmatch(phone):
        raise ValueError("请输入有效的手机号码")
    return phone


def normalize_username(value: str) -> str:
    username = str(value or "").strip().lower()
    if not username:
        raise ValueError("账号不能为空")
    return username


def hash_password(password: str) -> str:
    value = str(password or "")
    if not value:
        raise ValueError("密码不能为空")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        value.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=32,
    )
    encoded_salt = urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    encoded_hash = urlsafe_b64encode(derived).decode("ascii").rstrip("=")
    return f"scrypt${PASSWORD_SCRYPT_N}${PASSWORD_SCRYPT_R}${PASSWORD_SCRYPT_P}${encoded_salt}${encoded_hash}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, encoded_salt, encoded_hash = str(encoded or "").split("$", 5)
        if algorithm != "scrypt":
            return False
        cost, block_size, parallelization = int(n), int(r), int(p)
        if (cost, block_size, parallelization) != (
            PASSWORD_SCRYPT_N,
            PASSWORD_SCRYPT_R,
            PASSWORD_SCRYPT_P,
        ):
            return False
        salt = urlsafe_b64decode(encoded_salt + "=" * (-len(encoded_salt) % 4))
        expected = urlsafe_b64decode(encoded_hash + "=" * (-len(encoded_hash) % 4))
        derived = hashlib.scrypt(
            str(password or "").encode("utf-8"),
            salt=salt,
            n=cost,
            r=block_size,
            p=parallelization,
            dklen=len(expected),
        )
        return hmac.compare_digest(derived, expected)
    except (TypeError, ValueError):
        return False


def resolve_auth_secret(data_dir: Path, configured_secret: str) -> bytes:
    if configured_secret:
        return configured_secret.encode("utf-8")
    key_file = data_dir / ".auth.key"
    if key_file.exists():
        value = key_file.read_text(encoding="ascii").strip()
        if value:
            return value.encode("ascii")
    value = secrets.token_urlsafe(48)
    key_file.write_text(value, encoding="ascii")
    return value.encode("ascii")


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(secret: bytes, phone: str, code: str) -> str:
    return hmac.new(secret, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    phone = str(user.get("phone") or "")
    username = str(user.get("username") or "")
    return {
        "id": user["id"],
        "phone": phone or None,
        "username": username or None,
        "hasPassword": bool(user.get("password_hash")),
        "displayName": user.get("display_name") or username or mask_phone(phone),
        "role": user["role"],
        "status": user["status"],
        "createdAt": user.get("created_at"),
        "lastLoginAt": user.get("last_login_at"),
    }


def mask_phone(phone: str) -> str:
    if len(phone) <= 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


async def deliver_sms(config: AuthConfig, phone: str, code: str) -> None:
    if not config.sms_webhook_url:
        if config.debug_code:
            return
        raise RuntimeError("短信服务尚未配置")
    headers = {"content-type": "application/json"}
    if config.sms_webhook_token:
        headers["authorization"] = f"Bearer {config.sms_webhook_token}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                config.sms_webhook_url,
                headers=headers,
                json={"phone": phone, "code": code, "expiresIn": config.code_ttl_seconds},
            )
            response.raise_for_status()
    except httpx.HTTPError as error:
        raise RuntimeError("验证码发送失败，请稍后重试") from error

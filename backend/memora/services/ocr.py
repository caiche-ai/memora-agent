from __future__ import annotations

from typing import Any

from ..config import config
from .provider import ProviderError, request_json


def ocr_configured() -> bool:
    return bool(config.ocr_api_url)


async def extract_pdf_with_ocr(filename: str, data: bytes) -> dict[str, Any] | None:
    if not config.ocr_api_url:
        return None
    headers = {"Authorization": f"Bearer {config.ocr_api_key}"} if config.ocr_api_key else {}
    try:
        payload = await request_json(
            provider="ocr",
            operation_name="extract_pdf",
            method="POST",
            url=config.ocr_api_url,
            timeout=120,
            headers=headers,
            files={"file": (filename, data, "application/pdf")},
        )
        raw_pages = payload.get("pages") if isinstance(payload, dict) else None
        if isinstance(raw_pages, list):
            pages = [
                {
                    "page_number": int(item.get("page_number") or index),
                    "text": str(item.get("text") or "").strip(),
                }
                for index, item in enumerate(raw_pages, 1)
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ]
        else:
            text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
            pages = [{"page_number": 1, "text": text}] if text else []
        if not pages:
            return None
        return {
            "pages": pages,
            "text": "\n\n".join(item["text"] for item in pages),
            "format": "pdf",
            "ocr": True,
        }
    except (ProviderError, ValueError, TypeError, KeyError):
        return None

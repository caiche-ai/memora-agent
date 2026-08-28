from __future__ import annotations

import re
from typing import Any

from .llm import complete_json


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.8


def _iso_date(value: Any) -> str | None:
    candidate = str(value or "")[:10]
    return candidate if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", candidate) else None


def heuristic_chat_memories(text: str, message_id: int) -> list[dict[str, Any]]:
    patterns = [
        (
            "person",
            re.compile(r"(?:我叫|我是|联系人是|负责人是)([\u4e00-\u9fffA-Za-z· ]{2,20})"),
            lambda match: match.group(1),
            lambda match: match.group(0),
        ),
        (
            "preference",
            re.compile(r"我(?:喜欢|偏好|习惯|不喜欢)[^。！？\n]{1,80}"),
            lambda _: "用户偏好",
            lambda match: match.group(0),
        ),
        (
            "location",
            re.compile(r"(?:地点(?:是|在)|位于|会议室是)[^，。！？\n]{1,40}"),
            lambda _: "地点",
            lambda match: match.group(0),
        ),
        (
            "time",
            re.compile(r"(?:时间(?:是|定在)|截止到|截止时间)[^，。！？\n]{1,40}"),
            lambda _: "时间",
            lambda match: match.group(0),
        ),
        (
            "topic",
            re.compile(r"(?:我们在做|项目是|主题是|正在讨论)[^。！？\n]{1,80}"),
            lambda _: "主题",
            lambda match: match.group(0),
        ),
    ]
    memories = []
    for kind, pattern, subject, content in patterns:
        for match in pattern.finditer(text):
            memories.append(
                {
                    "type": kind,
                    "subject": subject(match).strip(),
                    "content": content(match).strip(),
                    "source_type": "chat",
                    "source_id": message_id,
                    "confidence": 0.75,
                    "sensitivity": "private",
                }
            )
    return memories


async def extract_chat_memories(text: str, message_id: int) -> list[dict[str, Any]]:
    fallback = heuristic_chat_memories(text, message_id)
    result = await complete_json(
        [
            {
                "role": "system",
                "content": "从用户消息中提取值得长期记忆且明确陈述的信息。输出 JSON："
                "{memories:[{type,subject,content,confidence,validFrom,validUntil,sensitivity}]}。"
                "type 只能是 person、time、location、topic、preference、fact；confidence 为 0 到 1；"
                "日期仅在原文明示时写 YYYY-MM-DD，否则为 null；sensitivity 为 private 或 sensitive。"
                "subject 应具体稳定，例如‘项目验收日期’，不要只写‘时间’或‘事实’。"
                "不要记录临时问题，不要推断。",
            },
            {"role": "user", "content": text},
        ],
        {"memories": fallback},
    )
    values = result.get("memories", fallback) if isinstance(result, dict) else fallback
    allowed = {"person", "time", "location", "topic", "preference", "fact"}
    importance = {"preference": 4, "fact": 4, "person": 3, "time": 3, "location": 3, "topic": 3}
    return [
        {
            "type": kind,
            "subject": str(item.get("subject") or "")[:80],
            "content": str(item["content"])[:500],
            "source_type": "chat",
            "source_id": message_id,
            "importance": importance[kind],
            "confidence": _confidence(item.get("confidence")),
            "valid_from": _iso_date(item.get("validFrom")),
            "valid_until": _iso_date(item.get("validUntil")),
            "sensitivity": "sensitive" if item.get("sensitivity") == "sensitive" else "private",
        }
        for item in values[:12]
        if isinstance(item, dict) and item.get("content")
        for kind in [item.get("type") if item.get("type") in allowed else "fact"]
    ]

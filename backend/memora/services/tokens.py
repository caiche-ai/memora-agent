from __future__ import annotations

from typing import Any

import httpx

from .llm import complete


def estimate_tokens(value: str) -> int:
    ascii_count = sum(ord(char) < 128 for char in value)
    return max(1, len(value) - ascii_count + (ascii_count + 3) // 4)


def trim_to_tokens(value: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    if estimate_tokens(value) <= token_budget:
        return value
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(value[:middle]) <= token_budget:
            low = middle
        else:
            high = middle - 1
    return value[:low].rstrip() + "…"


def fit_content_items(
    items: list[dict[str, Any]], token_budget: int, *, content_key: str = "content"
) -> list[dict[str, Any]]:
    if not items or token_budget <= 0:
        return []
    per_item = max(160, token_budget // len(items))
    result: list[dict[str, Any]] = []
    remaining = token_budget
    for item in items:
        if remaining <= 0:
            break
        allowance = min(remaining, per_item)
        content = trim_to_tokens(str(item.get(content_key) or ""), allowance)
        if content:
            result.append({**item, content_key: content})
            remaining -= estimate_tokens(content)
    return result


def _fallback_summary(messages: list[dict[str, Any]], token_budget: int = 700) -> str:
    lines = []
    for item in messages[-20:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = " ".join(str(item.get("content") or "").split())
        if content:
            lines.append(f"- {role}：{content[:180]}")
    return trim_to_tokens("\n".join(lines), token_budget)


async def compact_history(
    messages: list[dict[str, Any]], token_budget: int
) -> tuple[list[dict[str, Any]], str]:
    if sum(estimate_tokens(str(item.get("content") or "")) for item in messages) <= token_budget:
        return messages, ""
    recent_budget = max(160, int(token_budget * 0.72))
    recent_budget = min(token_budget, recent_budget)
    recent: list[dict[str, Any]] = []
    used = 0
    split_index = len(messages)
    for index in range(len(messages) - 1, -1, -1):
        item = messages[index]
        cost = estimate_tokens(str(item.get("content") or ""))
        if not recent and cost > recent_budget:
            recent.append(
                {
                    **item,
                    "content": trim_to_tokens(str(item.get("content") or ""), recent_budget),
                }
            )
            used = recent_budget
            split_index = index
            break
        if recent and used + cost > recent_budget:
            split_index = index + 1
            break
        recent.append(item)
        used += cost
        split_index = index
    recent.reverse()
    older = messages[:split_index]
    fallback = _fallback_summary(older)
    if not older:
        return recent, ""
    try:
        generated = await complete(
            [
                {
                    "role": "system",
                    "content": "压缩较早的对话，只保留用户身份、偏好、事实、决定、未解决问题和后续约定。不得补充原文没有的信息，使用简洁中文。",
                },
                {"role": "user", "content": fallback},
            ],
            temperature=0.1,
        )
    except (RuntimeError, httpx.HTTPError):
        generated = None
    return recent, trim_to_tokens(generated or fallback, max(0, token_budget - used))

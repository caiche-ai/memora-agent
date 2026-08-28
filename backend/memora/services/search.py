from __future__ import annotations

import re
from typing import Any

from ..config import config
from .provider import ProviderError, request_json

WEB_PATTERN = re.compile(
    r"今天|今日|现在|当前|最新|实时|近期|本周|新闻|天气|股价|汇率|价格|政策|法规|版本|发布|搜索|查询|联网|查一下|查找|recent|latest|today|current",
    re.I,
)


def needs_web_search(query: str) -> bool:
    return bool(WEB_PATTERN.search(query))


async def search_web(query: str, tavily_api_key: str | None = None) -> list[dict[str, Any]]:
    key = config.tavily_api_key if tavily_api_key is None else tavily_api_key
    try:
        if key:
            data = await request_json(
                provider="tavily",
                operation_name="web_search",
                method="POST",
                url="https://api.tavily.com/search",
                timeout=15,
                json_body={
                    "api_key": key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_answer": True,
                },
            )
            return [
                {"title": item["title"], "url": item["url"], "content": item.get("content", "")}
                for item in data.get("results", [])
            ]
        data = await request_json(
            provider="duckduckgo",
            operation_name="web_search",
            method="GET",
            url="https://api.duckduckgo.com/",
            timeout=15,
            headers={"User-Agent": "Memora/1.0"},
            params={
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1",
            },
        )
        results = []
        if data.get("AbstractText"):
            results.append(
                {
                    "title": data.get("Heading") or query,
                    "url": data.get("AbstractURL") or "https://duckduckgo.com",
                    "content": data["AbstractText"],
                }
            )
        for item in data.get("RelatedTopics", []):
            if item.get("Text") and item.get("FirstURL"):
                results.append(
                    {"title": item["Text"].split(" - ")[0], "url": item["FirstURL"], "content": item["Text"]}
                )
            if len(results) >= 5:
                break
        return results
    except (ProviderError, ValueError, KeyError) as error:
        return [{"title": "联网查询暂时不可用", "url": "", "content": str(error), "error": True}]

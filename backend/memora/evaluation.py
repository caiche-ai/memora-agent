from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_markdown_scenarios(filename: str | Path) -> list[dict[str, Any]]:
    content = Path(filename).read_text(encoding="utf-8")
    scenarios: list[dict[str, Any]] = []
    for block in re.findall(r"```json\s*(.*?)```", content, re.S | re.I):
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            scenarios.extend(item for item in value if isinstance(item, dict) and item.get("id"))
    return scenarios


def evaluate_intent_scenarios(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    from .services.intent import route_intent

    cases = [item for item in scenarios if item.get("request") and item.get("expectedIntent")]
    results = []
    for item in cases:
        decision = route_intent(str(item["request"]))
        expected_web = item.get("expectedWebSearch")
        passed = decision.name == item["expectedIntent"] and (
            expected_web is None or decision.web_search is bool(expected_web)
        )
        results.append(
            {
                "id": item["id"],
                "passed": passed,
                "expectedIntent": item["expectedIntent"],
                "actualIntent": decision.name,
                "expectedWebSearch": expected_web,
                "actualWebSearch": decision.web_search,
            }
        )
    passed_count = sum(item["passed"] for item in results)
    return {
        "total": len(results),
        "passed": passed_count,
        "accuracy": passed_count / len(results) if results else 0.0,
        "failures": [item for item in results if not item["passed"]],
    }

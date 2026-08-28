from __future__ import annotations

import re
from typing import Any


def meeting_analysis_markdown(analysis: dict[str, Any]) -> str:
    def bullets(values: list[Any], empty: str) -> str:
        return "\n".join(f"- {value}" for value in values) if values else empty

    level_names = {"high": "高", "medium": "中", "low": "低"}
    risks = analysis.get("risks") or []
    risk_text = (
        "\n\n".join(
            f"### {risk['title']}\n\n- **风险等级：** "
            f"{level_names.get(risk.get('level'), risk.get('level', '中'))}\n\n"
            f"{risk.get('description', '')}"
            for risk in risks
        )
        if risks
        else "未发现明确风险。"
    )
    decisions = analysis.get("decisions") or []
    decision_text = (
        "\n".join(f"{index}. {item}" for index, item in enumerate(decisions, 1))
        if decisions
        else "未识别到明确决策。"
    )
    todos = analysis.get("todos") or []
    todo_text = (
        "\n\n".join(
            f"### {item['title']}\n\n{item.get('description', '')}\n\n"
            f"- **负责人：** {item.get('owner') or '待确认'}\n"
            f"- **截止日期：** {item.get('dueDate') or '待确认'}\n"
            f"- **风险等级：** "
            f"{level_names.get(item.get('riskLevel'), item.get('riskLevel', '中'))}"
            for item in todos
        )
        if todos
        else "未识别到明确待办。"
    )
    return "\n\n".join(
        [
            f"# {analysis.get('title') or '会议详情'}",
            "## 会议摘要",
            str(analysis.get("summary") or "未生成摘要。"),
            "## 参会人物",
            bullets(analysis.get("participants") or [], "未识别到参会人物。"),
            "## 时间与地点",
            bullets(
                [*(analysis.get("dates") or []), *(analysis.get("locations") or [])],
                "未识别到时间或地点。",
            ),
            "## 讨论主题",
            bullets(analysis.get("topics") or [], "未识别到讨论主题。"),
            "## 风险",
            risk_text,
            "## 决策",
            decision_text,
            "## 待办",
            todo_text,
        ]
    )


def meeting_email_markdown(analysis: dict[str, Any]) -> str:
    def bullets(values: list[Any], empty: str) -> str:
        return "\n".join(f"- {value}" for value in values) if values else empty

    decisions = analysis.get("decisions") or []
    risks = analysis.get("risks") or []
    todos = analysis.get("todos") or []
    risk_text = bullets(
        [f"{item.get('title', '未命名风险')}：{item.get('description', '')}" for item in risks],
        "- 暂无明确风险",
    )
    todo_text = bullets(
        [
            f"{item.get('title', '未命名待办')}（负责人：{item.get('owner') or '待确认'}；"
            f"截止：{item.get('dueDate') or '待确认'}）"
            for item in todos
        ],
        "- 暂无明确行动项",
    )
    title = str(analysis.get("title") or "会议")
    return "\n\n".join(
        [
            "# 会议邮件内容",
            f"**主题：** {title}会议纪要与后续行动",
            "**收件人：** 待填写",
            "---",
            "您好，",
            f"以下是本次“{title}”的会议结论和后续安排，请查收。",
            "## 会议摘要",
            str(analysis.get("summary") or "暂无会议摘要。"),
            "## 主要决策",
            bullets(decisions, "- 暂无明确决策"),
            "## 风险提示",
            risk_text,
            "## 后续行动",
            todo_text,
            "如有遗漏或理解偏差，请直接回复补充。谢谢。",
        ]
    )


def meeting_artifact_name(analysis: dict[str, Any], content_type: str) -> str:
    model_title = str(analysis.get("title") or "会议").strip()
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", model_title).strip(" ._")
    safe_title = safe_title[:100] or "会议"
    suffix = "邮件内容" if content_type == "email_content" else "会议详情"
    return f"{safe_title}_{suffix}.md"

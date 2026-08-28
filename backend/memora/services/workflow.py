from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .context import AgentContext
from .errors import AgentError
from .intent import IntentDecision
from .llm import answer_question
from .meeting import analyze_meeting
from .meeting_artifacts import (
    meeting_analysis_markdown,
    meeting_artifact_name,
    meeting_email_markdown,
)
from .ppt import create_presentation


@dataclass
class WorkflowOutput:
    content: str
    artifact: dict[str, Any] | None = None
    artifact_draft: dict[str, Any] | None = None


@dataclass(frozen=True)
class MeetingWorkflowInput:
    meeting_id: int
    source_name: str
    source_text: str
    background_documents: list[dict[str, Any]]


@dataclass(frozen=True)
class WorkflowRequest:
    decision: IntentDecision
    query: str
    context: AgentContext
    data_dir: Path
    meeting: MeetingWorkflowInput | None = None


WorkflowHandler = Callable[[WorkflowRequest], Awaitable[WorkflowOutput]]
WORKFLOW_REGISTRY: dict[str, WorkflowHandler] = {}


def workflow_handler(*intent_names: str) -> Callable[[WorkflowHandler], WorkflowHandler]:
    def register(handler: WorkflowHandler) -> WorkflowHandler:
        for intent_name in intent_names:
            WORKFLOW_REGISTRY[intent_name] = handler
        return handler

    return register


@workflow_handler("chat")
async def execute_chat(request: WorkflowRequest) -> WorkflowOutput:
    return WorkflowOutput(
        content=await answer_question(
            query=request.query,
            history=request.context.history,
            document_context=request.context.documents,
            memories=request.context.memories,
            web_results=request.context.web_results,
            history_summary=request.context.history_summary,
        )
    )


@workflow_handler("ppt")
async def execute_ppt(request: WorkflowRequest) -> WorkflowOutput:
    generated = await create_presentation(
        request.query,
        request.data_dir,
        document_context=request.context.documents,
        memories=request.context.memories,
        web_results=request.context.web_results,
    )
    return WorkflowOutput(
        content=(
            f"PPT 已生成：《{generated['outline']['title']}》，共 "
            f"{len(generated['outline']['slides']) + 1} 页。"
            "内容已结合当前文件、记忆和可用的联网结果，你可以直接下载并继续编辑。"
        ),
        artifact=generated,
    )


@workflow_handler("meeting_detail", "email_content")
async def execute_meeting_artifact(request: WorkflowRequest) -> WorkflowOutput:
    meeting = request.meeting
    if meeting is None:
        raise AgentError(
            "请先输入 @ 并选择要处理的会议文件",
            code="meeting_file_required",
            category="context",
            status_code=422,
            stage="context",
        )
    analysis = await analyze_meeting(
        meeting.source_text,
        meeting.source_name,
        meeting.background_documents,
        request.query,
        memories=request.context.memories,
        web_results=request.context.web_results,
    )
    content_type = request.decision.name
    content = (
        meeting_email_markdown(analysis)
        if content_type == "email_content"
        else meeting_analysis_markdown(analysis)
    )
    type_name = "邮件内容" if content_type == "email_content" else "会议详情"
    background_ids = [item["id"] for item in meeting.background_documents]
    provenance = request.context.provenance()
    source_document_ids = list(dict.fromkeys([*provenance["sourceDocumentIds"], *background_ids]))
    return WorkflowOutput(
        content=f"{type_name}草稿已生成。请确认内容，必要时编辑后再保存到 Artifacts。",
        artifact_draft={
            "kind": "markdown",
            "status": "draft",
            "confirmationRequired": True,
            "idempotencyKey": uuid4().hex,
            "meetingId": meeting.meeting_id,
            "contentType": content_type,
            "name": meeting_artifact_name(analysis, content_type),
            "content": content,
            "analysis": analysis,
            "context": {
                **provenance,
                "sourceDocumentIds": source_document_ids,
            },
        },
    )


async def execute_workflow(
    *,
    decision: IntentDecision,
    query: str,
    context: AgentContext,
    data_dir: Path,
    meeting: MeetingWorkflowInput | None = None,
) -> WorkflowOutput:
    handler = WORKFLOW_REGISTRY.get(decision.name)
    if handler is None:
        raise AgentError(
            f"暂不支持意图：{decision.name}",
            code="unsupported_intent",
            category="routing",
            status_code=422,
            stage="routing",
        )
    return await handler(
        WorkflowRequest(
            decision=decision,
            query=query,
            context=context,
            data_dir=data_dir,
            meeting=meeting,
        )
    )

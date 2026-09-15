from __future__ import annotations

import hashlib
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .config import SmtpConfig, config, ensure_data_dirs
from .services.agentmail import (
    agentmail_configured,
    ensure_agentmail_inbox,
    send_agentmail_message,
)
from .services.auth import (
    deliver_sms,
    generate_code,
    generate_session_token,
    hash_code,
    hash_password,
    hash_session_token,
    normalize_phone,
    normalize_username,
    public_user,
    resolve_auth_secret,
    verify_password,
)
from .services.context import AgentContext, ContextBuildError, build_context, build_project_support_context
from .services.documents import SUPPORTED_EXTENSIONS, chunk_pages, decode_text, extract_knowledge_file
from .services.email import create_todo_email, send_todo_email, smtp_configured, test_smtp_connection
from .services.embeddings import embed_texts, embedding_enabled
from .services.errors import AgentError
from .services.intent import IntentDecision, route_intent
from .services.llm import llm_enabled
from .services.meeting import meeting_memories
from .services.memory import extract_chat_memories
from .services.observability import current_trace_id, emit_trace_event, trace_context
from .services.ocr import extract_pdf_with_ocr, ocr_configured
from .services.provider import ProviderError, provider_health
from .services.settings import (
    delete_smtp_settings,
    public_smtp_settings,
    resolve_smtp_settings,
    save_smtp_settings,
)
from .services.tasks import TaskManager
from .services.tencent_meeting import TencentMeetingClient
from .services.workflow import MeetingWorkflowInput, execute_workflow
from .store import Store


class ConversationInput(BaseModel):
    title: str = Field(default="新对话", max_length=80)


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)


class ProjectRenameInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MeetingRenameInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TencentMeetingImportInput(BaseModel):
    record_file_id: str = Field(alias="recordFileId", min_length=1, max_length=160)
    meeting_id: str | None = Field(default=None, alias="meetingId", max_length=160)
    meeting_record_id: str | None = Field(default=None, alias="meetingRecordId", max_length=160)
    title: str | None = Field(default=None, max_length=120)


class ArtifactRenameInput(BaseModel):
    name: str = Field(min_length=1, max_length=180)


class DocumentContentInput(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)


MemoryType = Literal["person", "time", "location", "topic", "preference", "fact", "decision", "risk"]


class MemoryCreateInput(BaseModel):
    type: MemoryType
    subject: str = Field(default="", max_length=80)
    content: str = Field(min_length=1, max_length=500)
    project_id: int | None = Field(default=None, alias="projectId")
    importance: int = Field(default=3, ge=1, le=5)
    pinned: bool = False
    confidence: float = Field(default=1.0, ge=0, le=1)
    valid_from: str | None = Field(default=None, alias="validFrom", max_length=10)
    valid_until: str | None = Field(default=None, alias="validUntil", max_length=10)
    sensitivity: Literal["private", "sensitive"] = "private"


class MemoryUpdateInput(BaseModel):
    type: MemoryType | None = None
    subject: str | None = Field(default=None, max_length=80)
    content: str | None = Field(default=None, min_length=1, max_length=500)
    importance: int | None = Field(default=None, ge=1, le=5)
    pinned: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_from: str | None = Field(default=None, alias="validFrom", max_length=10)
    valid_until: str | None = Field(default=None, alias="validUntil", max_length=10)
    status: Literal["active", "superseded", "expired"] | None = None
    sensitivity: Literal["private", "sensitive"] | None = None


class MeetingDraftInput(BaseModel):
    instruction: str = Field(default="", max_length=2_000)
    content_type: Literal["meeting_detail", "email_content"] = Field(
        default="meeting_detail", alias="contentType"
    )


class MeetingDetailSaveInput(BaseModel):
    name: str = Field(default="会议详情.md", min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=500_000)
    analysis: dict[str, Any]
    content_type: Literal["meeting_detail", "email_content"] = Field(
        default="meeting_detail", alias="contentType"
    )
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey", max_length=80)


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    document_ids: list[int] = Field(default_factory=list, alias="documentIds", max_length=8)
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey", max_length=100)


class TodoInput(BaseModel):
    status: str | None = None
    owner: str | None = Field(default=None, max_length=80)
    dueDate: str | None = Field(default=None, max_length=40)


class EmailInput(BaseModel):
    to: str
    subject: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20_000)
    provider: Literal["agentmail", "smtp"] | None = None
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey", max_length=100)


class EmailSettingsInput(BaseModel):
    host: str = Field(max_length=255)
    port: int = Field(ge=1, le=65_535)
    secure: bool = False
    user: str = Field(default="", max_length=255)
    password: str | None = Field(default=None, max_length=500)
    from_address: str = Field(alias="fromAddress", max_length=320)


class SmsCodeInput(BaseModel):
    phone: str = Field(min_length=6, max_length=32)


class SmsLoginInput(SmsCodeInput):
    code: str = Field(pattern=r"^\d{6}$")


class PasswordLoginInput(BaseModel):
    account: str
    password: str


class AccountRegisterInput(BaseModel):
    username: str
    password: str
    phone: str | None = Field(default=None, max_length=32)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")


class AccountCredentialsInput(BaseModel):
    username: str
    password: str
    current_password: str | None = Field(default=None, alias="currentPassword")


class PhoneBindingInput(SmsLoginInput):
    pass


class UserRoleInput(BaseModel):
    role: Literal["admin", "member"]


class ProjectMemberInput(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    role: Literal["editor", "viewer"] = "viewer"


def _public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": artifact["id"],
        "kind": artifact["kind"],
        "name": artifact["name"],
        "metadata": artifact["metadata"],
        "downloadUrl": f"/api/artifacts/{artifact['id']}/download",
    }


def _public_memory(memory: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in memory.items() if key != "embedding"}


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "kind": task.get("kind"),
        "status": task.get("status"),
        "progress": task.get("progress", 0),
        "attempts": task.get("attempts", 0),
        "maxAttempts": task.get("max_attempts", 0),
        "result": task.get("result"),
        "error": task.get("error"),
        "traceId": task.get("trace_id"),
        "createdAt": task.get("created_at"),
        "updatedAt": task.get("updated_at"),
        "availableAt": task.get("available_at"),
        "startedAt": task.get("started_at"),
        "completedAt": task.get("completed_at"),
        "pollUrl": f"/api/tasks/{task.get('id')}",
    }


def _public_dead_letter(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "taskId": item.get("task_id"),
        "task": _public_task(item.get("task") or {}),
        "error": item.get("error"),
        "compensationStatus": item.get("compensation_status"),
        "compensationResult": item.get("compensation_result"),
        "resolution": item.get("resolution"),
        "resolvedAt": item.get("resolved_at"),
        "createdAt": item.get("created_at"),
        "updatedAt": item.get("updated_at"),
    }


def _public_email_delivery(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "sourceType": item.get("source_type"),
        "sourceId": item.get("source_id"),
        "provider": item.get("provider"),
        "recipient": item.get("recipient"),
        "subject": item.get("subject"),
        "status": item.get("status"),
        "attempts": item.get("attempts"),
        "error": item.get("error"),
        "resolution": item.get("resolution"),
        "resolvedAt": item.get("resolved_at"),
        "createdAt": item.get("created_at"),
        "updatedAt": item.get("updated_at"),
        "sentAt": item.get("sent_at"),
    }


def _artifact_email_draft(document: dict[str, Any]) -> dict[str, str]:
    content = str(document.get("text_content") or "").strip()
    subject_match = re.search(r"^\*\*主题：\*\*\s*(.+)$", content, re.MULTILINE)
    subject = subject_match.group(1).strip() if subject_match else Path(document["name"]).stem
    body_lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "# 会议邮件内容" or stripped == "---":
            continue
        if re.match(r"^\*\*(?:主题|收件人)：\*\*", stripped):
            continue
        body_lines.append(line)
    return {"subject": subject, "body": "\n".join(body_lines).strip() or content}


def create_app(
    *,
    data_dir: Path | None = None,
    store: Store | None = None,
    tencent_meeting_client: TencentMeetingClient | None = None,
    auth_enabled: bool | None = None,
) -> FastAPI:
    target_dir = ensure_data_dirs(data_dir or config.data_dir)
    current_store = store or Store(target_dir / "memora.db")
    task_manager = TaskManager(current_store)
    meeting_connector = tencent_meeting_client or TencentMeetingClient(config.tencent_meeting)
    use_auth = config.auth.enabled if auth_enabled is None else auth_enabled
    auth_secret = resolve_auth_secret(target_dir, config.auth.secret) if use_auth else b"auth-disabled"
    request_user: ContextVar[dict[str, Any] | None] = ContextVar("memora_request_user", default=None)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task_manager.recover()
        yield
        await task_manager.shutdown()

    app = FastAPI(
        title=config.app_name,
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.frontend_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = current_store
    app.state.data_dir = target_dir
    app.state.task_manager = task_manager
    app.state.tencent_meeting = meeting_connector
    app.state.auth_enabled = use_auth

    def auth_error(status_code: int, message: str, code: str) -> JSONResponse:
        return JSONResponse(
            {
                "error": message,
                "errorDetail": {
                    "code": code,
                    "category": "authentication" if status_code == 401 else "authorization",
                    "message": message,
                    "retryable": False,
                    "stage": "request",
                    "details": {},
                },
            },
            status_code=status_code,
        )

    def permission_error(message: str = "无权访问该资源") -> JSONResponse:
        return auth_error(403, message, "resource_forbidden")

    def sufficient_project_role(role: str | None, required: str) -> bool:
        ranks = {"viewer": 1, "editor": 2, "owner": 3}
        return bool(role and ranks.get(role, 0) >= ranks[required])

    @app.middleware("http")
    async def authenticate_request(request: Request, call_next):
        path = request.url.path
        public = (
            request.method == "OPTIONS"
            or path in {"/", "/api/health", "/openapi.json"}
            or path.startswith("/api/auth/")
            or path.startswith("/api/docs")
        )
        if not use_auth or public:
            request.state.user = None
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        token = token.strip() if scheme.lower() == "bearer" else ""
        token = token or request.cookies.get("memora_session", "").strip()
        if not token:
            return auth_error(401, "请先登录", "authentication_required")
        user = current_store.get_user_by_session(hash_session_token(token.strip()))
        if not user:
            return auth_error(401, "登录状态已失效，请重新登录", "invalid_session")
        request.state.user = user
        if user["role"] == "admin":
            current_store.claim_legacy_resources(int(user["id"]))
        admin_only = (
            path.startswith("/api/admin/")
            or path == "/api/index/rebuild"
            or path == "/api/integrations/tencent-meeting/records"
            or path.endswith("/integrations/tencent-meeting/import")
            or (path.startswith("/api/settings/email") and request.method != "GET")
            or path.startswith("/api/dead-letters")
            or path.startswith("/api/traces")
            or path.startswith("/api/email-deliveries")
            or path == "/api/tasks"
        )
        if admin_only and user["role"] != "admin":
            return auth_error(403, "需要管理员权限", "admin_required")
        parts = [part for part in path.split("/") if part]
        method = request.method.upper()
        resource_role: str | None = None
        required_role = "viewer" if method == "GET" else "editor"
        if len(parts) >= 3 and parts[0] == "api" and parts[2].isdigit():
            resource_id = int(parts[2])
            resource = parts[1]
            if resource == "projects":
                resource_role = current_store.project_role(resource_id, int(user["id"]))
                if method == "DELETE" or (len(parts) >= 4 and parts[3] == "members"):
                    required_role = "owner"
            elif resource == "conversations":
                resource_role = current_store.conversation_role(resource_id, int(user["id"]))
            elif resource == "documents":
                resource_role = current_store.document_role(resource_id, int(user["id"]))
            elif resource == "meetings":
                resource_role = current_store.meeting_role(resource_id, int(user["id"]))
            elif resource == "todos":
                resource_role = current_store.todo_role(resource_id, int(user["id"]))
            elif resource == "memories":
                resource_role = current_store.memory_role(resource_id, int(user["id"]))
            elif resource == "artifacts":
                resource_role = current_store.artifact_role(resource_id, int(user["id"]))
            if resource_role is not None and not sufficient_project_role(resource_role, required_role):
                return permission_error()
            if (
                resource
                in {
                    "projects",
                    "conversations",
                    "documents",
                    "meetings",
                    "todos",
                    "memories",
                    "artifacts",
                }
                and resource_role is None
            ):
                return permission_error()
        if len(parts) >= 3 and parts[:2] == ["api", "tasks"]:
            task = current_store.get_task(parts[2])
            payload = (task or {}).get("payload") or {}
            if not task:
                return permission_error()
            if user["role"] != "admin" and payload.get("userId") != user["id"]:
                return permission_error()
        user_token = request_user.set(user)
        try:
            return await call_next(request)
        finally:
            request_user.reset(user_token)

    async def remember_chat_message(
        content: str,
        message_id: int,
        project_id: int | None,
        user_id: int | None = None,
    ) -> None:
        memories = await extract_chat_memories(content, message_id)
        vectors = await embed_texts([f"{item.get('subject', '')}\n{item['content']}" for item in memories])
        for index, memory in enumerate(memories):
            if len(vectors) == len(memories):
                memory["embedding"] = vectors[index]
            current_store.add_memory(memory, project_id=project_id, created_by=user_id)

    def meeting_workflow_input(project_id: int | None, document_ids: list[int]) -> MeetingWorkflowInput:
        if project_id is None:
            raise AgentError(
                "会议内容只能在项目聊天中生成",
                code="project_context_required",
                category="context",
                status_code=422,
                stage="context",
            )
        selected_ids = set(document_ids)
        selected_meetings = [
            meeting
            for meeting in current_store.list_meetings(project_id)
            if any(file["id"] in selected_ids for file in meeting.get("files", []))
        ]
        if not selected_meetings:
            raise AgentError(
                "请先输入 @ 并选择要处理的会议文件",
                code="meeting_file_required",
                category="context",
                status_code=422,
                stage="context",
            )
        if len(selected_meetings) > 1:
            raise AgentError(
                "一次只能基于一个会议生成内容，请移除其他会议文件",
                code="multiple_meetings_selected",
                category="context",
                status_code=422,
                stage="context",
                details={"meetingIds": [item["id"] for item in selected_meetings]},
            )
        meeting = selected_meetings[0]
        source = current_store.get_document(meeting["document_id"])
        if not source or not str(source.get("text_content") or "").strip():
            raise AgentError(
                "会议原文不存在或内容为空",
                code="meeting_source_empty",
                category="context",
                status_code=422,
                stage="context",
            )
        return MeetingWorkflowInput(
            meeting_id=meeting["id"],
            source_name=source["name"],
            source_text=str(source["text_content"]),
            background_documents=current_store.project_background_documents(project_id),
        )

    def agentmail_inbox_id() -> str:
        return config.agentmail.inbox_id or current_store.get_setting("agentmail_inbox_id") or ""

    def email_settings_payload() -> dict[str, Any]:
        smtp, source = resolve_smtp_settings(current_store, target_dir)
        result = public_smtp_settings(smtp, source)
        system_configured = agentmail_configured()
        result.update(
            {
                "smtpConfigured": smtp_configured(smtp),
                "agentMailConfigured": system_configured,
                "agentMailInbox": agentmail_inbox_id(),
                "defaultProvider": "agentmail"
                if system_configured
                else ("smtp" if smtp_configured(smtp) else "none"),
                "configured": system_configured or smtp_configured(smtp),
            }
        )
        return result

    def smtp_from_input(body: EmailSettingsInput) -> SmtpConfig:
        current, _ = resolve_smtp_settings(current_store, target_dir)
        retain_password = body.password in {None, ""} and body.user.strip() == current.user
        return SmtpConfig(
            host=body.host.strip(),
            port=body.port,
            secure=body.secure,
            user=body.user.strip(),
            password=current.password if retain_password else (body.password or ""),
            from_address=body.from_address.strip(),
        )

    def validate_smtp_settings(settings: SmtpConfig) -> None:
        if not settings.host:
            raise HTTPException(400, "SMTP 服务器不能为空")
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", settings.from_address):
            raise HTTPException(400, "请输入有效的发件人邮箱")

    async def send_email_once(
        *,
        source_type: str,
        source_id: int,
        body: EmailInput,
        draft: dict[str, str],
    ) -> dict[str, Any]:
        recipient = body.to.strip()
        subject = body.subject or draft["subject"]
        message_body = body.body or draft["body"]
        provider = "agentmail" if body.provider != "smtp" and agentmail_configured() else "smtp"
        idempotency_key = (body.idempotency_key or "").strip() or uuid4().hex
        body_hash = hashlib.sha256(message_body.encode("utf-8")).hexdigest()
        delivery, claimed = current_store.claim_email_delivery(
            delivery_id=uuid4().hex,
            idempotency_key=idempotency_key,
            source_type=source_type,
            source_id=source_id,
            provider=provider,
            recipient=recipient,
            subject=subject,
            body_hash=body_hash,
        )
        if any(
            (
                delivery.get("source_type") != source_type,
                delivery.get("source_id") != source_id,
                delivery.get("recipient") != recipient,
                delivery.get("subject") != subject,
                delivery.get("body_hash") != body_hash,
            )
        ):
            raise HTTPException(409, "Idempotency key was reused with different email content")
        if not claimed:
            if delivery.get("status") == "sent":
                return {
                    "ok": True,
                    "deliveryId": delivery["id"],
                    "idempotent": True,
                    **(delivery.get("result") or {}),
                }
            raise HTTPException(409, "Email is already being sent")
        smtp, _ = resolve_smtp_settings(current_store, target_dir)
        try:
            if body.provider == "agentmail" and not agentmail_configured():
                raise RuntimeError("AgentMail is not configured")
            if provider == "agentmail":
                inbox_id = await ensure_agentmail_inbox(agentmail_inbox_id())
                if inbox_id != agentmail_inbox_id():
                    current_store.set_setting("agentmail_inbox_id", inbox_id)
                result = await send_agentmail_message(inbox_id, recipient, subject, message_body)
            else:
                result = await send_todo_email(recipient, subject, message_body, smtp)
        except RuntimeError as error:
            current_store.fail_email_delivery(
                str(delivery["id"]),
                {"code": "email_send_failed", "message": str(error), "retryable": True},
            )
            raise HTTPException(503, str(error)) from error
        current_store.complete_email_delivery(str(delivery["id"]), result)
        return {
            "ok": True,
            "deliveryId": delivery["id"],
            "idempotent": False,
            **result,
        }

    async def process_knowledge_upload(
        file: UploadFile, *, conversation_id: int | None = None, project_id: int | None = None
    ) -> dict[str, Any]:
        filename = file.filename or "document"
        extension = Path(filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise HTTPException(400, "不支持的文件类型；目前支持 PDF、PPTX、TXT 和 Markdown")
        data = await file.read(25 * 1024 * 1024 + 1)
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(413, "文件过大")
        try:
            extracted = extract_knowledge_file(filename, data)
        except Exception as error:
            raise HTTPException(422, f"文件解析失败：{error}") from error
        if not extracted["text"].strip() and extension == ".pdf":
            extracted = await extract_pdf_with_ocr(filename, data) or extracted
        if not extracted["text"].strip():
            message = (
                "PDF 中没有可提取的文本；请配置 OCR_API_URL 后重试扫描件"
                if extension == ".pdf"
                else (
                    "PPTX 中没有可提取的文本；图片型幻灯片暂不支持 OCR"
                    if extension == ".pptx"
                    else "文件内容为空"
                )
            )
            raise HTTPException(422, message)
        chunks = chunk_pages(extracted["pages"])
        document = current_store.add_document(
            conversation_id=conversation_id,
            project_id=project_id,
            name=filename,
            mime_type=file.content_type or "application/octet-stream",
            kind="knowledge",
            text=extracted["text"],
            metadata={
                "pages": len(extracted["pages"]),
                "chunks": len(chunks),
                "size": len(data),
                "format": extracted["format"],
                "ocr": bool(extracted.get("ocr")),
            },
        )
        current_store.add_chunks(document["id"], chunks)
        vectors = await embed_texts([f"{item.get('heading', '')}\n{item['content']}" for item in chunks])
        if len(vectors) == len(chunks):
            current_store.set_chunk_embeddings(document["id"], vectors)
        document.pop("text_content", None)
        return document

    def process_meeting_text(
        project_id: int,
        text: str,
        filename: str,
        meeting_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not current_store.get_project(project_id):
            raise HTTPException(404, "项目不存在")
        text = text.strip()
        if not text:
            raise HTTPException(422, "会议文件内容为空")
        filename = Path(filename).name or "meeting.txt"
        document_metadata = {
            "size": len(text.encode("utf-8")),
            "characters": len(text),
            "format": "txt",
            "role": "source",
            **(metadata or {}),
        }
        document = current_store.add_document(
            name=filename,
            mime_type="text/plain",
            kind="meeting",
            text=text,
            metadata=document_metadata,
        )
        meeting = current_store.create_meeting(
            document["id"],
            {
                "title": (meeting_name or "").strip() or Path(filename).stem,
                "summary": "",
                "participants": [],
                "dates": [],
                "locations": [],
                "topics": [],
                "risks": [],
                "decisions": [],
            },
            project_id,
        )
        return {"meeting": meeting, "todos": [], "analysisStatus": "not_generated"}

    async def process_meeting_upload(
        project_id: int, file: UploadFile, meeting_name: str | None = None
    ) -> dict[str, Any]:
        if not current_store.get_project(project_id):
            raise HTTPException(404, "项目不存在")
        filename = file.filename or "meeting.txt"
        if not filename.lower().endswith(".txt") and not (file.content_type or "").startswith("text/"):
            raise HTTPException(400, "请选择 TXT 文件")
        data = await file.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, "文件过大")
        text = decode_text(data).strip()
        if not text:
            raise HTTPException(422, "会议文件内容为空")
        return process_meeting_text(
            project_id,
            text,
            filename,
            meeting_name,
            {"size": len(data)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        detail = error.errors()[0].get("msg", "请求参数无效") if error.errors() else "请求参数无效"
        classified = AgentError(
            detail,
            code="request_validation_failed",
            category="validation",
            status_code=422,
            stage="request",
        )
        return JSONResponse(
            {
                "error": detail,
                "errorDetail": classified.payload(),
                "execution": {"status": "failed", "stage": classified.stage},
            },
            status_code=422,
        )

    @app.exception_handler(AgentError)
    async def agent_error(_: Request, error: AgentError) -> JSONResponse:
        return JSONResponse(
            {
                "error": error.message,
                "errorDetail": error.payload(),
                "execution": {
                    "status": "failed",
                    "stage": error.stage,
                    "retryable": error.retryable,
                },
            },
            status_code=error.status_code,
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> JSONResponse:
        category = "provider" if error.status_code >= 500 else "validation"
        classified = AgentError(
            str(error.detail),
            code=f"http_{error.status_code}",
            category=category,
            status_code=error.status_code,
            retryable=error.status_code >= 500,
            stage="request" if error.status_code < 500 else "execution",
        )
        return JSONResponse(
            {
                "error": str(error.detail),
                "errorDetail": classified.payload(),
                "execution": {
                    "status": "failed",
                    "stage": classified.stage,
                    "retryable": classified.retryable,
                },
            },
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, error: Exception) -> JSONResponse:
        classified = AgentError(
            "服务器内部错误",
            code="internal_error",
            category="internal",
            status_code=500,
            retryable=True,
            stage="execution",
            details={"exceptionType": type(error).__name__},
        )
        return JSONResponse(
            {
                "error": classified.message,
                "errorDetail": classified.payload(),
                "execution": {"status": "failed", "stage": "execution", "retryable": True},
            },
            status_code=500,
        )

    def bearer_token(request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
        return request.cookies.get("memora_session", "").strip()

    def user_payload(user: dict[str, Any]) -> dict[str, Any]:
        result = public_user(user)
        result["permissions"] = (
            ["project.use", "system.manage", "users.manage"]
            if user["role"] == "admin"
            else ["project.use"]
        )
        return result

    def create_login_session(
        user: dict[str, Any], response: Response, *, is_new_user: bool = False
    ) -> dict[str, Any]:
        token = generate_session_token()
        if user["role"] == "admin":
            current_store.claim_legacy_resources(int(user["id"]))
        expires_at = datetime.now(UTC) + timedelta(days=config.auth.session_days)
        current_store.create_auth_session(
            uuid4().hex, user["id"], hash_session_token(token), expires_at
        )
        response.set_cookie(
            "memora_session",
            token,
            max_age=config.auth.session_days * 24 * 60 * 60,
            httponly=True,
            secure=config.auth.cookie_secure,
            samesite="lax",
        )
        return {
            "authEnabled": True,
            "token": token,
            "tokenType": "Bearer",
            "expiresAt": expires_at.isoformat(),
            "isNewUser": is_new_user,
            "user": user_payload(user),
        }

    def active_user_id() -> int | None:
        user = request_user.get()
        return int(user["id"]) if user else None

    def public_member(member: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": member["id"],
            "phone": member["phone"],
            "displayName": member.get("display_name") or member["phone"],
            "status": member["status"],
            "role": member["role"],
            "createdAt": member.get("created_at"),
        }

    def verify_sms_code_or_raise(phone: str, code: str) -> None:
        verification = current_store.verify_sms_code(
            phone,
            hash_code(auth_secret, phone, code),
            config.auth.code_max_attempts,
        )
        messages = {
            "missing": "请先获取验证码",
            "expired": "验证码已过期，请重新获取",
            "locked": "验证码错误次数过多，请重新获取",
            "invalid": "验证码错误",
        }
        if verification != "valid":
            raise HTTPException(401, messages.get(verification, "验证码无效"))

    @app.post("/api/auth/register", status_code=201)
    def register_account(body: AccountRegisterInput, response: Response) -> dict[str, Any]:
        if not use_auth:
            raise HTTPException(409, "当前未启用用户认证")
        try:
            username = normalize_username(body.username)
            password_hash = hash_password(body.password)
            phone = normalize_phone(body.phone) if body.phone and body.phone.strip() else None
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if phone:
            if not body.code:
                raise HTTPException(422, "绑定手机号时请输入短信验证码")
            verify_sms_code_or_raise(phone, body.code)
        try:
            user = current_store.create_user_for_registration(username, password_hash, phone)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return create_login_session(user, response, is_new_user=True)

    @app.post("/api/auth/password/login")
    def login_with_password(body: PasswordLoginInput, response: Response) -> dict[str, Any]:
        if not use_auth:
            return {
                "authEnabled": False,
                "token": "",
                "user": {
                    "id": 0,
                    "phone": "",
                    "username": None,
                    "hasPassword": False,
                    "displayName": "本地用户",
                    "role": "admin",
                    "status": "active",
                    "permissions": ["project.use", "system.manage", "users.manage"],
                },
            }
        account = body.account.strip().lower()
        try:
            account = normalize_phone(body.account)
        except ValueError:
            pass
        user = current_store.get_user_by_account(account)
        password_hash = str((user or {}).get("password_hash") or "")
        if not password_hash or not verify_password(body.password, password_hash):
            raise HTTPException(401, "账号或密码错误")
        if user and user["status"] != "active":
            raise HTTPException(403, "该用户已被停用")
        updated = current_store.record_user_login(int(user["id"])) if user else None
        if not updated:
            raise HTTPException(401, "账号或密码错误")
        return create_login_session(updated, response)

    @app.post("/api/auth/sms/send")
    async def send_login_code(body: SmsCodeInput, request: Request) -> dict[str, Any]:
        if not use_auth:
            return {"ok": True, "authEnabled": False, "expiresIn": config.auth.code_ttl_seconds}
        try:
            phone = normalize_phone(body.phone)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        remaining = current_store.sms_cooldown_remaining(phone, config.auth.code_cooldown_seconds)
        if remaining:
            raise HTTPException(
                429,
                f"验证码发送过于频繁，请在 {remaining} 秒后重试",
                headers={"Retry-After": str(remaining)},
            )
        code = generate_code()
        try:
            await deliver_sms(config.auth, phone, code)
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error
        expires_at = datetime.now(UTC) + timedelta(seconds=config.auth.code_ttl_seconds)
        current_store.create_sms_code(
            phone,
            hash_code(auth_secret, phone, code),
            request.client.host if request.client else "",
            expires_at,
        )
        result: dict[str, Any] = {
            "ok": True,
            "expiresIn": config.auth.code_ttl_seconds,
            "retryAfter": config.auth.code_cooldown_seconds,
        }
        if config.auth.debug_code:
            result["debugCode"] = code
        return result

    @app.post("/api/auth/sms/login")
    def login_with_sms(body: SmsLoginInput, response: Response) -> dict[str, Any]:
        if not use_auth:
            return {
                "authEnabled": False,
                "token": "",
                "user": {
                    "id": 0,
                    "phone": "",
                    "displayName": "本地用户",
                    "role": "admin",
                    "status": "active",
                    "permissions": ["project.use", "system.manage", "users.manage"],
                },
            }
        try:
            phone = normalize_phone(body.phone)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        verify_sms_code_or_raise(phone, body.code)
        user, created = current_store.get_or_create_user_for_login(phone)
        if user["status"] != "active":
            raise HTTPException(403, "该用户已被停用")
        return create_login_session(user, response, is_new_user=created)

    @app.get("/api/auth/me")
    def get_current_user(request: Request) -> dict[str, Any]:
        if not use_auth:
            return {
                "authEnabled": False,
                "user": {
                    "id": 0,
                    "phone": "",
                    "displayName": "本地用户",
                    "role": "admin",
                    "status": "active",
                    "permissions": ["project.use", "system.manage", "users.manage"],
                },
            }
        token = bearer_token(request)
        user = current_store.get_user_by_session(hash_session_token(token)) if token else None
        if not user:
            raise HTTPException(401, "登录状态已失效，请重新登录")
        if user["role"] == "admin":
            current_store.claim_legacy_resources(int(user["id"]))
        return {
            "authEnabled": True,
            "user": user_payload(user),
        }

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request) -> Response:
        token = bearer_token(request)
        if token:
            current_store.revoke_auth_session(hash_session_token(token))
        response = Response(status_code=204)
        response.delete_cookie("memora_session", httponly=True, samesite="lax")
        return response

    @app.put("/api/account/credentials")
    def update_account_credentials(
        body: AccountCredentialsInput, request: Request
    ) -> dict[str, Any]:
        user = request_user.get()
        if not user:
            raise HTTPException(401, "请先登录")
        existing_password_hash = str(user.get("password_hash") or "")
        if existing_password_hash and not verify_password(
            body.current_password or "", existing_password_hash
        ):
            raise HTTPException(401, "当前密码错误")
        try:
            username = normalize_username(body.username)
            password_hash = hash_password(body.password)
            updated = current_store.set_user_credentials(
                int(user["id"]), username, password_hash
            )
        except ValueError as error:
            raise HTTPException(409 if "已被使用" in str(error) else 422, str(error)) from error
        if not updated:
            raise HTTPException(404, "用户不存在")
        token = bearer_token(request)
        current_store.revoke_other_auth_sessions(
            int(user["id"]), hash_session_token(token) if token else ""
        )
        return user_payload(updated)

    @app.put("/api/account/phone")
    def bind_account_phone(body: PhoneBindingInput) -> dict[str, Any]:
        user = request_user.get()
        if not user:
            raise HTTPException(401, "请先登录")
        try:
            phone = normalize_phone(body.phone)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        verify_sms_code_or_raise(phone, body.code)
        try:
            updated = current_store.set_user_phone(int(user["id"]), phone)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if not updated:
            raise HTTPException(404, "用户不存在")
        return user_payload(updated)

    @app.get("/api/admin/users")
    def list_users() -> list[dict[str, Any]]:
        return [user_payload(user) for user in current_store.list_users()]

    @app.patch("/api/admin/users/{user_id}/role")
    def change_user_role(user_id: int, body: UserRoleInput) -> dict[str, Any]:
        try:
            user = current_store.update_user_role(user_id, body.role)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if not user:
            raise HTTPException(404, "用户不存在")
        return user_payload(user)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        smtp, _ = resolve_smtp_settings(current_store, target_dir)
        email_configured = agentmail_configured() or smtp_configured(smtp)
        return {
            "ok": True,
            "name": config.app_name,
            "capabilities": {
                "llm": llm_enabled(),
                "smtp": email_configured,
                "agentMail": agentmail_configured(),
                "webSearch": True,
                "pdf": True,
                "ppt": True,
                "embedding": embedding_enabled(),
                "fullTextSearch": current_store.fts_enabled,
                "ocr": ocr_configured(),
            },
            "providers": provider_health(),
        }

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": config.app_name, "service": "backend", "docs": "/api/docs"}

    @app.post("/api/index/rebuild")
    async def rebuild_search_index() -> dict[str, Any]:
        fts_enabled = current_store.rebuild_full_text_index()
        indexed_documents = 0
        indexed_chunks = 0
        indexed_memories = 0
        if embedding_enabled():
            for document in current_store.documents_needing_embeddings():
                chunks = document["chunks"]
                vectors = await embed_texts(
                    [f"{item.get('heading', '')}\n{item['content']}" for item in chunks]
                )
                if len(vectors) != len(chunks):
                    continue
                current_store.set_chunk_embeddings(document["document_id"], vectors)
                indexed_documents += 1
                indexed_chunks += len(chunks)
            memories = current_store.memories_needing_embeddings()
            memory_vectors = await embed_texts(
                [f"{item.get('subject', '')}\n{item['content']}" for item in memories]
            )
            if len(memory_vectors) == len(memories):
                for memory, vector in zip(memories, memory_vectors, strict=True):
                    current_store.update_memory(memory["id"], {"embedding": vector})
                indexed_memories = len(memories)
        return {
            "ok": True,
            "ftsEnabled": fts_enabled,
            "embeddingEnabled": embedding_enabled(),
            "indexedDocuments": indexed_documents,
            "indexedChunks": indexed_chunks,
            "indexedMemories": indexed_memories,
        }

    @app.get("/api/settings/email")
    def get_email_settings() -> dict[str, Any]:
        return email_settings_payload()

    @app.put("/api/settings/email")
    def update_email_settings(body: EmailSettingsInput) -> dict[str, Any]:
        settings = smtp_from_input(body)
        validate_smtp_settings(settings)
        save_smtp_settings(current_store, target_dir, settings)
        return email_settings_payload()

    @app.post("/api/settings/email/test")
    async def test_email_settings(body: EmailSettingsInput) -> dict[str, bool]:
        settings = smtp_from_input(body)
        validate_smtp_settings(settings)
        try:
            await test_smtp_connection(settings)
        except RuntimeError as error:
            raise HTTPException(422, str(error)) from error
        return {"ok": True}

    @app.delete("/api/settings/email", status_code=204)
    def clear_email_settings() -> Response:
        delete_smtp_settings(current_store)
        return Response(status_code=204)

    @app.get("/api/integrations/tencent-meeting/status")
    def get_tencent_meeting_status() -> dict[str, Any]:
        return {
            "configured": meeting_connector.configured,
            "provider": "official_mcp",
            "skillVersion": config.tencent_meeting.skill_version,
            "tokenUrl": "https://meeting.tencent.com/ai-skill/",
        }

    @app.get("/api/integrations/tencent-meeting/records")
    async def list_tencent_meeting_records(days: int = 30) -> dict[str, Any]:
        if days < 1 or days > 31:
            raise HTTPException(422, "查询天数必须在 1 到 31 之间")
        try:
            records = await meeting_connector.list_records(days)
        except ProviderError as error:
            raise HTTPException(error.status_code or 502, str(error)) from error
        return {"records": records, "days": days}

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return current_store.list_projects(user_id=active_user_id())

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectInput) -> dict[str, Any]:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "项目名称不能为空")
        user_id = active_user_id()
        return current_store.create_project(
            name,
            body.description.strip(),
            created_by=user_id,
        )

    @app.get("/api/projects/{project_id}/members")
    def list_project_members(project_id: int) -> list[dict[str, Any]]:
        return [public_member(item) for item in current_store.list_project_members(project_id)]

    @app.post("/api/projects/{project_id}/members", status_code=201)
    def add_project_member(project_id: int, body: ProjectMemberInput) -> dict[str, Any]:
        try:
            phone = normalize_phone(body.phone)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        project = current_store.get_project(project_id)
        if not project:
            raise HTTPException(404, "项目不存在")
        user = next(
            (item for item in current_store.list_users() if item.get("phone") == phone and item.get("status") == "active"),
            None,
        )
        if not user:
            raise HTTPException(404, "该手机号尚未登录，无法加入项目")
        member = current_store.set_project_member(project_id, int(user["id"]), body.role)
        return public_member(member or user)

    @app.delete("/api/projects/{project_id}/members/{user_id}", status_code=204)
    def remove_project_member(project_id: int, user_id: int) -> Response:
        if not current_store.remove_project_member(project_id, user_id):
            raise HTTPException(409, "不能移除项目所有者，或成员不存在")
        return Response(status_code=204)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int) -> dict[str, Any]:
        project = current_store.get_project(project_id)
        if not project:
            raise HTTPException(404, "项目不存在")
        user_id = active_user_id()
        if user_id is not None:
            project["access_role"] = current_store.project_role(project_id, user_id)
        return {
            "project": project,
            "conversations": current_store.list_project_conversations(project_id),
            "documents": current_store.list_project_documents(project_id),
            "meetings": current_store.list_meetings(project_id),
            "todos": current_store.list_todos(project_id),
            "memories": [_public_memory(item) for item in current_store.list_memories(project_id=project_id)],
        }

    @app.patch("/api/projects/{project_id}")
    def rename_project(project_id: int, body: ProjectRenameInput) -> dict[str, Any]:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "项目名称不能为空")
        project = current_store.rename_project(project_id, name)
        if not project:
            raise HTTPException(404, "项目不存在")
        return project

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: int) -> Response:
        if not current_store.delete_project(project_id):
            raise HTTPException(404, "项目不存在")
        return Response(status_code=204)

    @app.post("/api/projects/{project_id}/meetings", status_code=201)
    async def upload_project_meeting(
        project_id: int,
        file: Annotated[UploadFile, File()],
        name: Annotated[str | None, Form(max_length=120)] = None,
    ) -> dict[str, Any]:
        return await process_meeting_upload(project_id, file, name)

    @app.post(
        "/api/projects/{project_id}/integrations/tencent-meeting/import",
        status_code=201,
    )
    async def import_tencent_meeting(project_id: int, body: TencentMeetingImportInput) -> dict[str, Any]:
        if not current_store.get_project(project_id):
            raise HTTPException(404, "项目不存在")
        for meeting in current_store.list_meetings(project_id):
            source = current_store.get_document(meeting["document_id"])
            source_metadata = (source or {}).get("metadata") or {}
            if (
                source_metadata.get("source") == "tencent_meeting"
                and source_metadata.get("recordFileId") == body.record_file_id
            ):
                return {
                    "meeting": meeting,
                    "todos": [
                        item
                        for item in current_store.list_todos(project_id)
                        if item["meeting_id"] == meeting["id"]
                    ],
                    "analysisStatus": "not_generated",
                    "idempotent": True,
                }
        try:
            transcript = await meeting_connector.get_transcript(body.record_file_id, body.meeting_id)
        except ProviderError as error:
            raise HTTPException(error.status_code or 502, str(error)) from error
        title = (body.title or "").strip() or "腾讯会议记录"
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" ._")[:100]
        filename = f"{safe_title or '腾讯会议记录'}_逐字稿.txt"
        result = process_meeting_text(
            project_id,
            transcript,
            filename,
            title,
            {
                "source": "tencent_meeting",
                "recordFileId": body.record_file_id,
                "meetingRecordId": body.meeting_record_id,
                "remoteMeetingId": body.meeting_id,
            },
        )
        result["idempotent"] = False
        return result

    @app.post("/api/projects/{project_id}/documents", status_code=201)
    async def upload_project_document(project_id: int, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        if not current_store.get_project(project_id):
            raise HTTPException(404, "项目不存在")
        return await process_knowledge_upload(file, project_id=project_id)

    @app.post("/api/projects/{project_id}/conversations", status_code=201)
    def create_project_conversation(project_id: int, body: ConversationInput) -> dict[str, Any]:
        if not current_store.get_project(project_id):
            raise HTTPException(404, "项目不存在")
        user_id = active_user_id()
        return current_store.create_conversation(
            body.title[:80],
            project_id=project_id,
            created_by=user_id,
        )

    @app.delete("/api/projects/{project_id}/conversations/{conversation_id}", status_code=204)
    def delete_project_conversation(project_id: int, conversation_id: int) -> Response:
        conversation = current_store.get_conversation(conversation_id)
        if not conversation or conversation.get("project_id") != project_id:
            raise HTTPException(404, "项目对话不存在")
        current_store.delete_conversation(conversation_id)
        return Response(status_code=204)

    @app.delete("/api/projects/{project_id}/documents/{document_id}", status_code=204)
    def delete_project_document(project_id: int, document_id: int) -> Response:
        if not current_store.delete_project_document(project_id, document_id):
            raise HTTPException(404, "背景知识文件不存在或不属于当前项目")
        return Response(status_code=204)

    @app.get("/api/documents/{document_id}/preview")
    def preview_document(document_id: int) -> dict[str, Any]:
        document = current_store.get_document(document_id)
        if not document:
            raise HTTPException(404, "文件不存在")
        content = str(document.pop("text_content", "") or "")
        limit = 500_000
        return {
            **document,
            "content": content[:limit],
            "truncated": len(content) > limit,
        }

    @app.patch("/api/documents/{document_id}/content")
    async def update_document_content(document_id: int, body: DocumentContentInput) -> dict[str, Any]:
        document = current_store.get_document(document_id)
        if not document:
            raise HTTPException(404, "文件不存在")
        content = body.content
        if not content.strip():
            raise HTTPException(422, "文件内容不能为空")
        chunks = chunk_pages([{"page_number": 1, "text": content}])
        updated = current_store.update_document_content(document_id, content, chunks)
        if not updated:
            raise HTTPException(404, "文件不存在")
        vectors = await embed_texts([f"{item.get('heading', '')}\n{item['content']}" for item in chunks])
        if len(vectors) == len(chunks):
            current_store.set_chunk_embeddings(document_id, vectors)
        updated.pop("text_content", None)
        return {**updated, "content": content, "truncated": False}

    @app.get("/api/conversations")
    def list_conversations() -> list[dict[str, Any]]:
        return current_store.list_conversations(user_id=active_user_id())

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: ConversationInput) -> dict[str, Any]:
        return current_store.create_conversation(body.title[:80], created_by=active_user_id())

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: int) -> dict[str, Any]:
        conversation = current_store.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(404, "会话不存在")
        return {
            "conversation": conversation,
            "messages": current_store.list_messages(conversation_id),
            "documents": current_store.list_project_documents(conversation["project_id"])
            if conversation.get("project_id") is not None
            else current_store.list_documents(conversation_id),
        }

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: int) -> Response:
        if not current_store.delete_conversation(conversation_id):
            raise HTTPException(404, "会话不存在")
        return Response(status_code=204)

    @app.post("/api/conversations/{conversation_id}/documents", status_code=201)
    async def upload_document(conversation_id: int, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        if not current_store.get_conversation(conversation_id):
            raise HTTPException(404, "会话不存在")
        return await process_knowledge_upload(file, conversation_id=conversation_id)

    @app.delete("/api/conversations/{conversation_id}/documents/{document_id}", status_code=204)
    def delete_document(conversation_id: int, document_id: int) -> Response:
        if not current_store.delete_document(conversation_id, document_id):
            raise HTTPException(404, "知识文件不存在或不属于当前对话")
        return Response(status_code=204)

    @app.post("/api/meetings", status_code=201)
    async def upload_meeting(
        file: Annotated[UploadFile, File()],
        name: Annotated[str | None, Form(max_length=120)] = None,
    ) -> dict[str, Any]:
        user_id = active_user_id()
        project = current_store.get_or_create_default_project(user_id=user_id)
        return await process_meeting_upload(project["id"], file, name)

    @app.get("/api/meetings")
    def list_meetings() -> list[dict[str, Any]]:
        return current_store.list_meetings(user_id=active_user_id())

    @app.get("/api/meetings/{meeting_id}")
    def get_meeting(meeting_id: int) -> dict[str, Any]:
        meeting = current_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(404, "会议不存在")
        return {
            "meeting": meeting,
            "todos": [item for item in current_store.list_todos() if item["meeting_id"] == meeting_id],
        }

    @app.patch("/api/meetings/{meeting_id}")
    def rename_meeting(meeting_id: int, body: MeetingRenameInput) -> dict[str, Any]:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "会议名称不能为空")
        meeting = current_store.rename_meeting(meeting_id, name)
        if not meeting:
            raise HTTPException(404, "会议不存在")
        return meeting

    @app.delete("/api/meetings/{meeting_id}", status_code=204)
    def delete_meeting(meeting_id: int) -> Response:
        if not current_store.delete_meeting(meeting_id):
            raise HTTPException(404, "会议不存在")
        return Response(status_code=204)

    @app.patch("/api/meetings/{meeting_id}/files/{document_id}")
    def rename_meeting_file(meeting_id: int, document_id: int, body: ArtifactRenameInput) -> dict[str, Any]:
        name = Path(body.name.strip()).name
        if not name or name in {".", ".."}:
            raise HTTPException(400, "文件名不能为空")
        document = current_store.rename_meeting_document(meeting_id, document_id, name)
        if not document:
            raise HTTPException(404, "文件不存在或不属于当前会议")
        document.pop("text_content", None)
        return document

    @app.delete("/api/meetings/{meeting_id}/files/{document_id}", status_code=204)
    def delete_meeting_file(meeting_id: int, document_id: int) -> Response:
        meeting = current_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(404, "会议不存在")
        if meeting["document_id"] == document_id:
            raise HTTPException(400, "会议原文不能单独删除，请删除整个会议")
        if not current_store.delete_meeting_document(meeting_id, document_id):
            raise HTTPException(404, "文件不存在或不属于当前会议")
        return Response(status_code=204)

    @app.post("/api/meetings/{meeting_id}/detail-draft")
    async def generate_meeting_detail_draft(meeting_id: int, body: MeetingDraftInput) -> dict[str, Any]:
        meeting = current_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(404, "会议不存在")
        source = current_store.get_document(meeting["document_id"])
        if not source or not str(source.get("text_content") or "").strip():
            raise HTTPException(422, "会议原文不存在或内容为空")
        routed = route_intent(body.instruction)
        decision = IntentDecision(
            body.content_type,
            routed.web_search,
            "explicit_artifact_regeneration",
        )
        support = await build_project_support_context(
            store=current_store,
            project_id=meeting["project_id"],
            query=body.instruction or meeting["title"],
            use_web_search=routed.web_search,
        )
        context = AgentContext(
            history=[],
            documents=[
                {
                    "document_id": item["id"],
                    "name": item["name"],
                    "page_number": None,
                    "content": item["content"],
                }
                for item in support["documents"]
            ],
            memories=support["memories"],
            web_results=support["web_results"],
        )
        output = await execute_workflow(
            decision=decision,
            query=body.instruction,
            context=context,
            data_dir=target_dir,
            meeting=MeetingWorkflowInput(
                meeting_id=meeting_id,
                source_name=source["name"],
                source_text=str(source["text_content"]),
                background_documents=support["documents"],
            ),
        )
        draft = output.artifact_draft or {}
        draft.update(
            {
                "routing": {
                    "intent": body.content_type,
                    "reason": decision.reason,
                    "webSearch": decision.web_search,
                },
            }
        )
        return draft

    @app.post("/api/meetings/{meeting_id}/details", status_code=201)
    async def save_meeting_detail(meeting_id: int, body: MeetingDetailSaveInput) -> dict[str, Any]:
        meeting = current_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(404, "会议不存在")
        required = {
            "title",
            "summary",
            "participants",
            "dates",
            "locations",
            "topics",
            "risks",
            "decisions",
            "todos",
        }
        if not required.issubset(body.analysis):
            raise HTTPException(422, "会议详情草稿数据不完整，请重新生成")
        name = Path(body.name.strip()).name
        if not name.lower().endswith((".md", ".markdown")):
            name += ".md"
        idempotency_seed = "|".join(
            [
                body.idempotency_key or "legacy",
                body.content_type,
                name,
                body.content,
            ]
        )
        idempotency_key = hashlib.sha256(idempotency_seed.encode("utf-8")).hexdigest()
        existing = current_store.get_meeting_document_by_idempotency_key(meeting_id, idempotency_key)
        if existing:
            existing.pop("text_content", None)
            return {
                "file": existing,
                "meeting": meeting,
                "todos": [
                    item
                    for item in current_store.list_todos(meeting["project_id"])
                    if item["meeting_id"] == meeting_id
                ],
                "idempotent": True,
            }
        if body.content_type == "meeting_detail":
            current_store.update_meeting_analysis(meeting_id, body.analysis)
            for todo in body.analysis["todos"]:
                current_store.add_todo(meeting_id, todo)
            extracted_memories = meeting_memories(body.analysis, meeting_id)
            vectors = await embed_texts(
                [f"{item.get('subject', '')}\n{item['content']}" for item in extracted_memories]
            )
            for index, memory in enumerate(extracted_memories):
                if len(vectors) == len(extracted_memories):
                    memory["embedding"] = vectors[index]
                current_store.add_memory(memory, project_id=meeting["project_id"])
        todos = [
            item
            for item in current_store.list_todos(meeting["project_id"])
            if item["meeting_id"] == meeting_id
        ]
        detail_file = current_store.add_document(
            project_id=meeting["project_id"],
            meeting_id=meeting_id,
            idempotency_key=idempotency_key,
            name=name,
            mime_type="text/markdown",
            kind="meeting",
            text=body.content,
            metadata={
                "format": "md",
                "role": body.content_type,
                "artifact": True,
                "characters": len(body.content),
                "size": len(body.content.encode("utf-8")),
                "draftKey": body.idempotency_key,
            },
        )
        detail_file.pop("text_content", None)
        return {
            "file": detail_file,
            "meeting": current_store.get_meeting(meeting_id),
            "todos": todos,
            "idempotent": False,
        }

    @app.patch("/api/meetings/{meeting_id}/artifacts/{document_id}")
    def rename_meeting_artifact(
        meeting_id: int, document_id: int, body: ArtifactRenameInput
    ) -> dict[str, Any]:
        meeting = current_store.get_meeting(meeting_id)
        if not meeting or meeting["document_id"] == document_id:
            raise HTTPException(404, "Artifact 不存在或不属于当前会议")
        name = Path(body.name.strip()).name
        if not name.lower().endswith((".md", ".markdown")):
            name += ".md"
        artifact = current_store.rename_meeting_document(meeting_id, document_id, name)
        if not artifact:
            raise HTTPException(404, "Artifact 不存在或不属于当前会议")
        artifact.pop("text_content", None)
        return artifact

    @app.get("/api/meetings/{meeting_id}/artifacts/{document_id}/email-draft")
    def meeting_artifact_email_draft(meeting_id: int, document_id: int) -> dict[str, str]:
        document = current_store.get_document(document_id)
        if not document or document.get("meeting_id") != meeting_id:
            raise HTTPException(404, "Artifact 不存在或不属于当前会议")
        return _artifact_email_draft(document)

    @app.post("/api/meetings/{meeting_id}/artifacts/{document_id}/send-email")
    async def send_meeting_artifact_email(
        meeting_id: int, document_id: int, body: EmailInput
    ) -> dict[str, Any]:
        document = current_store.get_document(document_id)
        if not document or document.get("meeting_id") != meeting_id:
            raise HTTPException(404, "Artifact 不存在或不属于当前会议")
        email_pattern = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+(?:\s*,\s*[^\s@]+@[^\s@]+\.[^\s@]+)*$")
        if not email_pattern.match(body.to.strip()):
            raise HTTPException(400, "请输入有效的收件人邮箱；多个地址使用英文逗号分隔")
        draft = _artifact_email_draft(document)
        delivery_result = await send_email_once(
            source_type="artifact", source_id=document_id, body=body, draft=draft
        )
        return {"documentId": document_id, **delivery_result}

    @app.get("/api/todos")
    def list_todos() -> list[dict[str, Any]]:
        return current_store.list_todos(user_id=active_user_id())

    @app.patch("/api/todos/{todo_id}")
    def update_todo(todo_id: int, body: TodoInput) -> dict[str, Any]:
        if not current_store.get_todo(todo_id):
            raise HTTPException(404, "待办不存在")
        fields = {}
        if body.status in {"open", "done"}:
            fields["status"] = body.status
        if body.owner is not None:
            fields["owner"] = body.owner
        if body.dueDate is not None:
            fields["due_date"] = body.dueDate
        return current_store.update_todo(todo_id, fields) or {}

    @app.get("/api/todos/{todo_id}/email-draft")
    def email_draft(todo_id: int) -> dict[str, str]:
        todo = next((item for item in current_store.list_todos() if item["id"] == todo_id), None)
        if not todo:
            raise HTTPException(404, "待办不存在")
        return create_todo_email(todo)

    @app.post("/api/todos/{todo_id}/send-email")
    async def send_email(todo_id: int, body: EmailInput) -> dict[str, Any]:
        todo = next((item for item in current_store.list_todos() if item["id"] == todo_id), None)
        if not todo:
            raise HTTPException(404, "待办不存在")
        email_pattern = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+(?:\s*,\s*[^\s@]+@[^\s@]+\.[^\s@]+)*$")
        if not email_pattern.match(body.to.strip()):
            raise HTTPException(400, "请输入有效的收件人邮箱；多个地址使用英文逗号分隔")
        draft = create_todo_email(todo)
        delivery_result = await send_email_once(source_type="todo", source_id=todo_id, body=body, draft=draft)
        current_store.update_todo(todo_id, {"email_status": "sent"})
        return delivery_result

    @app.get("/api/memories")
    def list_memories(
        scope: Literal["all", "ordinary", "project"] = "all",
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        user_id = active_user_id()
        if scope == "project":
            if project_id is None:
                raise HTTPException(422, "查询项目记忆时必须提供 project_id")
            if not current_store.get_project(project_id):
                raise HTTPException(404, "项目不存在")
            if (
                user_id is not None
                and not current_store.project_role(project_id, user_id)
            ):
                raise HTTPException(403, "无权访问该项目")
            return [_public_memory(item) for item in current_store.list_memories(project_id=project_id)]
        return [
            _public_memory(item)
            for item in current_store.list_memories(
                ordinary_only=scope == "ordinary",
                user_id=user_id,
            )
        ]

    @app.post("/api/memories", status_code=201)
    async def create_memory(body: MemoryCreateInput) -> dict[str, Any]:
        user_id = active_user_id()
        if body.project_id is not None and not current_store.get_project(body.project_id):
            raise HTTPException(404, "项目不存在")
        if (
            body.project_id is not None
            and user_id is not None
            and not sufficient_project_role(
                current_store.project_role(body.project_id, user_id), "editor"
            )
        ):
            raise HTTPException(403, "无权修改该项目")
        subject = body.subject.strip()
        content = body.content.strip()
        if not content:
            raise HTTPException(422, "记忆内容不能为空")
        if any(
            value and not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value)
            for value in (body.valid_from, body.valid_until)
        ):
            raise HTTPException(422, "记忆有效期必须使用 YYYY-MM-DD 格式")
        memory = {
            "type": body.type,
            "subject": subject,
            "content": content,
            "source_type": "manual",
            "source_id": None,
            "importance": body.importance,
            "pinned": body.pinned,
            "confidence": body.confidence,
            "valid_from": body.valid_from,
            "valid_until": body.valid_until,
            "sensitivity": body.sensitivity,
        }
        vectors = await embed_texts([f"{subject}\n{content}"])
        if vectors:
            memory["embedding"] = vectors[0]
        return _public_memory(
            current_store.add_memory(
                memory,
                project_id=body.project_id,
                created_by=user_id,
            )
        )

    @app.get("/api/memories/{memory_id}/versions")
    def list_memory_versions(memory_id: int) -> list[dict[str, Any]]:
        versions = current_store.list_memory_versions(memory_id)
        if not versions:
            raise HTTPException(404, "记忆不存在")
        return [_public_memory(item) for item in versions]

    @app.patch("/api/memories/{memory_id}")
    async def update_memory(memory_id: int, body: MemoryUpdateInput) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        if any(
            fields.get(key) and not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(fields[key]))
            for key in ("valid_from", "valid_until")
        ):
            raise HTTPException(422, "记忆有效期必须使用 YYYY-MM-DD 格式")
        if "subject" in fields:
            fields["subject"] = str(fields["subject"] or "").strip()
        if "content" in fields:
            fields["content"] = str(fields["content"] or "").strip()
            if not fields["content"]:
                raise HTTPException(422, "记忆内容不能为空")
        if "content" in fields or "subject" in fields:
            current = current_store.get_memory(memory_id)
            if current:
                vectors = await embed_texts(
                    [
                        f"{fields.get('subject', current.get('subject', ''))}\n"
                        f"{fields.get('content', current.get('content', ''))}"
                    ]
                )
                if vectors:
                    fields["embedding"] = vectors[0]
        try:
            memory = current_store.update_memory(memory_id, fields)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if not memory:
            raise HTTPException(404, "记忆不存在")
        return _public_memory(memory)

    @app.delete("/api/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: int) -> Response:
        if not current_store.delete_memory(memory_id):
            raise HTTPException(404, "记忆不存在")
        return Response(status_code=204)

    async def process_message(
        conversation_id: int,
        body: MessageInput,
        trace_id: str,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        conversation = current_store.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(404, "会话不存在")
        project_id = conversation.get("project_id")
        conversation_user_id = conversation.get("created_by")
        content = body.content.strip()
        if not content:
            raise HTTPException(400, "消息不能为空")
        decision = route_intent(content)
        current_store.update_trace_context(
            trace_id,
            conversation_id=conversation_id,
            intent=decision.name,
            metadata={"projectId": project_id, "webSearch": decision.web_search},
        )
        emit_trace_event(
            stage="routing",
            event="intent",
            status="completed",
            metadata={"intent": decision.name, "reason": decision.reason},
        )
        if task_id:
            current_store.update_task_progress(task_id, 15)
        emit_trace_event(stage="context", event="build", status="running")
        try:
            context = await build_context(
                store=current_store,
                conversation_id=conversation_id,
                project_id=project_id,
                query=content,
                document_ids=body.document_ids,
                use_web_search=decision.web_search,
                force_document_fallback=decision.name == "ppt",
                user_id=conversation_user_id,
            )
        except ContextBuildError as error:
            raise AgentError(
                str(error),
                code="invalid_document_context",
                category="context",
                status_code=400,
                stage="context",
            ) from error
        emit_trace_event(
            stage="context",
            event="build",
            status="completed",
            metadata=context.provenance(),
        )
        if task_id:
            current_store.update_task_progress(task_id, 40)
        meeting_input = (
            meeting_workflow_input(project_id, body.document_ids)
            if decision.name in {"meeting_detail", "email_content"}
            else None
        )
        emit_trace_event(stage="workflow", event=decision.name, status="running")
        try:
            output = await execute_workflow(
                decision=decision,
                query=content,
                context=context,
                data_dir=target_dir,
                meeting=meeting_input,
            )
        except AgentError:
            raise
        except RuntimeError as error:
            raise AgentError(
                str(error),
                code="provider_request_failed",
                category="provider",
                status_code=503,
                retryable=True,
                stage="execution",
            ) from error
        emit_trace_event(stage="workflow", event=decision.name, status="completed")
        if task_id:
            current_store.update_task_progress(task_id, 80)
        sources = context.sources()
        artifact = None
        if output.artifact:
            generated = output.artifact
            emit_trace_event(
                stage="artifact",
                event="generated",
                status="completed",
                metadata={"filePath": generated["file_path"]},
            )
            provenance = context.provenance()
            artifact = current_store.add_artifact(
                conversation_id=conversation_id,
                kind="pptx",
                name=generated["filename"],
                file_path=generated["file_path"],
                metadata={
                    "outline": generated["outline"],
                    "intent": decision.name,
                    "routingReason": decision.reason,
                    **provenance,
                },
                execution_id=trace_id,
            )
        user_message = current_store.add_message(conversation_id, "user", content, execution_id=trace_id)
        message = current_store.add_message(
            conversation_id,
            "assistant",
            output.content,
            sources,
            artifact_id=artifact["id"] if artifact else None,
            execution_id=trace_id,
        )
        emit_trace_event(
            stage="persistence",
            event="messages",
            status="completed",
            metadata={"userMessageId": user_message["id"], "messageId": message["id"]},
        )
        if task_id:
            current_store.update_task_progress(task_id, 95)
        try:
            task_manager.enqueue(
                kind="memory_extract",
                payload={
                    "content": content,
                    "messageId": user_message["id"],
                    "projectId": project_id,
                    "userId": conversation_user_id,
                },
                idempotency_key=f"message:{user_message['id']}",
                max_attempts=3,
            )
        except Exception as error:
            emit_trace_event(
                stage="memory",
                event="enqueue",
                status="failed",
                metadata={"message": str(error)},
            )
        result: dict[str, Any] = {
            "message": message,
            "routing": {
                "intent": decision.name,
                "reason": decision.reason,
                "webSearch": decision.web_search,
            },
            "execution": {
                "id": trace_id,
                "status": "completed",
                "stage": "completed",
                "intent": decision.name,
                "retryable": False,
            },
        }
        if artifact:
            result["artifact"] = _public_artifact(artifact)
        if output.artifact_draft:
            output.artifact_draft["routing"] = {
                "intent": decision.name,
                "reason": decision.reason,
                "webSearch": decision.web_search,
            }
            result["artifactDraft"] = output.artifact_draft
        return result

    async def message_task_handler(payload: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        try:
            return await process_message(
                int(payload["conversationId"]),
                MessageInput.model_validate(payload["message"]),
                current_trace_id() or uuid4().hex,
                str(_["id"]),
            )
        except HTTPException as error:
            raise AgentError(
                str(error.detail),
                code=f"http_{error.status_code}",
                category="validation" if error.status_code < 500 else "provider",
                status_code=error.status_code,
                retryable=error.status_code >= 500,
                stage="request" if error.status_code < 500 else "execution",
            ) from error

    async def memory_task_handler(payload: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        await remember_chat_message(
            str(payload["content"]),
            int(payload["messageId"]),
            int(payload["projectId"]) if payload.get("projectId") is not None else None,
            int(payload["userId"]) if payload.get("userId") is not None else None,
        )
        return {"stored": True, "messageId": int(payload["messageId"])}

    async def message_task_compensator(_: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(task.get("trace_id") or "")
        rollback = current_store.rollback_execution(trace_id)
        trace = current_store.get_trace(trace_id) or {}
        generated_paths = [
            str(event.get("metadata", {}).get("filePath"))
            for event in trace.get("events", [])
            if event.get("metadata", {}).get("filePath")
        ]
        artifact_root = (target_dir / "artifacts").resolve()
        removed_files: list[str] = []
        unsafe_files: list[str] = []
        failed_files: list[str] = []
        for filename in dict.fromkeys([*rollback["filePaths"], *generated_paths]):
            resolved = Path(filename).resolve()
            if not resolved.is_relative_to(artifact_root):
                unsafe_files.append(filename)
                continue
            if not resolved.exists():
                continue
            try:
                resolved.unlink()
                removed_files.append(resolved.name)
            except OSError:
                failed_files.append(resolved.name)
        if failed_files:
            raise RuntimeError(f"Failed to remove generated files: {', '.join(failed_files)}")
        return {
            "removedMessageIds": rollback["messageIds"],
            "removedArtifactIds": rollback["artifactIds"],
            "removedFiles": removed_files,
            "skippedUnsafeFiles": unsafe_files,
        }

    task_manager.register("message", message_task_handler)
    task_manager.register("memory_extract", memory_task_handler)
    task_manager.register_compensator("message", message_task_compensator)

    @app.post("/api/conversations/{conversation_id}/messages", status_code=201)
    async def create_message(conversation_id: int, body: MessageInput) -> dict[str, Any]:
        trace_id = uuid4().hex
        current_store.create_trace(
            trace_id,
            conversation_id=conversation_id,
            metadata={"mode": "synchronous"},
        )
        try:
            with trace_context(trace_id, current_store.add_trace_event):
                result = await process_message(conversation_id, body, trace_id)
        except AgentError as error:
            current_store.finish_trace(trace_id, "failed", error.payload())
            raise
        except Exception as error:
            current_store.finish_trace(
                trace_id,
                "failed",
                {"code": "internal_error", "message": str(error), "retryable": True},
            )
            raise
        current_store.finish_trace(trace_id, "completed")
        return result

    @app.post("/api/conversations/{conversation_id}/message-tasks", status_code=202)
    async def create_message_task(conversation_id: int, body: MessageInput) -> dict[str, Any]:
        conversation = current_store.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(404, "Conversation does not exist")
        user_id = active_user_id()
        idempotency_key = (body.idempotency_key or "").strip() or uuid4().hex
        task, created = task_manager.enqueue(
            kind="message",
            payload={
                "conversationId": conversation_id,
                "message": body.model_dump(by_alias=True),
                "userId": user_id,
            },
            idempotency_key=f"conversation:{conversation_id}:{idempotency_key}",
            max_attempts=3,
        )
        if not created and task.get("status") == "queued":
            task_manager.schedule(str(task["id"]))
        return {**_public_task(task), "idempotent": not created}

    @app.get("/api/tasks")
    def list_tasks(
        limit: int = 100,
        status: Literal["queued", "running", "completed", "failed", "cancelled", "dead_letter"] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            _public_task(item) for item in current_store.list_tasks(max(1, min(limit, 200)), status=status)
        ]

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        task = current_store.get_task(task_id)
        if not task:
            raise HTTPException(404, "Task does not exist")
        if task.get("status") == "queued":
            task_manager.schedule(task_id)
        return _public_task(task)

    @app.post("/api/tasks/{task_id}/retry", status_code=202)
    def retry_task(task_id: str) -> dict[str, Any]:
        existing = current_store.get_task(task_id)
        if not existing:
            raise HTTPException(404, "Task does not exist")
        if existing.get("status") not in {"failed", "cancelled", "dead_letter"}:
            raise HTTPException(409, "Only failed, cancelled or dead-letter tasks can be retried")
        task = current_store.retry_task(task_id)
        task_manager.schedule(task_id)
        return _public_task(task or {})

    @app.delete("/api/tasks/{task_id}")
    def cancel_task(task_id: str) -> dict[str, Any]:
        existing = current_store.get_task(task_id)
        if not existing:
            raise HTTPException(404, "Task does not exist")
        if existing.get("status") != "queued":
            raise HTTPException(409, "Only queued tasks can be cancelled")
        task = current_store.cancel_task(task_id)
        return _public_task(task or {})

    @app.get("/api/dead-letters")
    def list_dead_letters(active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        return [
            _public_dead_letter(item)
            for item in current_store.list_dead_letters(
                active_only=active_only, limit=max(1, min(limit, 200))
            )
        ]

    @app.get("/api/dead-letters/{task_id}")
    def get_dead_letter(task_id: str) -> dict[str, Any]:
        item = current_store.get_dead_letter(task_id)
        if not item:
            raise HTTPException(404, "Dead-letter task does not exist")
        return _public_dead_letter(item)

    @app.post("/api/dead-letters/{task_id}/compensate")
    async def compensate_dead_letter(task_id: str) -> dict[str, Any]:
        try:
            await task_manager.compensate(task_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        item = current_store.get_dead_letter(task_id)
        return _public_dead_letter(item or {})

    @app.post("/api/dead-letters/{task_id}/resolve")
    def resolve_dead_letter(task_id: str) -> dict[str, Any]:
        item = current_store.resolve_dead_letter(task_id)
        if not item:
            raise HTTPException(404, "Active dead-letter task does not exist")
        return _public_dead_letter(item)

    @app.get("/api/email-deliveries")
    def list_email_deliveries(
        status: Literal["sending", "sent", "failed"] | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return [
            _public_email_delivery(item)
            for item in current_store.list_email_deliveries(
                status=status,
                active_only=active_only,
                limit=max(1, min(limit, 200)),
            )
        ]

    @app.post("/api/email-deliveries/{delivery_id}/resolve")
    def resolve_email_delivery(delivery_id: str) -> dict[str, Any]:
        delivery = current_store.resolve_email_delivery(delivery_id)
        if not delivery:
            raise HTTPException(404, "Active failed email delivery does not exist")
        return _public_email_delivery(delivery)

    @app.get("/api/traces")
    def list_traces(limit: int = 100) -> list[dict[str, Any]]:
        return current_store.list_traces(max(1, min(limit, 200)))

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, Any]:
        trace = current_store.get_trace(trace_id)
        if not trace:
            raise HTTPException(404, "Trace does not exist")
        return trace

    @app.get("/api/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: int) -> FileResponse:
        artifact = current_store.get_artifact(artifact_id)
        if not artifact:
            raise HTTPException(404, "文件不存在")
        artifact_root = (target_dir / "artifacts").resolve()
        resolved = Path(artifact["file_path"]).resolve()
        migrated = (artifact_root / artifact["name"]).resolve()
        if not resolved.is_file() and migrated.is_file():
            resolved = migrated
        if not resolved.is_relative_to(artifact_root) or not resolved.is_file():
            raise HTTPException(404, "文件不存在")
        return FileResponse(
            resolved,
            filename=artifact["name"],
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

    return app


app = create_app()

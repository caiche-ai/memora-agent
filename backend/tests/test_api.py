from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

from memora.app import create_app
from memora.config import SmtpConfig
from memora.services.intent import route_intent
from memora.store import Store


def minimal_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 16 Tf 72 720 Td ({escaped}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode('ascii'))} >>\nstream\n{stream}\nendstream",
    ]
    pdf = "%PDF-1.4\n"
    offsets = [0]
    for index, item in enumerate(objects, 1):
        offsets.append(len(pdf.encode("ascii")))
        pdf += f"{index} 0 obj\n{item}\nendobj\n"
    xref = len(pdf.encode("ascii"))
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    pdf += "".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:])
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return pdf.encode("ascii")


def test_api_chat_pdf_meeting_todo_memory_and_ppt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_smtp_test(settings: SmtpConfig) -> None:
        assert settings.host == "smtp.example.com"

    async def fake_send_email(to: str, subject: str, body: str, settings: SmtpConfig) -> dict[str, object]:
        assert settings.password == "smtp-secret-value"
        return {"provider": "smtp", "messageId": "test-message", "accepted": [to], "rejected": []}

    async def fake_ensure_agentmail_inbox(inbox_id: str = "") -> str:
        return inbox_id or "memora-test@agentmail.to"

    async def fake_send_agentmail(inbox_id: str, to: str, subject: str, body: str) -> dict[str, object]:
        assert inbox_id == "memora-test@agentmail.to"
        return {
            "provider": "agentmail",
            "messageId": "agentmail-message",
            "accepted": [to],
            "rejected": [],
            "from": inbox_id,
        }

    monkeypatch.setattr("memora.app.test_smtp_connection", fake_smtp_test)
    monkeypatch.setattr("memora.app.send_todo_email", fake_send_email)
    monkeypatch.setattr("memora.app.agentmail_configured", lambda: True)
    monkeypatch.setattr("memora.app.ensure_agentmail_inbox", fake_ensure_agentmail_inbox)
    monkeypatch.setattr("memora.app.send_agentmail_message", fake_send_agentmail)
    asyncio.run(_exercise_api(tmp_path))


def test_memory_schema_migrates_existing_rows(tmp_path: Path) -> None:
    database = tmp_path / "legacy-memory.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,type TEXT NOT NULL,subject TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,source_type TEXT NOT NULL,source_id INTEGER,
        fingerprint TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
    )
    connection.execute(
        "INSERT INTO memories(type,subject,content,source_type,source_id,fingerprint) VALUES (?,?,?,?,?,?)",
        ("preference", "用户偏好", "我偏好简洁回答", "chat", None, "legacy-fingerprint"),
    )
    connection.commit()
    connection.close()

    store = Store(database)
    memories = store.list_memories(ordinary_only=True)
    assert len(memories) == 1
    assert memories[0]["scope_type"] == "ordinary"
    assert memories[0]["importance"] == 3
    assert memories[0]["fingerprint"].startswith("ordinary|")
    store.close()


def test_intent_router_covers_chat_search_ppt_and_meeting_drafts() -> None:
    assert route_intent("解释一下项目架构").name == "chat"
    search = route_intent("查询今天最新的人工智能新闻")
    assert search.name == "chat" and search.web_search is True
    ppt = route_intent("基于项目资料生成一份 PPT")
    assert ppt.name == "ppt" and ppt.reason == "matched_ppt_rule"
    assert route_intent("生成会议总结").name == "meeting_detail"
    assert route_intent("起草一封会后邮件").name == "email_content"


def test_unified_message_workflow_and_idempotent_meeting_artifact(tmp_path: Path) -> None:
    asyncio.run(_exercise_unified_message_workflow(tmp_path))


async def _exercise_unified_message_workflow(tmp_path: Path) -> None:
    store = Store(":memory:")
    app = create_app(data_dir=tmp_path, store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        project = (await client.post("/api/projects", json={"name": "统一编排测试"})).json()
        conversation = (await client.post(f"/api/projects/{project['id']}/conversations", json={})).json()
        meeting = (
            await client.post(
                f"/api/projects/{project['id']}/meetings",
                data={"name": "架构评审会"},
                files={
                    "file": (
                        "architecture.txt",
                        "架构评审会\n风险：接口可能延期。\n待办：由张三在8月30日前完成接口联调。".encode(),
                        "text/plain",
                    )
                },
            )
        ).json()["meeting"]

        response = await client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={
                "content": "@architecture.txt 生成会议总结",
                "documentIds": [meeting["document_id"]],
            },
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["routing"]["intent"] == "meeting_detail"
        assert result["execution"]["status"] == "completed"
        assert result["artifactDraft"]["meetingId"] == meeting["id"]
        assert result["artifactDraft"]["status"] == "draft"
        assert result["artifactDraft"]["confirmationRequired"] is True
        assert "会议摘要" in result["artifactDraft"]["content"]

        draft = result["artifactDraft"]
        save_body = {
            "name": draft["name"],
            "content": draft["content"],
            "analysis": draft["analysis"],
            "contentType": draft["contentType"],
            "idempotencyKey": draft["idempotencyKey"],
        }
        first_save = await client.post(f"/api/meetings/{meeting['id']}/details", json=save_body)
        second_save = await client.post(f"/api/meetings/{meeting['id']}/details", json=save_body)
        assert first_save.status_code == 201, first_save.text
        assert second_save.status_code == 201, second_save.text
        assert first_save.json()["file"]["id"] == second_save.json()["file"]["id"]
        assert first_save.json()["idempotent"] is False
        assert second_save.json()["idempotent"] is True
        assert [item["id"] for item in first_save.json()["todos"]] == [
            item["id"] for item in second_save.json()["todos"]
        ]
        assert len(store.list_meeting_documents(meeting["id"])) == 2

        message_count = len(store.list_messages(conversation["id"]))
        missing_file = await client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "再生成一份会议总结"},
        )
        assert missing_file.status_code == 422
        assert missing_file.json()["errorDetail"] == {
            "code": "meeting_file_required",
            "category": "context",
            "message": "请先输入 @ 并选择要处理的会议文件",
            "retryable": False,
            "stage": "context",
            "details": {},
        }
        assert len(store.list_messages(conversation["id"])) == message_count
    store.close()


async def _exercise_api(tmp_path: Path) -> None:
    store = Store(":memory:")
    app = create_app(data_dir=tmp_path, store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert response.json()["service"] == "backend"

        email_settings = {
            "host": "smtp.example.com",
            "port": 587,
            "secure": False,
            "user": "sender@example.com",
            "password": "smtp-secret-value",
            "fromAddress": "sender@example.com",
        }
        response = await client.post("/api/settings/email/test", json=email_settings)
        assert response.status_code == 200
        response = await client.put("/api/settings/email", json=email_settings)
        assert response.status_code == 200
        assert response.json()["configured"] is True
        assert response.json()["agentMailConfigured"] is True
        assert response.json()["smtpConfigured"] is True
        assert response.json()["defaultProvider"] == "agentmail"
        assert response.json()["passwordConfigured"] is True
        assert "password" not in response.json()
        encrypted = store.get_setting("smtp_config") or ""
        assert "smtp-secret-value" not in encrypted
        public_settings = (await client.get("/api/settings/email")).json()
        assert public_settings["source"] == "frontend"
        assert public_settings["fromAddress"] == "sender@example.com"

        response = await client.post("/api/conversations", json={})
        assert response.status_code == 201
        conversation = response.json()

        response = await client.post(
            "/api/projects", json={"name": "星河项目", "description": "项目会议与行动项"}
        )
        assert response.status_code == 201
        project = response.json()

        response = await client.post(
            f"/api/projects/{project['id']}/documents",
            files={
                "file": (
                    "project-background.pdf",
                    minimal_pdf("Galaxy project requires enterprise security review."),
                    "application/pdf",
                )
            },
        )
        assert response.status_code == 201, response.text
        project_document = response.json()
        assert project_document["project_id"] == project["id"]
        assert project_document["metadata"]["pages"] == 1
        preview = (await client.get(f"/api/documents/{project_document['id']}/preview")).json()
        assert preview["name"] == "project-background.pdf"
        assert "enterprise security review" in preview["content"]
        assert preview["truncated"] is False
        ordinary_messages_before = len(
            (await client.get(f"/api/conversations/{conversation['id']}")).json()["messages"]
        )
        invalid_reference = await client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "引用项目文件", "documentIds": [project_document["id"]]},
        )
        assert invalid_reference.status_code == 400
        ordinary_messages_after = len(
            (await client.get(f"/api/conversations/{conversation['id']}")).json()["messages"]
        )
        assert ordinary_messages_after == ordinary_messages_before

        response = await client.post(f"/api/projects/{project['id']}/conversations", json={})
        assert response.status_code == 201
        project_conversation = response.json()
        assert project_conversation["project_id"] == project["id"]
        global_conversation_ids = {item["id"] for item in (await client.get("/api/conversations")).json()}
        assert project_conversation["id"] not in global_conversation_ids

        response = await client.post(
            f"/api/conversations/{project_conversation['id']}/messages",
            json={"content": "What security review does this project require?"},
        )
        assert response.status_code == 201
        assert any(
            source["title"] == "project-background.pdf" for source in response.json()["message"]["sources"]
        )

        ordinary_memory = (
            await client.post(
                "/api/memories",
                json={
                    "type": "fact",
                    "subject": "共享规则",
                    "content": "统一记忆隔离测试内容",
                    "importance": 4,
                    "pinned": True,
                },
            )
        ).json()
        project_memory_response = await client.post(
            "/api/memories",
            json={
                "type": "fact",
                "subject": "共享规则",
                "content": "统一记忆隔离测试内容",
                "projectId": project["id"],
                "importance": 5,
            },
        )
        assert project_memory_response.status_code == 201, project_memory_response.text
        project_memory = project_memory_response.json()
        assert ordinary_memory["id"] != project_memory["id"]
        assert ordinary_memory["updated_at"]
        assert project_memory["updated_at"]
        assert ordinary_memory["scope_type"] == "ordinary"
        assert project_memory["scope_type"] == "project"
        assert project_memory["project_id"] == project["id"]
        ordinary_ids = {item["id"] for item in (await client.get("/api/memories?scope=ordinary")).json()}
        project_ids = {
            item["id"]
            for item in (await client.get(f"/api/memories?scope=project&project_id={project['id']}")).json()
        }
        assert ordinary_memory["id"] in ordinary_ids and project_memory["id"] not in ordinary_ids
        assert project_memory["id"] in project_ids and ordinary_memory["id"] not in project_ids
        updated_memory = (
            await client.patch(
                f"/api/memories/{project_memory['id']}",
                json={"content": "项目专属 QuantumMemory 规则", "pinned": True},
            )
        ).json()
        assert updated_memory["pinned"] == 1
        assert updated_memory["content"] == "项目专属 QuantumMemory 规则"
        assert project_memory["id"] not in {
            item["id"] for item in store.search_memories("QuantumMemory", project_id=None)
        }
        assert (
            store.search_memories("QuantumMemory", project_id=project["id"])[0]["id"] == project_memory["id"]
        )

        response = await client.patch(
            f"/api/documents/{project_document['id']}/content",
            json={"content": "Edited project knowledge contains the unique QuantumBridge requirement."},
        )
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["edited"] is True
        assert response.json()["metadata"]["chunks"] == 1
        edited_preview = (await client.get(f"/api/documents/{project_document['id']}/preview")).json()
        assert "QuantumBridge" in edited_preview["content"]
        edited_chunks = store.search_project_chunks(project["id"], ["quantumbridge"])
        assert edited_chunks and "QuantumBridge" in edited_chunks[0]["content"]

        response = await client.post(
            f"/api/projects/{project['id']}/documents",
            files={"file": ("temporary.md", "# 临时背景".encode(), "text/markdown")},
        )
        removable_project_document = response.json()
        response = await client.delete(
            f"/api/projects/{project['id']}/documents/{removable_project_document['id']}"
        )
        assert response.status_code == 204

        response = await client.post(
            f"/api/conversations/{conversation['id']}/documents",
            files={
                "file": ("plan.pdf", minimal_pdf("Project delivery date is September."), "application/pdf")
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["metadata"]["pages"] == 1
        pdf_document = response.json()

        response = await client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "总结这份 PDF 的主要内容。"},
        )
        assert response.status_code == 201
        assert any(source["title"] == "plan.pdf" for source in response.json()["message"]["sources"])

        response = await client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "What is the project delivery date?"},
        )
        assert response.status_code == 201
        assert any(source["title"] == "plan.pdf" for source in response.json()["message"]["sources"])

        response = await client.post(
            f"/api/conversations/{conversation['id']}/documents",
            files={"file": ("notes.md", "# 说明\n这是 Markdown 知识文件。".encode(), "text/markdown")},
        )
        assert response.status_code == 201, response.text
        markdown_document = response.json()
        assert markdown_document["metadata"]["format"] == "md"

        response = await client.delete(
            f"/api/conversations/{conversation['id']}/documents/{markdown_document['id']}"
        )
        assert response.status_code == 204
        conversation_detail = (await client.get(f"/api/conversations/{conversation['id']}")).json()
        document_ids = {item["id"] for item in conversation_detail["documents"]}
        assert markdown_document["id"] not in document_ids
        assert pdf_document["id"] in document_ids

        response = await client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "我叫张三，我们在做星河项目"},
        )
        assert response.status_code == 201
        assert response.json()["message"]["role"] == "assistant"
        ordinary_auto_memories = store.list_memories(ordinary_only=True)
        assert ordinary_auto_memories
        assert all(item["scope_type"] == "ordinary" for item in ordinary_auto_memories)
        assert all(item["project_id"] is None for item in ordinary_auto_memories)

        response = await client.post(
            f"/api/projects/{project['id']}/meetings",
            data={"name": "表单指定的会议名称"},
            files={
                "file": (
                    "meeting.txt",
                    "项目会议\n张三：当前存在延期风险。\n待办：由张三在8月28日前完成修复。".encode(),
                    "text/plain",
                )
            },
        )
        assert response.status_code == 201, response.text
        meeting = response.json()
        assert meeting["meeting"]["risks"] == []
        assert meeting["meeting"]["project_id"] == project["id"]
        assert meeting["meeting"]["title"] == "表单指定的会议名称"
        assert meeting["todos"] == []
        assert meeting["analysisStatus"] == "not_generated"
        meeting_id = meeting["meeting"]["id"]
        source_document_id = meeting["meeting"]["document_id"]

        response = await client.patch(f"/api/meetings/{meeting_id}", json={"name": "用户命名的联调会议"})
        assert response.status_code == 200, response.text
        assert response.json()["title"] == "用户命名的联调会议"

        response = await client.patch(
            f"/api/meetings/{meeting_id}/files/{source_document_id}",
            json={"name": "联调会议原文.txt"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "联调会议原文.txt"

        response = await client.post(
            f"/api/conversations/{project_conversation['id']}/messages",
            json={"content": "@联调会议原文.txt 总结这份会议文件", "documentIds": [source_document_id]},
        )
        assert response.status_code == 201, response.text
        assert any(
            source["documentId"] == source_document_id for source in response.json()["message"]["sources"]
        )
        project_auto_memories = store.list_memories(project_id=project["id"])
        assert project_auto_memories
        assert all(item["scope_type"] == "project" for item in project_auto_memories)
        assert all(item["project_id"] == project["id"] for item in project_auto_memories)

        response = await client.post(
            f"/api/meetings/{meeting['meeting']['id']}/detail-draft",
            json={"instruction": "突出风险和待办"},
        )
        assert response.status_code == 200, response.text
        detail_draft = response.json()
        assert "会议摘要" in detail_draft["content"]
        assert detail_draft["analysis"]["risks"]
        assert detail_draft["name"].startswith(detail_draft["analysis"]["title"])
        assert project_document["id"] in detail_draft["context"]["sourceDocumentIds"]
        assert project_memory["id"] in detail_draft["context"]["memoryIds"]
        assert detail_draft["routing"]["intent"] == "meeting_detail"
        detail_draft["name"] = "用户修改的会议详情.md"

        response = await client.post(
            f"/api/meetings/{meeting['meeting']['id']}/details",
            json=detail_draft,
        )
        assert response.status_code == 201, response.text
        saved_detail = response.json()
        assert saved_detail["meeting"]["title"] == "用户命名的联调会议"
        assert saved_detail["file"]["meeting_id"] == meeting["meeting"]["id"]
        assert saved_detail["file"]["metadata"]["artifact"] is True
        assert saved_detail["file"]["name"] == "用户修改的会议详情.md"
        assert saved_detail["todos"]
        preview = (await client.get(f"/api/documents/{saved_detail['file']['id']}/preview")).json()
        assert "会议摘要" in preview["content"]

        response = await client.patch(
            f"/api/meetings/{meeting['meeting']['id']}/artifacts/{saved_detail['file']['id']}",
            json={"name": "Artifacts中修改的文件名"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Artifacts中修改的文件名.md"
        detail_as_email = (
            await client.get(
                f"/api/meetings/{meeting['meeting']['id']}/artifacts/{saved_detail['file']['id']}/email-draft"
            )
        ).json()
        assert detail_as_email["subject"] == "Artifacts中修改的文件名"
        assert "会议摘要" in detail_as_email["body"]
        response = await client.post(
            f"/api/meetings/{meeting['meeting']['id']}/artifacts/{saved_detail['file']['id']}/send-email",
            json={
                "provider": "agentmail",
                "to": "recipient@example.com",
                "subject": detail_as_email["subject"],
                "body": detail_as_email["body"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["documentId"] == saved_detail["file"]["id"]

        response = await client.post(
            f"/api/meetings/{meeting['meeting']['id']}/detail-draft",
            json={"instruction": "生成一封会后同步邮件", "contentType": "email_content"},
        )
        assert response.status_code == 200, response.text
        email_draft = response.json()
        assert email_draft["contentType"] == "email_content"
        assert "会议邮件内容" in email_draft["content"]
        todo_ids_before_email_save = {item["id"] for item in saved_detail["todos"]}

        response = await client.post(
            f"/api/meetings/{meeting['meeting']['id']}/details",
            json=email_draft,
        )
        assert response.status_code == 201, response.text
        saved_email = response.json()
        assert saved_email["file"]["metadata"]["artifact"] is True
        assert saved_email["file"]["metadata"]["role"] == "email_content"
        assert {item["id"] for item in saved_email["todos"]} == todo_ids_before_email_save
        email_preview = (await client.get(f"/api/documents/{saved_email['file']['id']}/preview")).json()
        assert "会议邮件内容" in email_preview["content"]
        artifact_email_draft = (
            await client.get(
                f"/api/meetings/{meeting['meeting']['id']}/artifacts/{saved_email['file']['id']}/email-draft"
            )
        ).json()
        assert "会议纪要与后续行动" in artifact_email_draft["subject"]
        assert "会议摘要" in artifact_email_draft["body"]
        response = await client.post(
            f"/api/meetings/{meeting['meeting']['id']}/artifacts/{saved_email['file']['id']}/send-email",
            json={
                "provider": "agentmail",
                "to": "recipient@example.com",
                "subject": artifact_email_draft["subject"],
                "body": artifact_email_draft["body"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["documentId"] == saved_email["file"]["id"]
        assert response.json()["accepted"] == ["recipient@example.com"]

        response = await client.delete(f"/api/meetings/{meeting_id}/files/{saved_email['file']['id']}")
        assert response.status_code == 204, response.text
        assert (await client.get(f"/api/documents/{saved_email['file']['id']}/preview")).status_code == 404

        response = await client.delete(f"/api/meetings/{meeting_id}/files/{source_document_id}")
        assert response.status_code == 400

        project_detail = (await client.get(f"/api/projects/{project['id']}")).json()
        assert project_detail["project"]["name"] == "星河项目"
        assert project_detail["project"]["document_count"] == 1
        assert project_detail["project"]["conversation_count"] == 1
        assert project_detail["conversations"][0]["id"] == project_conversation["id"]
        assert [item["id"] for item in project_detail["documents"]] == [project_document["id"]]
        assert project_detail["meetings"][0]["id"] == meeting["meeting"]["id"]
        assert len(project_detail["meetings"][0]["files"]) == 2
        assert project_detail["todos"]
        assert any(item["type"] == "risk" for item in project_detail["memories"])

        todos = (await client.get("/api/todos")).json()
        assert todos
        draft = (await client.get(f"/api/todos/{todos[0]['id']}/email-draft")).json()
        assert "待办提醒" in draft["subject"]
        response = await client.post(
            f"/api/todos/{todos[0]['id']}/send-email",
            json={
                "provider": "smtp",
                "to": "recipient@example.com",
                "subject": draft["subject"],
                "body": draft["body"],
            },
        )
        assert response.status_code == 200
        assert response.json()["provider"] == "smtp"
        assert response.json()["accepted"] == ["recipient@example.com"]

        response = await client.post(
            f"/api/todos/{todos[0]['id']}/send-email",
            json={"to": "recipient@example.com", "subject": draft["subject"], "body": draft["body"]},
        )
        assert response.status_code == 200
        assert response.json()["provider"] == "agentmail"
        assert response.json()["from"] == "memora-test@agentmail.to"
        assert store.get_setting("agentmail_inbox_id") == "memora-test@agentmail.to"
        assert (await client.delete("/api/settings/email")).status_code == 204
        assert any(item["type"] == "risk" for item in (await client.get("/api/memories")).json())

        empty_project = (await client.post("/api/projects", json={"name": "临时项目"})).json()
        renamed_project = (
            await client.patch(f"/api/projects/{empty_project['id']}", json={"name": "已重命名项目"})
        ).json()
        assert renamed_project["name"] == "已重命名项目"
        response = await client.delete(f"/api/projects/{empty_project['id']}")
        assert response.status_code == 204

        response = await client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "基于我上传的文件制作一份项目汇报 PPT"},
        )
        assert response.status_code == 201, response.text
        ppt_result = response.json()
        assert ppt_result["routing"]["intent"] == "ppt"
        assert any(source["documentId"] == pdf_document["id"] for source in ppt_result["message"]["sources"])
        artifact = ppt_result["artifact"]
        assert pdf_document["id"] in artifact["metadata"]["sourceDocumentIds"]
        assert artifact["metadata"]["intent"] == "ppt"
        download = await client.get(artifact["downloadUrl"])
        assert download.status_code == 200
        assert download.content[:2] == b"PK"

        response = await client.delete(f"/api/meetings/{meeting_id}")
        assert response.status_code == 204
        assert (await client.get(f"/api/meetings/{meeting_id}")).status_code == 404
        assert (await client.get(f"/api/documents/{source_document_id}/preview")).status_code == 404
        assert (await client.get(f"/api/documents/{saved_detail['file']['id']}/preview")).status_code == 404
        assert all(item["meeting_id"] != meeting_id for item in (await client.get("/api/todos")).json())
        assert not any(
            item["source_type"] == "meeting" and item["source_id"] == meeting_id
            for item in (await client.get("/api/memories")).json()
        )

        response = await client.delete(f"/api/projects/{project['id']}")
        assert response.status_code == 204
        assert store.project_background_documents(project["id"]) == []
        assert (await client.get(f"/api/projects/{project['id']}")).status_code == 404
        assert (await client.get(f"/api/conversations/{project_conversation['id']}")).status_code == 404
        assert (await client.get(f"/api/meetings/{meeting['meeting']['id']}")).status_code == 404
        assert all(
            item["meeting_id"] != meeting["meeting"]["id"] for item in (await client.get("/api/todos")).json()
        )
    store.close()

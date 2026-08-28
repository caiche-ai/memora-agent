from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from memora.services.documents import chunk_pages, decode_text
from memora.services.meeting import analyze_meeting, heuristic_analysis, meeting_memories
from memora.services.ppt import create_presentation, is_ppt_request
from memora.store import Store, tokenize


def test_store_conversations_documents_and_memories() -> None:
    store = Store(":memory:")
    conversation = store.create_conversation()
    store.add_message(conversation["id"], "user", "项目交付计划是什么？")
    document = store.add_document(
        conversation_id=conversation["id"],
        name="plan.pdf",
        mime_type="application/pdf",
        kind="knowledge",
        text="项目将在九月交付",
    )
    store.add_chunks(
        document["id"], [{"index": 0, "page_number": 2, "content": "星河项目计划在九月完成交付。"}]
    )
    store.add_memory(
        {
            "type": "person",
            "subject": "张三",
            "content": "负责星河项目",
            "source_type": "chat",
            "source_id": 1,
        }
    )
    assert len(store.list_messages(conversation["id"])) == 1
    assert store.search_chunks(conversation["id"], tokenize("星河项目什么时候交付"))[0]["page_number"] == 2
    assert store.search_memories("张三负责什么")[0]["subject"] == "张三"
    store.close()


def test_existing_meetings_migrate_to_default_project(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER,
          name TEXT NOT NULL, mime_type TEXT NOT NULL, kind TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'ready', text_content TEXT NOT NULL DEFAULT '',
          metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE meetings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          title TEXT NOT NULL, summary TEXT NOT NULL, participants_json TEXT NOT NULL DEFAULT '[]',
          dates_json TEXT NOT NULL DEFAULT '[]', locations_json TEXT NOT NULL DEFAULT '[]',
          topics_json TEXT NOT NULL DEFAULT '[]', risks_json TEXT NOT NULL DEFAULT '[]',
          decisions_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO documents(name,mime_type,kind,text_content) VALUES ('legacy.txt','text/plain','meeting','旧会议');
        INSERT INTO meetings(document_id,title,summary) VALUES (1,'旧会议','迁移测试');
        """
    )
    connection.commit()
    connection.close()

    store = Store(database)
    projects = store.list_projects()
    assert projects[0]["name"] == "默认项目"
    assert "project_id" in {row["name"] for row in store._all("PRAGMA table_info(conversations)")}
    assert "project_id" in {row["name"] for row in store._all("PRAGMA table_info(documents)")}
    assert store.list_meetings(projects[0]["id"])[0]["title"] == "旧会议"
    store.close()


def test_meeting_analysis_extracts_risks_todos_and_memories() -> None:
    text = """星河项目周例会
时间：2026年8月25日
地点：三号会议室
张三：测试环境还没有准备完成，存在延期风险。
李四：由李四在8月27日前完成环境部署。
决定保持验收节点不变。"""
    result = heuristic_analysis(text, "meeting.txt")
    assert "张三" in result["participants"]
    assert "2026年8月25日" in result["dates"]
    assert result["risks"]
    assert result["todos"]
    assert result["decisions"]
    assert any(item["type"] == "risk" for item in meeting_memories(result, 1))


def test_meeting_analysis_receives_project_background(monkeypatch) -> None:
    captured: list[dict[str, str]] = []

    async def fake_complete_json(messages, fallback):
        captured.extend(messages)
        return fallback

    monkeypatch.setattr("memora.services.meeting.complete_json", fake_complete_json)
    result = asyncio.run(
        analyze_meeting(
            "本周确认验收安排。",
            "meeting.txt",
            [{"name": "产品规范.pdf", "content": "项目验收必须完成安全评审。"}],
        )
    )
    assert result["title"]
    assert "产品规范.pdf" in captured[1]["content"]
    assert "项目验收必须完成安全评审" in captured[1]["content"]


def test_document_chunking_and_text_decoding() -> None:
    chunks = chunk_pages([{"page_number": 3, "text": "这是第一段。" * 100 + "这是结尾。"}], 120, 20)
    assert len(chunks) > 2
    assert all(item["page_number"] == 3 for item in chunks)
    assert decode_text("普通文本".encode()) == "普通文本"


def test_ppt_request_and_generation(tmp_path: Path) -> None:
    assert is_ppt_request("帮我制作一份项目汇报 PPT")
    result = asyncio.run(create_presentation("制作一份项目汇报 PPT", tmp_path))
    content = Path(result["file_path"]).read_bytes()
    assert content[:2] == b"PK"
    assert len(content) > 10_000

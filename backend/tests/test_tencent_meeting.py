from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from memora.app import create_app
from memora.config import TencentMeetingConfig
from memora.services.tencent_meeting import TencentMeetingClient, normalize_records, transcript_text
from memora.store import Store


class FakeTencentMeetingClient:
    configured = True

    async def list_records(self, days: int = 30) -> list[dict[str, object]]:
        assert days == 7
        return [
            {
                "meetingRecordId": "record-1",
                "recordFileId": "file-1",
                "meetingId": "meeting-1",
                "subject": "项目周会",
                "fileName": "项目周会转写",
                "fileType": "文字转写",
                "startTime": "2026-08-27T10:00:00+08:00",
                "endTime": "2026-08-27T11:00:00+08:00",
                "status": "completed",
            }
        ]

    async def get_transcript(self, record_file_id: str, meeting_id: str | None = None) -> str:
        assert record_file_id == "file-1"
        assert meeting_id == "meeting-1"
        return "[00:00:01] 张三: 确认本周完成腾讯会议导入。"


def test_normalize_records_and_transcript_text() -> None:
    records = normalize_records(
        {
            "meeting_record_list": [
                {
                    "meeting_record_id": "record-1",
                    "meeting_id": "meeting-1",
                    "subject": "项目周会",
                    "record_files": [
                        {
                            "record_file_id": "file-1",
                            "file_name": "项目周会转写",
                            "record_type": "文字转写",
                            "record_start_time": 1_788_487_200,
                        }
                    ],
                }
            ]
        }
    )
    assert records[0]["recordFileId"] == "file-1"
    assert records[0]["meetingId"] == "meeting-1"
    assert records[0]["subject"] == "项目周会"

    text = transcript_text(
        {
            "paragraphs": [
                {
                    "speaker": {"nickname": "张三"},
                    "sentences": [
                        {"start_time": 1_000, "text": "确认方案。"},
                        {"start_time": 3_500, "text": "周五完成。"},
                    ],
                }
            ]
        }
    )
    assert "[00:00:01] 张三: 确认方案。" in text
    assert "[00:00:03] 张三: 周五完成。" in text


def test_tencent_meeting_records_import_and_idempotency(tmp_path: Path) -> None:
    asyncio.run(_exercise_tencent_meeting_import(tmp_path))


def test_official_mcp_json_rpc_and_transcript_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_request_json(**kwargs):
        calls.append(kwargs)
        tool = kwargs["json_body"]["params"]["name"]
        if tool == "get_transcripts_paragraphs":
            value = {"pids": [{"pid": "7"}]}
        else:
            value = {"paragraphs": [{"speaker_name": "李四", "text": "接口联调完成。"}]}
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": json.dumps(value)}]},
        }

    monkeypatch.setattr("memora.services.tencent_meeting.request_json", fake_request_json)
    client = TencentMeetingClient(
        TencentMeetingConfig(
            token="secret-token",
            base_url="https://mcp.example.test/v1",
            skill_version="v1.0.14",
            timeout_seconds=30,
        )
    )

    text = asyncio.run(client.get_transcript("file-1", "meeting-1"))

    assert text == "李四: 接口联调完成。"
    assert [call["json_body"]["params"]["name"] for call in calls] == [
        "get_transcripts_paragraphs",
        "get_transcripts_details",
    ]
    assert calls[0]["headers"]["X-Tencent-Meeting-Token"] == "secret-token"
    assert calls[1]["json_body"]["params"]["arguments"]["pid"] == "7"


async def _exercise_tencent_meeting_import(tmp_path: Path) -> None:
    store = Store(":memory:")
    app = create_app(
        data_dir=tmp_path,
        store=store,
        tencent_meeting_client=FakeTencentMeetingClient(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        project = (await client.post("/api/projects", json={"name": "MCP 项目"})).json()

        status = await client.get("/api/integrations/tencent-meeting/status")
        assert status.status_code == 200
        assert status.json()["configured"] is True

        records = await client.get("/api/integrations/tencent-meeting/records?days=7")
        assert records.status_code == 200
        assert records.json()["records"][0]["recordFileId"] == "file-1"

        payload = {
            "recordFileId": "file-1",
            "meetingId": "meeting-1",
            "meetingRecordId": "record-1",
            "title": "项目周会",
        }
        first = await client.post(
            f"/api/projects/{project['id']}/integrations/tencent-meeting/import",
            json=payload,
        )
        second = await client.post(
            f"/api/projects/{project['id']}/integrations/tencent-meeting/import",
            json=payload,
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["idempotent"] is False
        assert second.json()["idempotent"] is True
        assert first.json()["meeting"]["id"] == second.json()["meeting"]["id"]
        source = store.get_document(first.json()["meeting"]["document_id"])
        assert source is not None
        assert source["metadata"]["source"] == "tencent_meeting"
        assert source["metadata"]["recordFileId"] == "file-1"
        assert "张三" in source["text_content"]
        assert len(store.list_meetings(project["id"])) == 1
    store.close()

from __future__ import annotations

import json
import platform
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import TencentMeetingConfig
from .provider import ProviderError, request_json

PROVIDER = "tencent_meeting"
SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))


def _decoded(value: Any) -> Any:
    current = value
    for _ in range(3):
        if not isinstance(current, str):
            break
        text = current.strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        elif text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()
        if not text.startswith(("{", "[", '"')):
            break
        try:
            current = json.loads(text)
        except json.JSONDecodeError:
            break
    return current


def _normalized_key(value: Any) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _direct_value(value: Any, names: tuple[str, ...]) -> Any:
    value = _decoded(value)
    if not isinstance(value, dict):
        return None
    wanted = {_normalized_key(name) for name in names}
    for key, child in value.items():
        if _normalized_key(key) in wanted and child is not None:
            return child
    return None


def _deep_value(value: Any, names: tuple[str, ...]) -> Any:
    value = _decoded(value)
    direct = _direct_value(value, names)
    if direct is not None:
        return direct
    children = value if isinstance(value, list) else value.values() if isinstance(value, dict) else []
    for child in children:
        found = _deep_value(child, names)
        if found is not None:
            return found
    return None


def _objects_with_key(value: Any, names: tuple[str, ...], output: list[dict[str, Any]]) -> None:
    value = _decoded(value)
    if isinstance(value, list):
        for child in value:
            _objects_with_key(child, names, output)
        return
    if not isinstance(value, dict):
        return
    if _direct_value(value, names) is not None:
        output.append(value)
    for child in value.values():
        _objects_with_key(child, names, output)


def _string(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _time_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    if number < 10_000_000_000:
        number *= 1000
    return datetime.fromtimestamp(number / 1000, tz=SHANGHAI_TIMEZONE).isoformat()


def _record_type(value: Any) -> str:
    labels = {0: "云录制", 2: "上传录制", 3: "文字转写", 4: "视频录制", 5: "录音"}
    try:
        return labels.get(int(str(value)), _string(value))
    except ValueError:
        return _string(value)


def _record_status(value: Any) -> str:
    labels = {1: "录制中", 2: "转码中", 3: "转码完成"}
    try:
        return labels.get(int(str(value)), _string(value))
    except ValueError:
        return _string(value)


def normalize_records(raw: Any) -> list[dict[str, Any]]:
    parents: list[dict[str, Any]] = []
    _objects_with_key(raw, ("meeting_record_id", "meetingRecordId"), parents)
    rows: list[dict[str, Any]] = []

    def add_row(parent: dict[str, Any], file: dict[str, Any] | None = None) -> None:
        source = file or parent
        meeting_record_id = _direct_value(parent, ("meeting_record_id", "meetingRecordId")) or _direct_value(
            source, ("meeting_record_id", "meetingRecordId")
        )
        record_file_id = _direct_value(
            source, ("record_file_id", "recordFileId", "file_id", "fileId")
        ) or _direct_value(parent, ("record_file_id", "recordFileId", "file_id", "fileId"))
        if meeting_record_id is None and record_file_id is None:
            return
        rows.append(
            {
                "meetingRecordId": _string(meeting_record_id) or None,
                "recordFileId": _string(record_file_id) or None,
                "meetingId": _string(
                    _direct_value(parent, ("meeting_id", "meetingId"))
                    or _direct_value(source, ("meeting_id", "meetingId"))
                )
                or None,
                "subject": _string(
                    _direct_value(parent, ("subject", "meeting_subject", "title"))
                    or _direct_value(source, ("subject", "meeting_subject", "title"))
                ),
                "fileName": _string(_direct_value(source, ("file_name", "fileName", "name"))),
                "fileType": _record_type(
                    _direct_value(
                        source,
                        ("file_type", "fileType", "record_file_type", "recordFileType", "record_type"),
                    )
                    or _direct_value(parent, ("record_type", "recordType"))
                ),
                "startTime": _time_value(
                    _direct_value(source, ("record_start_time", "recordStartTime", "start_time", "startTime"))
                    or _direct_value(
                        parent, ("record_start_time", "recordStartTime", "start_time", "startTime")
                    )
                ),
                "endTime": _time_value(
                    _direct_value(source, ("record_end_time", "recordEndTime", "end_time", "endTime"))
                    or _direct_value(parent, ("record_end_time", "recordEndTime", "end_time", "endTime"))
                ),
                "status": _record_status(
                    _direct_value(source, ("status", "state", "record_status", "recordStatus"))
                    or _direct_value(parent, ("status", "state", "record_status", "recordStatus"))
                ),
            }
        )

    for parent in parents:
        files: list[dict[str, Any]] = []
        container = _direct_value(parent, ("record_files", "recordFiles", "files", "file_list", "fileList"))
        _objects_with_key(container, ("record_file_id", "recordFileId", "file_id", "fileId"), files)
        if files:
            for file in files:
                add_row(parent, file)
        else:
            add_row(parent)

    if not parents:
        files = []
        _objects_with_key(raw, ("record_file_id", "recordFileId", "file_id", "fileId"), files)
        for file in files:
            add_row(file, file)

    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['meetingRecordId'] or ''}:{row['recordFileId'] or ''}"
        unique.setdefault(key, row)
    return sorted(
        unique.values(),
        key=lambda item: item.get("startTime") or "",
        reverse=True,
    )


def _speaker_name(value: Any) -> str:
    direct = _direct_value(
        value,
        ("speaker_name", "speakerName", "user_name", "userName", "nickname", "nick_name"),
    )
    if direct is not None:
        return _string(direct)
    speaker = _direct_value(value, ("speaker", "user"))
    if isinstance(speaker, dict):
        return _string(_direct_value(speaker, ("name", "nickname", "nick_name", "user_name", "speaker_name")))
    return _string(speaker)


def _clock(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(str(value))
    except ValueError:
        return _string(value)
    if number > 86_400_000:
        return ""
    seconds = max(0, int(number / 1000))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def transcript_text(raw: Any) -> str:
    raw = _decoded(raw)
    if isinstance(raw, str):
        return raw.strip()

    segments: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    text_keys = ("text", "sentence_text", "sentenceText", "speech_text", "transcript_text")

    def visit(value: Any, inherited_speaker: str = "") -> None:
        value = _decoded(value)
        if isinstance(value, list):
            for child in value:
                visit(child, inherited_speaker)
            return
        if not isinstance(value, dict):
            return
        speaker = _speaker_name(value) or inherited_speaker
        text = _string(_direct_value(value, text_keys))
        start = _clock(
            _direct_value(value, ("start_time", "startTime", "start_timestamp", "offset", "timestamp"))
        )
        if text:
            fingerprint = (start, speaker, text)
            if fingerprint not in seen:
                seen.add(fingerprint)
                prefix = " ".join(part for part in (f"[{start}]" if start else "", speaker) if part)
                segments.append(f"{prefix}: {text}" if prefix else text)
        for key, child in value.items():
            if _normalized_key(key) not in {_normalized_key(name) for name in text_keys}:
                visit(child, speaker)

    visit(raw)
    if segments:
        return "\n".join(segments).strip()

    fallback = _deep_value(raw, ("content", "transcript", "transcripts"))
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    raise ProviderError(
        "腾讯会议尚未返回可导入的逐字稿，请确认云录制和文字转写已生成",
        provider=PROVIDER,
        code="transcript_empty",
        retryable=True,
        status_code=422,
    )


class TencentMeetingClient:
    def __init__(self, settings: TencentMeetingConfig) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.token.strip())

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise ProviderError(
                "尚未配置腾讯会议 Token",
                provider=PROVIDER,
                code="not_configured",
                retryable=False,
                status_code=503,
            )
        response = await request_json(
            provider=PROVIDER,
            operation_name=method,
            method="POST",
            url=self.settings.base_url,
            timeout=self.settings.timeout_seconds,
            headers={
                "Content-Type": "application/json",
                "X-Tencent-Meeting-Token": self.settings.token,
                "X-Skill-Version": self.settings.skill_version,
            },
            json_body={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1},
        )
        error = response.get("error")
        if error:
            self._raise_mcp_error(error)
        result = response.get("result", response)
        if isinstance(result, dict) and result.get("error"):
            self._raise_mcp_error(result["error"])
        return result if isinstance(result, dict) else {"value": result}

    @staticmethod
    def _raise_mcp_error(error: Any) -> None:
        if isinstance(error, dict):
            message = _string(error.get("message")) or "腾讯会议 MCP 调用失败"
            code = _string(error.get("code")) or "mcp_error"
        else:
            message, code = _string(error) or "腾讯会议 MCP 调用失败", "mcp_error"
        raise ProviderError(
            message,
            provider=PROVIDER,
            code=code,
            retryable=False,
            status_code=422,
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._rpc(
            "tools/call",
            {
                "name": name,
                "arguments": {
                    **arguments,
                    "_client_info": {
                        "os": platform.system().lower(),
                        "agent": "memora-agent",
                        "model": "deterministic-web-app",
                    },
                },
            },
        )
        content = result.get("content")
        if not isinstance(content, list):
            return _decoded(result)
        values = [_decoded(item.get("text", "")) for item in content if item.get("type") == "text"]
        values = [value for value in values if value not in (None, "")]
        if not values:
            return _decoded(result)
        return values[0] if len(values) == 1 else values

    async def list_records(self, days: int = 30) -> list[dict[str, Any]]:
        end = datetime.now(SHANGHAI_TIMEZONE)
        start = end - timedelta(days=max(1, min(days, 31)))
        raw_pages: list[Any] = []
        page_token = ""
        for _ in range(10):
            arguments: dict[str, Any] = {
                "start_time": start.isoformat(timespec="seconds"),
                "end_time": end.isoformat(timespec="seconds"),
                "page_size": 20,
            }
            if page_token:
                arguments["page_token"] = page_token
            page = await self.call_tool("get_records_list", arguments)
            raw_pages.append(page)
            next_token = _deep_value(page, ("next_page_token", "nextPageToken"))
            has_more = _deep_value(page, ("has_more", "hasMore"))
            if not next_token or str(next_token) == page_token or has_more in (False, 0, "0", "false"):
                break
            page_token = str(next_token)
        return normalize_records(raw_pages)

    async def get_transcript(self, record_file_id: str, meeting_id: str | None = None) -> str:
        common: dict[str, Any] = {"record_file_id": record_file_id}
        if meeting_id:
            common["meeting_id"] = meeting_id
        paragraphs = await self.call_tool("get_transcripts_paragraphs", common)
        paragraph_objects: list[dict[str, Any]] = []
        _objects_with_key(paragraphs, ("pid",), paragraph_objects)
        first_pid = next(
            (
                _string(_direct_value(item, ("pid",)))
                for item in paragraph_objects
                if _direct_value(item, ("pid",))
            ),
            "0",
        )
        return transcript_text(
            await self.call_tool(
                "get_transcripts_details",
                {**common, "pid": first_pid},
            )
        )

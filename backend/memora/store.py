from __future__ import annotations

import hmac
import json
import math
import re
import sqlite3
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import ensure_data_dirs

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE,
  username TEXT COLLATE NOCASE, password_hash TEXT,
  display_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin','member')),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_role_status ON users(role,status);
CREATE TABLE IF NOT EXISTS workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_members (
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('owner','admin','member')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(workspace_id,user_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members(user_id,workspace_id);
CREATE TABLE IF NOT EXISTS sms_login_codes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL, code_hash TEXT NOT NULL,
  request_ip TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT NOT NULL, consumed_at TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sms_codes_phone ON sms_login_codes(phone,id DESC);
CREATE TABLE IF NOT EXISTS auth_sessions (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, revoked_at TEXT,
  created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id,expires_at);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
  workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  title TEXT NOT NULL DEFAULT '新对话',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('user','assistant','system')), content TEXT NOT NULL,
  sources_json TEXT NOT NULL DEFAULT '[]', artifact_id INTEGER, execution_id TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id,id);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS project_members (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'viewer' CHECK(role IN ('owner','editor','viewer')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(project_id,user_id)
);
CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_id,project_id);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
  project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
  meeting_id INTEGER,
  idempotency_key TEXT,
  name TEXT NOT NULL, mime_type TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('knowledge','meeting')),
  status TEXT NOT NULL DEFAULT 'ready', text_content TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS document_chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page_number INTEGER, chunk_index INTEGER NOT NULL, heading TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL, embedding_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id,chunk_index);
CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  title TEXT NOT NULL, summary TEXT NOT NULL, participants_json TEXT NOT NULL DEFAULT '[]',
  dates_json TEXT NOT NULL DEFAULT '[]', locations_json TEXT NOT NULL DEFAULT '[]', topics_json TEXT NOT NULL DEFAULT '[]',
  risks_json TEXT NOT NULL DEFAULT '[]', decisions_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS todos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
  title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '', due_date TEXT NOT NULL DEFAULT '',
  risk_level TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'open', email_status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
  source_type TEXT NOT NULL, source_id INTEGER,
  scope_type TEXT NOT NULL DEFAULT 'ordinary' CHECK(scope_type IN ('ordinary','project')),
  project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
  workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  importance INTEGER NOT NULL DEFAULT 3 CHECK(importance BETWEEN 1 AND 5), pinned INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0.8, valid_from TEXT, valid_until TEXT,
  supersedes_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active', sensitivity TEXT NOT NULL DEFAULT 'private', embedding_json TEXT,
  use_count INTEGER NOT NULL DEFAULT 0, last_used_at TEXT,
  fingerprint TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type,id DESC);
CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
  kind TEXT NOT NULL, name TEXT NOT NULL, file_path TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
  execution_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS agent_tasks (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
  payload_json TEXT NOT NULL DEFAULT '{}', result_json TEXT, error_json TEXT,
  idempotency_key TEXT, trace_id TEXT, progress INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
  available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, started_at TEXT, completed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(kind,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status,available_at,created_at);
CREATE TABLE IF NOT EXISTS dead_letter_tasks (
  task_id TEXT PRIMARY KEY REFERENCES agent_tasks(id) ON DELETE CASCADE,
  error_json TEXT NOT NULL DEFAULT '{}', compensation_status TEXT NOT NULL DEFAULT 'pending',
  compensation_result_json TEXT, resolved_at TEXT, resolution TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dead_letter_active ON dead_letter_tasks(resolved_at,created_at DESC);
CREATE TABLE IF NOT EXISTS execution_traces (
  id TEXT PRIMARY KEY, task_id TEXT, conversation_id INTEGER, intent TEXT,
  status TEXT NOT NULL DEFAULT 'running', error_json TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT, duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_execution_traces_started ON execution_traces(started_at DESC);
CREATE TABLE IF NOT EXISTS trace_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL REFERENCES execution_traces(id) ON DELETE CASCADE,
  stage TEXT NOT NULL, event TEXT NOT NULL, status TEXT NOT NULL,
  attempt INTEGER, duration_ms INTEGER, metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id,id);
CREATE TABLE IF NOT EXISTS email_deliveries (
  id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, source_type TEXT NOT NULL,
  source_id INTEGER, provider TEXT, recipient TEXT NOT NULL, subject TEXT NOT NULL,
  body_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'sending', attempts INTEGER NOT NULL DEFAULT 1,
  result_json TEXT, error_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, sent_at TEXT, resolved_at TEXT, resolution TEXT
);
"""


def _decode_json(row: dict[str, Any] | None, fields: list[str]) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for field in fields:
        target = field.removesuffix("_json")
        try:
            result[target] = json.loads(result.get(field) or ("{}" if field == "metadata_json" else "[]"))
        except (TypeError, json.JSONDecodeError):
            result[target] = {} if field == "metadata_json" else []
        result.pop(field, None)
    return result


def tokenize(text: str) -> list[str]:
    value = str(text or "").lower()
    latin = re.findall(r"[a-z0-9_]{2,}", value)
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", value)
    bigrams = [word[index : index + 2] for word in chinese for index in range(len(word) - 1)]
    return list(dict.fromkeys([*latin, *chinese, *bigrams]))[:40]


def _decode_embedding(value: Any) -> list[float] | None:
    if isinstance(value, list):
        return [float(item) for item in value]
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
        return [float(item) for item in parsed] if isinstance(parsed, list) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


class Store:
    def __init__(self, filename: str | Path | None = None) -> None:
        resolved = str(filename or (ensure_data_dirs() / "memora.db"))
        self.db = sqlite3.connect(resolved, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.fts_enabled = False
        with self.lock:
            self.db.executescript(SCHEMA)
            self._migrate_schema()
            self.db.commit()

    def _migrate_schema(self) -> None:
        user_columns = {row["name"] for row in self._all("PRAGMA table_info(users)")}
        phone_column = next(
            (row for row in self._all("PRAGMA table_info(users)") if row["name"] == "phone"),
            None,
        )
        if phone_column and int(phone_column["notnull"]):
            self._rebuild_users_with_optional_phone(user_columns)
            user_columns = {row["name"] for row in self._all("PRAGMA table_info(users)")}
        if "username" not in user_columns:
            self.db.execute("ALTER TABLE users ADD COLUMN username TEXT")
        if "password_hash" not in user_columns:
            self.db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username COLLATE NOCASE) WHERE username IS NOT NULL"
        )
        conversation_columns = {row["name"] for row in self._all("PRAGMA table_info(conversations)")}
        if "project_id" not in conversation_columns:
            self.db.execute(
                "ALTER TABLE conversations ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE"
            )
        if "workspace_id" not in conversation_columns:
            self.db.execute("ALTER TABLE conversations ADD COLUMN workspace_id INTEGER")
        if "created_by" not in conversation_columns:
            self.db.execute("ALTER TABLE conversations ADD COLUMN created_by INTEGER")
        project_columns = {row["name"] for row in self._all("PRAGMA table_info(projects)")}
        if "workspace_id" not in project_columns:
            self.db.execute("ALTER TABLE projects ADD COLUMN workspace_id INTEGER")
        if "created_by" not in project_columns:
            self.db.execute("ALTER TABLE projects ADD COLUMN created_by INTEGER")
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id,updated_at DESC)"
        )
        message_columns = {row["name"] for row in self._all("PRAGMA table_info(messages)")}
        if "execution_id" not in message_columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN execution_id TEXT")
        self.db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_execution_role
            ON messages(execution_id,role) WHERE execution_id IS NOT NULL"""
        )
        artifact_columns = {row["name"] for row in self._all("PRAGMA table_info(artifacts)")}
        if "execution_id" not in artifact_columns:
            self.db.execute("ALTER TABLE artifacts ADD COLUMN execution_id TEXT")
        self.db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_execution
            ON artifacts(execution_id) WHERE execution_id IS NOT NULL"""
        )
        email_columns = {row["name"] for row in self._all("PRAGMA table_info(email_deliveries)")}
        if "resolved_at" not in email_columns:
            self.db.execute("ALTER TABLE email_deliveries ADD COLUMN resolved_at TEXT")
        if "resolution" not in email_columns:
            self.db.execute("ALTER TABLE email_deliveries ADD COLUMN resolution TEXT")
        document_columns = {row["name"] for row in self._all("PRAGMA table_info(documents)")}
        if "project_id" not in document_columns:
            self.db.execute(
                "ALTER TABLE documents ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE"
            )
        if "meeting_id" not in document_columns:
            self.db.execute("ALTER TABLE documents ADD COLUMN meeting_id INTEGER")
        if "idempotency_key" not in document_columns:
            self.db.execute("ALTER TABLE documents ADD COLUMN idempotency_key TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_documents_meeting ON documents(meeting_id,id)")
        self.db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_meeting_idempotency
            ON documents(meeting_id,idempotency_key) WHERE idempotency_key IS NOT NULL"""
        )
        chunk_columns = {row["name"] for row in self._all("PRAGMA table_info(document_chunks)")}
        if "heading" not in chunk_columns:
            self.db.execute("ALTER TABLE document_chunks ADD COLUMN heading TEXT NOT NULL DEFAULT ''")
        if "embedding_json" not in chunk_columns:
            self.db.execute("ALTER TABLE document_chunks ADD COLUMN embedding_json TEXT")
        meeting_columns = {row["name"] for row in self._all("PRAGMA table_info(meetings)")}
        if "project_id" not in meeting_columns:
            self.db.execute(
                "ALTER TABLE meetings ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL"
            )
        unassigned = self._one("SELECT COUNT(*) AS count FROM meetings WHERE project_id IS NULL")
        if unassigned and unassigned["count"]:
            project = self._one("SELECT * FROM projects WHERE name='默认项目' ORDER BY id LIMIT 1")
            if not project:
                cursor = self.db.execute(
                    "INSERT INTO projects(name,description) VALUES (?,?)",
                    ("默认项目", "升级前已有的会议资料"),
                )
                project_id = cursor.lastrowid
            else:
                project_id = project["id"]
            self.db.execute("UPDATE meetings SET project_id=? WHERE project_id IS NULL", (project_id,))
        memory_columns = {row["name"] for row in self._all("PRAGMA table_info(memories)")}
        memory_migrations = {
            "scope_type": "ALTER TABLE memories ADD COLUMN scope_type TEXT NOT NULL DEFAULT 'ordinary'",
            "project_id": "ALTER TABLE memories ADD COLUMN project_id INTEGER",
            "importance": "ALTER TABLE memories ADD COLUMN importance INTEGER NOT NULL DEFAULT 3",
            "pinned": "ALTER TABLE memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
            "use_count": "ALTER TABLE memories ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0",
            "last_used_at": "ALTER TABLE memories ADD COLUMN last_used_at TEXT",
            "updated_at": "ALTER TABLE memories ADD COLUMN updated_at TEXT",
            "confidence": "ALTER TABLE memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.8",
            "valid_from": "ALTER TABLE memories ADD COLUMN valid_from TEXT",
            "valid_until": "ALTER TABLE memories ADD COLUMN valid_until TEXT",
            "supersedes_id": "ALTER TABLE memories ADD COLUMN supersedes_id INTEGER",
            "status": "ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "sensitivity": "ALTER TABLE memories ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'private'",
            "embedding_json": "ALTER TABLE memories ADD COLUMN embedding_json TEXT",
            "workspace_id": "ALTER TABLE memories ADD COLUMN workspace_id INTEGER",
            "created_by": "ALTER TABLE memories ADD COLUMN created_by INTEGER",
        }
        for column, statement in memory_migrations.items():
            if column not in memory_columns:
                self.db.execute(statement)
        self.db.execute(
            """UPDATE memories SET project_id=(
              SELECT conversation.project_id FROM messages message
              JOIN conversations conversation ON conversation.id=message.conversation_id
              WHERE source_type='chat' AND message.id=memories.source_id
            ) WHERE source_type='chat'"""
        )
        self.db.execute(
            """UPDATE memories SET project_id=(
              SELECT meeting.project_id FROM meetings meeting
              WHERE source_type='meeting' AND meeting.id=memories.source_id
            ) WHERE source_type='meeting'"""
        )
        self.db.execute(
            "UPDATE memories SET scope_type=CASE WHEN project_id IS NULL THEN 'ordinary' ELSE 'project' END"
        )
        self.db.execute("UPDATE memories SET updated_at=COALESCE(updated_at,created_at)")
        for memory in self._all("SELECT id,type,subject,content,scope_type,project_id FROM memories"):
            self.db.execute(
                "UPDATE memories SET fingerprint=? WHERE id=?",
                (self._memory_fingerprint(memory), memory["id"]),
            )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope_type,project_id,pinned,importance,id DESC)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(scope_type,project_id,status,valid_until)"
        )
        try:
            self.db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(chunk_id UNINDEXED,tokens)"
            )
            self.fts_enabled = True
            self._rebuild_chunk_fts()
        except sqlite3.OperationalError:
            self.fts_enabled = False

    def _rebuild_users_with_optional_phone(self, columns: set[str]) -> None:
        username = "username" if "username" in columns else "NULL"
        password_hash = "password_hash" if "password_hash" in columns else "NULL"
        self.db.commit()
        self.db.execute("PRAGMA foreign_keys = OFF")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("DROP TABLE IF EXISTS users_optional_phone_migration")
            self.db.execute(
                """CREATE TABLE users_optional_phone_migration (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE,
                  username TEXT COLLATE NOCASE, password_hash TEXT,
                  display_name TEXT NOT NULL DEFAULT '',
                  role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin','member')),
                  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT
                )"""
            )
            self.db.execute(
                f"""INSERT INTO users_optional_phone_migration(
                id,phone,username,password_hash,display_name,role,status,created_at,updated_at,last_login_at)
                SELECT id,phone,{username},{password_hash},display_name,role,status,
                created_at,updated_at,last_login_at FROM users"""
            )
            self.db.execute("DROP TABLE users")
            self.db.execute("ALTER TABLE users_optional_phone_migration RENAME TO users")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        finally:
            self.db.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row = self.db.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.db.execute(sql, params).fetchall()]

    @staticmethod
    def _chunk_search_tokens(content: str, heading: str = "") -> str:
        return " ".join(tokenize(f"{heading} {heading} {content}"))

    def _rebuild_chunk_fts(self) -> None:
        if not self.fts_enabled:
            return
        self.db.execute("DELETE FROM document_chunks_fts")
        rows = self._all("SELECT id,heading,content FROM document_chunks")
        if rows:
            self.db.executemany(
                "INSERT INTO document_chunks_fts(chunk_id,tokens) VALUES (?,?)",
                [
                    (row["id"], self._chunk_search_tokens(row["content"], row.get("heading") or ""))
                    for row in rows
                ],
            )

    def get_setting(self, key: str) -> str | None:
        with self.lock:
            row = self._one("SELECT value FROM app_settings WHERE key=?", (key,))
            return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.lock:
            self.db.execute(
                """INSERT INTO app_settings(key,value) VALUES (?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
                (key, value),
            )
            self.db.commit()

    def delete_setting(self, key: str) -> bool:
        with self.lock:
            cursor = self.db.execute("DELETE FROM app_settings WHERE key=?", (key,))
            self.db.commit()
            return cursor.rowcount > 0

    def sms_cooldown_remaining(self, phone: str, cooldown_seconds: int) -> int:
        with self.lock:
            row = self._one(
                "SELECT created_at FROM sms_login_codes WHERE phone=? ORDER BY id DESC LIMIT 1",
                (phone,),
            )
            if not row:
                return 0
            try:
                created_at = datetime.fromisoformat(str(row["created_at"]))
            except ValueError:
                return 0
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            elapsed = (datetime.now(UTC) - created_at).total_seconds()
            return max(0, math.ceil(cooldown_seconds - elapsed))

    def create_sms_code(
        self, phone: str, code_hash: str, request_ip: str, expires_at: datetime
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            self.db.execute(
                "UPDATE sms_login_codes SET consumed_at=? WHERE phone=? AND consumed_at IS NULL",
                (now, phone),
            )
            cursor = self.db.execute(
                """INSERT INTO sms_login_codes(
                phone,code_hash,request_ip,expires_at,created_at) VALUES (?,?,?,?,?)""",
                (phone, code_hash, request_ip, expires_at.isoformat(), now),
            )
            self.db.execute(
                "DELETE FROM sms_login_codes WHERE expires_at<?",
                ((datetime.now(UTC) - timedelta(days=1)).isoformat(),),
            )
            self.db.commit()
            return self._one("SELECT * FROM sms_login_codes WHERE id=?", (cursor.lastrowid,)) or {}

    def verify_sms_code(self, phone: str, code_hash: str, max_attempts: int) -> str:
        now = datetime.now(UTC)
        with self.lock:
            row = self._one(
                """SELECT * FROM sms_login_codes
                WHERE phone=? AND consumed_at IS NULL ORDER BY id DESC LIMIT 1""",
                (phone,),
            )
            if not row:
                return "missing"
            try:
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
            except ValueError:
                expires_at = now - timedelta(seconds=1)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                self.db.execute(
                    "UPDATE sms_login_codes SET consumed_at=? WHERE id=?", (now.isoformat(), row["id"])
                )
                self.db.commit()
                return "expired"
            if int(row["attempts"]) >= max_attempts:
                return "locked"
            if not hmac.compare_digest(str(row["code_hash"]), code_hash):
                attempts = int(row["attempts"]) + 1
                self.db.execute("UPDATE sms_login_codes SET attempts=? WHERE id=?", (attempts, row["id"]))
                self.db.commit()
                return "locked" if attempts >= max_attempts else "invalid"
            self.db.execute(
                "UPDATE sms_login_codes SET consumed_at=? WHERE id=?", (now.isoformat(), row["id"])
            )
            self.db.commit()
            return "valid"

    def get_or_create_user_for_login(self, phone: str) -> tuple[dict[str, Any], bool]:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            user = self._one("SELECT * FROM users WHERE phone=?", (phone,))
            created = False
            if not user:
                count = self._one("SELECT COUNT(*) AS count FROM users") or {"count": 0}
                role = "admin" if int(count["count"]) == 0 else "member"
                cursor = self.db.execute(
                    """INSERT INTO users(phone,role,status,created_at,updated_at,last_login_at)
                    VALUES (?,?,'active',?,?,?)""",
                    (phone, role, now, now, now),
                )
                user = self._one("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)) or {}
                created = True
            else:
                self.db.execute(
                    "UPDATE users SET last_login_at=?,updated_at=? WHERE id=?", (now, now, user["id"])
                )
                user = self._one("SELECT * FROM users WHERE id=?", (user["id"],)) or {}
            self.db.commit()
            return user, created

    def create_user_for_registration(
        self, username: str, password_hash: str, phone: str | None = None
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            if self._one(
                "SELECT id FROM users WHERE username=? COLLATE NOCASE OR phone=?",
                (username, username),
            ):
                raise ValueError("该账号已被使用")
            if phone and self._one(
                "SELECT id FROM users WHERE phone=? OR username=? COLLATE NOCASE", (phone, phone)
            ):
                raise ValueError("该手机号已绑定其他账号")
            count = self._one("SELECT COUNT(*) AS count FROM users") or {"count": 0}
            role = "admin" if int(count["count"]) == 0 else "member"
            try:
                cursor = self.db.execute(
                    """INSERT INTO users(
                    phone,username,password_hash,role,status,created_at,updated_at,last_login_at)
                    VALUES (?,?,?,?,'active',?,?,?)""",
                    (phone, username, password_hash, role, now, now, now),
                )
                self.db.commit()
            except sqlite3.IntegrityError as error:
                self.db.rollback()
                raise ValueError("账号或手机号已被使用") from error
            return self._one("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)) or {}

    def get_user_by_account(self, account: str) -> dict[str, Any] | None:
        with self.lock:
            return self._one(
                """SELECT * FROM users
                WHERE username=? COLLATE NOCASE OR phone=?
                ORDER BY CASE WHEN username=? COLLATE NOCASE THEN 0 ELSE 1 END LIMIT 1""",
                (account, account, account),
            )

    def set_user_phone(self, user_id: int, phone: str) -> dict[str, Any] | None:
        with self.lock:
            if not self._one("SELECT id FROM users WHERE id=?", (user_id,)):
                return None
            if self._one(
                """SELECT id FROM users WHERE id<>?
                AND (phone=? OR username=? COLLATE NOCASE)""",
                (user_id, phone, phone),
            ):
                raise ValueError("该手机号已绑定其他账号")
            try:
                self.db.execute(
                    "UPDATE users SET phone=?,updated_at=? WHERE id=?",
                    (phone, datetime.now(UTC).isoformat(), user_id),
                )
                self.db.commit()
            except sqlite3.IntegrityError as error:
                self.db.rollback()
                raise ValueError("该手机号已绑定其他账号") from error
            return self._one("SELECT * FROM users WHERE id=?", (user_id,))

    def record_user_login(self, user_id: int) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            self.db.execute(
                "UPDATE users SET last_login_at=?,updated_at=? WHERE id=?",
                (now, now, user_id),
            )
            self.db.commit()
            return self._one("SELECT * FROM users WHERE id=?", (user_id,))

    def set_user_credentials(
        self, user_id: int, username: str, password_hash: str
    ) -> dict[str, Any] | None:
        with self.lock:
            if not self._one("SELECT id FROM users WHERE id=?", (user_id,)):
                return None
            if self._one(
                """SELECT id FROM users WHERE id<>?
                AND (username=? COLLATE NOCASE OR phone=?)""",
                (user_id, username, username),
            ):
                raise ValueError("该账号已被使用")
            try:
                self.db.execute(
                    "UPDATE users SET username=?,password_hash=?,updated_at=? WHERE id=?",
                    (username, password_hash, datetime.now(UTC).isoformat(), user_id),
                )
                self.db.commit()
            except sqlite3.IntegrityError as error:
                self.db.rollback()
                raise ValueError("该账号已被使用") from error
            return self._one("SELECT * FROM users WHERE id=?", (user_id,))

    def revoke_other_auth_sessions(self, user_id: int, current_token_hash: str) -> int:
        with self.lock:
            cursor = self.db.execute(
                """UPDATE auth_sessions SET revoked_at=?
                WHERE user_id=? AND token_hash<>? AND revoked_at IS NULL""",
                (datetime.now(UTC).isoformat(), user_id, current_token_hash),
            )
            self.db.commit()
            return cursor.rowcount

    def create_auth_session(
        self, session_id: str, user_id: int, token_hash: str, expires_at: datetime
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            self.db.execute(
                """INSERT INTO auth_sessions(
                id,user_id,token_hash,expires_at,created_at,last_seen_at) VALUES (?,?,?,?,?,?)""",
                (session_id, user_id, token_hash, expires_at.isoformat(), now, now),
            )
            self.db.execute(
                "DELETE FROM auth_sessions WHERE expires_at<? OR revoked_at IS NOT NULL",
                ((datetime.now(UTC) - timedelta(days=1)).isoformat(),),
            )
            self.db.commit()

    def get_user_by_session(self, token_hash: str) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            user = self._one(
                """SELECT u.* FROM auth_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?
                AND u.status='active'""",
                (token_hash, now),
            )
            if user:
                self.db.execute(
                    "UPDATE auth_sessions SET last_seen_at=? WHERE token_hash=?", (now, token_hash)
                )
                self.db.commit()
            return user

    def revoke_auth_session(self, token_hash: str) -> bool:
        with self.lock:
            cursor = self.db.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (datetime.now(UTC).isoformat(), token_hash),
            )
            self.db.commit()
            return cursor.rowcount > 0

    def list_users(self) -> list[dict[str, Any]]:
        with self.lock:
            return self._all("SELECT * FROM users ORDER BY created_at,id")

    def update_user_role(self, user_id: int, role: str) -> dict[str, Any] | None:
        with self.lock:
            user = self._one("SELECT * FROM users WHERE id=?", (user_id,))
            if not user:
                return None
            if user["role"] == "admin" and role != "admin":
                admins = self._one(
                    "SELECT COUNT(*) AS count FROM users WHERE role='admin' AND status='active'"
                ) or {"count": 0}
                if int(admins["count"]) <= 1:
                    raise ValueError("系统必须至少保留一名管理员")
            self.db.execute(
                "UPDATE users SET role=?,updated_at=? WHERE id=?",
                (role, datetime.now(UTC).isoformat(), user_id),
            )
            self.db.commit()
            return self._one("SELECT * FROM users WHERE id=?", (user_id,))

    def claim_legacy_resources(self, user_id: int) -> None:
        """Assign pre-authentication data that has no owner to the first administrator."""
        now = datetime.now(UTC).isoformat()
        with self.lock:
            self.db.execute(
                "UPDATE projects SET created_by=? WHERE created_by IS NULL",
                (user_id,),
            )
            self.db.execute(
                """INSERT OR IGNORE INTO project_members(
                project_id,user_id,role,created_at,updated_at)
                SELECT p.id,?,'owner',?,? FROM projects p
                WHERE NOT EXISTS(SELECT 1 FROM project_members pm WHERE pm.project_id=p.id)""",
                (user_id, now, now),
            )
            self.db.execute(
                """UPDATE conversations SET created_by=?
                WHERE project_id IS NULL AND created_by IS NULL""",
                (user_id,),
            )
            self.db.execute(
                """UPDATE memories SET created_by=?
                WHERE scope_type='ordinary' AND created_by IS NULL""",
                (user_id,),
            )
            self.db.commit()

    def ensure_user_workspace(self, user_id: int, *, migrate_legacy: bool = False) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            workspace = self._one(
                """SELECT w.*,wm.role AS membership_role FROM workspaces w
                JOIN workspace_members wm ON wm.workspace_id=w.id
                WHERE wm.user_id=? ORDER BY CASE wm.role WHEN 'owner' THEN 0 ELSE 1 END,w.id LIMIT 1""",
                (user_id,),
            )
            if not workspace:
                user = self._one(
                    "SELECT phone,username,display_name FROM users WHERE id=?", (user_id,)
                ) or {}
                label = str(user.get("display_name") or "").strip()
                if not label:
                    username = str(user.get("username") or "").strip()
                    phone = str(user.get("phone") or "")
                    label = (
                        f"{username} 的工作空间"
                        if username
                        else (f"{phone[-4:]} 的工作空间" if len(phone) >= 4 else "我的工作空间")
                    )
                cursor = self.db.execute(
                    """INSERT INTO workspaces(name,owner_user_id,created_at,updated_at)
                    VALUES (?,?,?,?)""",
                    (label, user_id, now, now),
                )
                workspace_id = int(cursor.lastrowid)
                self.db.execute(
                    """INSERT INTO workspace_members(workspace_id,user_id,role,created_at,updated_at)
                    VALUES (?,?,'owner',?,?)""",
                    (workspace_id, user_id, now, now),
                )
                workspace = self._one("SELECT * FROM workspaces WHERE id=?", (workspace_id,)) or {}
                workspace["membership_role"] = "owner"
            workspace_id = int(workspace["id"])
            if migrate_legacy:
                self.db.execute(
                    "UPDATE projects SET workspace_id=?,created_by=COALESCE(created_by,?) WHERE workspace_id IS NULL",
                    (workspace_id, user_id),
                )
                self.db.execute(
                    """UPDATE conversations SET workspace_id=(
                    SELECT p.workspace_id FROM projects p WHERE p.id=conversations.project_id)
                    WHERE project_id IS NOT NULL AND workspace_id IS NULL"""
                )
                self.db.execute(
                    """UPDATE conversations SET workspace_id=?,created_by=COALESCE(created_by,?)
                    WHERE workspace_id IS NULL""",
                    (workspace_id, user_id),
                )
                self.db.execute(
                    """UPDATE memories SET workspace_id=(
                    SELECT p.workspace_id FROM projects p WHERE p.id=memories.project_id)
                    WHERE project_id IS NOT NULL AND workspace_id IS NULL"""
                )
                self.db.execute(
                    """UPDATE memories SET workspace_id=?,created_by=COALESCE(created_by,?)
                    WHERE workspace_id IS NULL""",
                    (workspace_id, user_id),
                )
                projects = self._all("SELECT id FROM projects WHERE workspace_id=?", (workspace_id,))
                self.db.executemany(
                    """INSERT OR IGNORE INTO project_members(
                    project_id,user_id,role,created_at,updated_at) VALUES (?,?,'owner',?,?)""",
                    [(item["id"], user_id, now, now) for item in projects],
                )
                for memory in self._all(
                    """SELECT id,type,subject,content,scope_type,project_id,workspace_id,created_by
                    FROM memories WHERE workspace_id=?""",
                    (workspace_id,),
                ):
                    self.db.execute(
                        "UPDATE memories SET fingerprint=? WHERE id=?",
                        (self._memory_fingerprint(memory), memory["id"]),
                    )
            self.db.commit()
            return self.get_workspace(workspace_id, user_id) or workspace

    def get_workspace(self, workspace_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        with self.lock:
            params: tuple[Any, ...] = (user_id, workspace_id) if user_id is not None else (workspace_id,)
            role_select = (
                "(SELECT role FROM workspace_members WHERE workspace_id=w.id AND user_id=?) AS membership_role,"
                if user_id is not None
                else "NULL AS membership_role,"
            )
            return self._one(
                f"""SELECT w.*,{role_select}
                (SELECT COUNT(*) FROM workspace_members wm WHERE wm.workspace_id=w.id) AS member_count,
                (SELECT COUNT(*) FROM projects p WHERE p.workspace_id=w.id) AS project_count
                FROM workspaces w WHERE w.id=?""",  # noqa: S608
                params,
            )

    def list_workspaces(self, user_id: int) -> list[dict[str, Any]]:
        with self.lock:
            return self._all(
                """SELECT w.*,wm.role AS membership_role,
                (SELECT COUNT(*) FROM workspace_members x WHERE x.workspace_id=w.id) AS member_count,
                (SELECT COUNT(*) FROM projects p WHERE p.workspace_id=w.id AND (
                  wm.role IN ('owner','admin') OR EXISTS(
                    SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.user_id=wm.user_id
                  ))) AS project_count
                FROM workspaces w JOIN workspace_members wm ON wm.workspace_id=w.id
                WHERE wm.user_id=? ORDER BY CASE wm.role WHEN 'owner' THEN 0 ELSE 1 END,w.updated_at DESC""",
                (user_id,),
            )

    def create_workspace(self, user_id: int, name: str) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            cursor = self.db.execute(
                "INSERT INTO workspaces(name,owner_user_id,created_at,updated_at) VALUES (?,?,?,?)",
                (name, user_id, now, now),
            )
            workspace_id = int(cursor.lastrowid)
            self.db.execute(
                """INSERT INTO workspace_members(workspace_id,user_id,role,created_at,updated_at)
                VALUES (?,?,'owner',?,?)""",
                (workspace_id, user_id, now, now),
            )
            self.db.commit()
            return self.get_workspace(workspace_id, user_id) or {}

    def workspace_role(self, workspace_id: int, user_id: int) -> str | None:
        with self.lock:
            row = self._one(
                "SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",
                (workspace_id, user_id),
            )
            return str(row["role"]) if row else None

    def list_workspace_members(self, workspace_id: int) -> list[dict[str, Any]]:
        with self.lock:
            return self._all(
                """SELECT u.id,u.phone,u.display_name,u.status,wm.role,wm.created_at
                FROM workspace_members wm JOIN users u ON u.id=wm.user_id
                WHERE wm.workspace_id=? ORDER BY CASE wm.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,u.id""",
                (workspace_id,),
            )

    def add_workspace_member(
        self, workspace_id: int, phone: str, role: str = "member"
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            user = self._one("SELECT * FROM users WHERE phone=? AND status='active'", (phone,))
            if not user:
                return None
            self.db.execute(
                """INSERT INTO workspace_members(workspace_id,user_id,role,created_at,updated_at)
                VALUES (?,?,?,?,?) ON CONFLICT(workspace_id,user_id) DO UPDATE SET
                role=CASE
                  WHEN workspace_members.role='owner' THEN 'owner'
                  WHEN workspace_members.role='admin' AND excluded.role='member' THEN 'admin'
                  ELSE excluded.role END,
                updated_at=excluded.updated_at""",
                (workspace_id, user["id"], role, now, now),
            )
            self.db.commit()
            return self._one(
                """SELECT u.id,u.phone,u.display_name,u.status,wm.role,wm.created_at
                FROM workspace_members wm JOIN users u ON u.id=wm.user_id
                WHERE wm.workspace_id=? AND wm.user_id=?""",
                (workspace_id, user["id"]),
            )

    def remove_workspace_member(self, workspace_id: int, user_id: int) -> bool:
        with self.lock:
            row = self._one(
                "SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",
                (workspace_id, user_id),
            )
            if not row or row["role"] == "owner":
                return False
            self.db.execute(
                "DELETE FROM project_members WHERE user_id=? AND project_id IN (SELECT id FROM projects WHERE workspace_id=?)",
                (user_id, workspace_id),
            )
            cursor = self.db.execute(
                "DELETE FROM workspace_members WHERE workspace_id=? AND user_id=?",
                (workspace_id, user_id),
            )
            self.db.commit()
            return cursor.rowcount > 0

    def project_role(
        self, project_id: int, user_id: int, workspace_id: int | None = None
    ) -> str | None:
        with self.lock:
            project = self._one("SELECT id FROM projects WHERE id=?", (project_id,))
            if not project:
                return None
            member = self._one(
                "SELECT role FROM project_members WHERE project_id=? AND user_id=?",
                (project_id, user_id),
            )
            return str(member["role"]) if member else None

    def list_project_members(self, project_id: int) -> list[dict[str, Any]]:
        with self.lock:
            return self._all(
                """SELECT u.id,u.phone,u.display_name,u.status,pm.role,pm.created_at
                FROM project_members pm JOIN users u ON u.id=pm.user_id
                WHERE pm.project_id=? ORDER BY CASE pm.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,u.id""",
                (project_id,),
            )

    def set_project_member(self, project_id: int, user_id: int, role: str) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            user = self._one("SELECT * FROM users WHERE id=? AND status='active'", (user_id,))
            project = self._one("SELECT id FROM projects WHERE id=?", (project_id,))
            if not user or not project:
                return None
            self.db.execute(
                """INSERT INTO project_members(project_id,user_id,role,created_at,updated_at)
                VALUES (?,?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET
                role=excluded.role,updated_at=excluded.updated_at""",
                (project_id, user_id, role, now, now),
            )
            self.db.commit()
            return self._one(
                """SELECT u.id,u.phone,u.display_name,u.status,pm.role,pm.created_at
                FROM project_members pm JOIN users u ON u.id=pm.user_id
                WHERE pm.project_id=? AND pm.user_id=?""",
                (project_id, user_id),
            )

    def remove_project_member(self, project_id: int, user_id: int) -> bool:
        with self.lock:
            row = self._one(
                "SELECT role FROM project_members WHERE project_id=? AND user_id=?",
                (project_id, user_id),
            )
            if not row or row["role"] == "owner":
                return False
            cursor = self.db.execute(
                "DELETE FROM project_members WHERE project_id=? AND user_id=?", (project_id, user_id)
            )
            self.db.commit()
            return cursor.rowcount > 0

    def conversation_role(
        self, conversation_id: int, user_id: int, workspace_id: int | None = None
    ) -> str | None:
        with self.lock:
            conversation = self._one(
                "SELECT project_id,workspace_id,created_by FROM conversations WHERE id=?",
                (conversation_id,),
            )
            if not conversation:
                return None
            if conversation.get("project_id") is not None:
                return self.project_role(int(conversation["project_id"]), user_id, workspace_id)
            return "owner" if conversation.get("created_by") == user_id else None

    def meeting_role(
        self, meeting_id: int, user_id: int, workspace_id: int | None = None
    ) -> str | None:
        with self.lock:
            meeting = self._one("SELECT project_id FROM meetings WHERE id=?", (meeting_id,))
            if not meeting or meeting.get("project_id") is None:
                return None
            return self.project_role(int(meeting["project_id"]), user_id, workspace_id)

    def document_role(
        self, document_id: int, user_id: int, workspace_id: int | None = None
    ) -> str | None:
        with self.lock:
            document = self._one(
                "SELECT conversation_id,project_id,meeting_id FROM documents WHERE id=?",
                (document_id,),
            )
            if not document:
                return None
            if document.get("project_id") is not None:
                return self.project_role(int(document["project_id"]), user_id, workspace_id)
            if document.get("meeting_id") is not None:
                return self.meeting_role(int(document["meeting_id"]), user_id, workspace_id)
            if document.get("conversation_id") is not None:
                return self.conversation_role(int(document["conversation_id"]), user_id, workspace_id)
            return None

    def todo_role(
        self, todo_id: int, user_id: int, workspace_id: int | None = None
    ) -> str | None:
        with self.lock:
            row = self._one(
                """SELECT m.project_id FROM todos t JOIN meetings m ON m.id=t.meeting_id
                WHERE t.id=?""",
                (todo_id,),
            )
            if not row or row.get("project_id") is None:
                return None
            return self.project_role(int(row["project_id"]), user_id, workspace_id)

    def memory_role(
        self, memory_id: int, user_id: int, workspace_id: int | None = None
    ) -> str | None:
        with self.lock:
            memory = self._one(
                "SELECT project_id,workspace_id,created_by FROM memories WHERE id=?", (memory_id,)
            )
            if not memory:
                return None
            if memory.get("project_id") is not None:
                return self.project_role(int(memory["project_id"]), user_id, workspace_id)
            return "owner" if memory.get("created_by") == user_id else None

    def artifact_role(
        self, artifact_id: int, user_id: int, workspace_id: int | None = None
    ) -> str | None:
        with self.lock:
            row = self._one("SELECT conversation_id FROM artifacts WHERE id=?", (artifact_id,))
            if not row or row.get("conversation_id") is None:
                return None
            return self.conversation_role(int(row["conversation_id"]), user_id, workspace_id)

    def list_projects(
        self, workspace_id: int | None = None, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        with self.lock:
            where = ""
            params: tuple[Any, ...] = ()
            access_role = "NULL AS access_role,"
            if user_id is not None:
                where = """WHERE EXISTS(
                SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.user_id=?)"""
                params = (user_id,)
                access_role = """(SELECT pm.role FROM project_members pm
                WHERE pm.project_id=p.id AND pm.user_id=?) AS access_role,"""
                params = (user_id, *params)
            return self._all(
                f"""SELECT p.*,{access_role}
                (SELECT COUNT(*) FROM meetings m WHERE m.project_id=p.id) AS meeting_count,
                (SELECT COUNT(*) FROM documents d WHERE d.project_id=p.id AND d.kind='knowledge') AS document_count,
                (SELECT COUNT(*) FROM conversations c WHERE c.project_id=p.id) AS conversation_count,
                (SELECT COUNT(*) FROM todos t JOIN meetings m ON m.id=t.meeting_id
                 WHERE m.project_id=p.id AND t.status='open') AS open_todo_count
                FROM projects p {where} ORDER BY p.updated_at DESC,p.id DESC""",  # noqa: S608
                params,
            )

    def create_project(
        self,
        name: str,
        description: str = "",
        *,
        workspace_id: int | None = None,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self.lock:
            cursor = self.db.execute(
                "INSERT INTO projects(workspace_id,created_by,name,description) VALUES (?,?,?,?)",
                (workspace_id, created_by, name, description),
            )
            if created_by is not None:
                self.db.execute(
                    """INSERT INTO project_members(project_id,user_id,role,created_at,updated_at)
                    VALUES (?,?,'owner',?,?)""",
                    (cursor.lastrowid, created_by, now, now),
                )
            self.db.commit()
            return self.get_project(cursor.lastrowid) or {}

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        with self.lock:
            return self._one(
                """SELECT p.*,
                (SELECT COUNT(*) FROM meetings m WHERE m.project_id=p.id) AS meeting_count,
                (SELECT COUNT(*) FROM documents d WHERE d.project_id=p.id AND d.kind='knowledge') AS document_count,
                (SELECT COUNT(*) FROM conversations c WHERE c.project_id=p.id) AS conversation_count,
                (SELECT COUNT(*) FROM todos t JOIN meetings m ON m.id=t.meeting_id
                 WHERE m.project_id=p.id AND t.status='open') AS open_todo_count
                ,(SELECT COUNT(*) FROM project_members pm WHERE pm.project_id=p.id) AS member_count
                FROM projects p WHERE p.id=?""",
                (project_id,),
            )

    def rename_project(self, project_id: int, name: str) -> dict[str, Any] | None:
        with self.lock:
            cursor = self.db.execute(
                "UPDATE projects SET name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (name, project_id),
            )
            self.db.commit()
            if cursor.rowcount == 0:
                return None
            return self.get_project(project_id)

    def get_or_create_default_project(
        self, workspace_id: int | None = None, user_id: int | None = None
    ) -> dict[str, Any]:
        with self.lock:
            project = self._one(
                """SELECT * FROM projects WHERE name='默认项目' AND workspace_id IS ?
                ORDER BY id LIMIT 1""",
                (workspace_id,),
            )
            if project:
                return project
            return self.create_project(
                "默认项目", "未指定项目的会议资料", workspace_id=workspace_id, created_by=user_id
            )

    def touch_project(self, project_id: int) -> None:
        with self.lock:
            self.db.execute("UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
            self.db.commit()

    def delete_project(self, project_id: int) -> bool:
        with self.lock:
            project = self._one("SELECT id FROM projects WHERE id=?", (project_id,))
            if not project:
                return False
            meetings = self._all("SELECT id,document_id FROM meetings WHERE project_id=?", (project_id,))
            meeting_ids = [item["id"] for item in meetings]
            chat_message_ids = [
                item["id"]
                for item in self._all(
                    """SELECT message.id FROM messages message JOIN conversations conversation
                    ON conversation.id=message.conversation_id WHERE conversation.project_id=?""",
                    (project_id,),
                )
            ]
            if chat_message_ids:
                placeholders = ",".join("?" for _ in chat_message_ids)
                self.db.execute(
                    f"DELETE FROM memories WHERE source_type='chat' AND source_id IN ({placeholders})",  # noqa: S608
                    tuple(chat_message_ids),
                )
            if meeting_ids:
                placeholders = ",".join("?" for _ in meeting_ids)
                self.db.execute(
                    f"DELETE FROM memories WHERE source_type='meeting' AND source_id IN ({placeholders})",  # noqa: S608
                    tuple(meeting_ids),
                )
                self.db.execute(
                    f"DELETE FROM todos WHERE meeting_id IN ({placeholders})",  # noqa: S608
                    tuple(meeting_ids),
                )
                self.db.executemany(
                    "DELETE FROM documents WHERE id=?", [(item["document_id"],) for item in meetings]
                )
            self.db.execute("DELETE FROM memories WHERE project_id=?", (project_id,))
            self.db.execute("DELETE FROM documents WHERE project_id=? AND kind='knowledge'", (project_id,))
            cursor = self.db.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self.db.commit()
            return cursor.rowcount > 0

    def list_conversations(
        self, workspace_id: int | None = None, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        with self.lock:
            if user_id is not None:
                return self._all(
                    """SELECT * FROM conversations WHERE project_id IS NULL
                    AND created_by=? ORDER BY updated_at DESC,id DESC""",
                    (user_id,),
                )
            return self._all(
                "SELECT * FROM conversations WHERE project_id IS NULL ORDER BY updated_at DESC,id DESC"
            )

    def list_project_conversations(self, project_id: int) -> list[dict[str, Any]]:
        with self.lock:
            return self._all(
                "SELECT * FROM conversations WHERE project_id=? ORDER BY updated_at DESC,id DESC",
                (project_id,),
            )

    def create_conversation(
        self,
        title: str = "新对话",
        project_id: int | None = None,
        *,
        workspace_id: int | None = None,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if project_id is not None and workspace_id is None:
                project = self._one("SELECT workspace_id FROM projects WHERE id=?", (project_id,))
                workspace_id = project.get("workspace_id") if project else None
            cursor = self.db.execute(
                """INSERT INTO conversations(project_id,workspace_id,created_by,title)
                VALUES (?,?,?,?)""",
                (project_id, workspace_id, created_by, title),
            )
            if project_id is not None:
                self.db.execute("UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
            self.db.commit()
            return self._one("SELECT * FROM conversations WHERE id=?", (cursor.lastrowid,)) or {}

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        with self.lock:
            return self._one("SELECT * FROM conversations WHERE id=?", (conversation_id,))

    def delete_conversation(self, conversation_id: int) -> bool:
        with self.lock:
            message_ids = [
                item["id"]
                for item in self._all("SELECT id FROM messages WHERE conversation_id=?", (conversation_id,))
            ]
            if message_ids:
                placeholders = ",".join("?" for _ in message_ids)
                self.db.execute(
                    f"DELETE FROM memories WHERE source_type='chat' AND source_id IN ({placeholders})",  # noqa: S608
                    tuple(message_ids),
                )
            cursor = self.db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
            self.db.commit()
            return cursor.rowcount > 0

    def list_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,))
            return [_decode_json(row, ["sources_json"]) or {} for row in rows]

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        sources: list[dict[str, Any]] | None = None,
        artifact_id: int | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            cursor = self.db.execute(
                """INSERT OR IGNORE INTO messages(
                conversation_id,role,content,sources_json,artifact_id,execution_id) VALUES (?,?,?,?,?,?)""",
                (
                    conversation_id,
                    role,
                    content,
                    json.dumps(sources or [], ensure_ascii=False),
                    artifact_id,
                    execution_id,
                ),
            )
            if cursor.rowcount == 0 and execution_id:
                row = self._one(
                    "SELECT * FROM messages WHERE execution_id=? AND role=?",
                    (execution_id, role),
                )
                return _decode_json(row, ["sources_json"]) or {}
            self.db.execute(
                "UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conversation_id,)
            )
            conversation = self._one("SELECT project_id FROM conversations WHERE id=?", (conversation_id,))
            if conversation and conversation["project_id"] is not None:
                self.db.execute(
                    "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (conversation["project_id"],),
                )
            count = self._one(
                "SELECT COUNT(*) AS count FROM messages WHERE conversation_id=?", (conversation_id,)
            )["count"]
            if role == "user" and count <= 2:
                self.db.execute(
                    "UPDATE conversations SET title=? WHERE id=?",
                    ((content.strip()[:28] or "新对话"), conversation_id),
                )
            self.db.commit()
            row = self._one("SELECT * FROM messages WHERE id=?", (cursor.lastrowid,))
            return _decode_json(row, ["sources_json"]) or {}

    def add_document(
        self,
        *,
        conversation_id: int | None = None,
        project_id: int | None = None,
        meeting_id: int | None = None,
        idempotency_key: str | None = None,
        name: str,
        mime_type: str,
        kind: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            cursor = self.db.execute(
                """INSERT INTO documents(conversation_id,project_id,meeting_id,idempotency_key,name,mime_type,
                kind,text_content,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    conversation_id,
                    project_id,
                    meeting_id,
                    idempotency_key,
                    name,
                    mime_type,
                    kind,
                    text,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            if project_id is not None:
                self.db.execute("UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
            self.db.commit()
            return (
                _decode_json(
                    self._one("SELECT * FROM documents WHERE id=?", (cursor.lastrowid,)), ["metadata_json"]
                )
                or {}
            )

    def add_chunks(self, document_id: int, chunks: list[dict[str, Any]]) -> None:
        with self.lock:
            self.db.executemany(
                """INSERT INTO document_chunks(document_id,page_number,chunk_index,heading,content)
                VALUES (?,?,?,?,?)""",
                [
                    (
                        document_id,
                        item.get("page_number"),
                        item["index"],
                        item.get("heading", ""),
                        item["content"],
                    )
                    for item in chunks
                ],
            )
            self._rebuild_chunk_fts()
            self.db.commit()

    def set_chunk_embeddings(self, document_id: int, vectors: list[list[float]]) -> None:
        with self.lock:
            rows = self._all(
                "SELECT id FROM document_chunks WHERE document_id=? ORDER BY chunk_index",
                (document_id,),
            )
            if len(rows) != len(vectors):
                return
            self.db.executemany(
                "UPDATE document_chunks SET embedding_json=? WHERE id=?",
                [
                    (json.dumps(vector, separators=(",", ":")), row["id"])
                    for row, vector in zip(rows, vectors, strict=True)
                ],
            )
            self.db.commit()

    def documents_needing_embeddings(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            document_ids = self._all(
                """SELECT DISTINCT document_id FROM document_chunks
                WHERE embedding_json IS NULL OR embedding_json='' ORDER BY document_id LIMIT ?""",
                (limit,),
            )
            return [
                {
                    "document_id": item["document_id"],
                    "chunks": self._all(
                        """SELECT id,heading,content FROM document_chunks
                        WHERE document_id=? ORDER BY chunk_index""",
                        (item["document_id"],),
                    ),
                }
                for item in document_ids
            ]

    def rebuild_full_text_index(self) -> bool:
        with self.lock:
            self._rebuild_chunk_fts()
            self.db.commit()
            return self.fts_enabled

    def memories_needing_embeddings(self, limit: int = 500) -> list[dict[str, Any]]:
        with self.lock:
            return self._all(
                """SELECT id,subject,content FROM memories WHERE status='active'
                AND (embedding_json IS NULL OR embedding_json='') ORDER BY id LIMIT ?""",
                (limit,),
            )

    def list_documents(self, conversation_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all(
                """SELECT id,conversation_id,name,mime_type,kind,status,metadata_json,created_at FROM documents
                WHERE conversation_id=? ORDER BY id DESC""",
                (conversation_id,),
            )
            return [_decode_json(row, ["metadata_json"]) or {} for row in rows]

    def delete_document(self, conversation_id: int, document_id: int) -> bool:
        with self.lock:
            cursor = self.db.execute(
                "DELETE FROM documents WHERE id=? AND conversation_id=? AND kind='knowledge'",
                (document_id, conversation_id),
            )
            self.db.commit()
            return cursor.rowcount > 0

    def list_project_documents(self, project_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all(
                """SELECT id,project_id,name,mime_type,kind,status,metadata_json,created_at FROM documents
                WHERE project_id=? AND kind='knowledge' ORDER BY id DESC""",
                (project_id,),
            )
            return [_decode_json(row, ["metadata_json"]) or {} for row in rows]

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self._one(
                """SELECT id,conversation_id,project_id,meeting_id,idempotency_key,name,mime_type,kind,
                status,text_content,
                metadata_json,created_at FROM documents WHERE id=?""",
                (document_id,),
            )
            return _decode_json(row, ["metadata_json"])

    def get_meeting_document_by_idempotency_key(
        self, meeting_id: int, idempotency_key: str
    ) -> dict[str, Any] | None:
        with self.lock:
            row = self._one(
                "SELECT id FROM documents WHERE meeting_id=? AND idempotency_key=?",
                (meeting_id, idempotency_key),
            )
            return self.get_document(row["id"]) if row else None

    def update_document_content(
        self, document_id: int, content: str, chunks: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        with self.lock:
            document = self.get_document(document_id)
            if not document:
                return None
            metadata = dict(document.get("metadata") or {})
            metadata.update(
                {
                    "characters": len(content),
                    "chunks": len(chunks),
                    "edited": True,
                }
            )
            self.db.execute(
                "UPDATE documents SET text_content=?,metadata_json=? WHERE id=?",
                (content, json.dumps(metadata, ensure_ascii=False), document_id),
            )
            self.db.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
            if chunks:
                self.db.executemany(
                    """INSERT INTO document_chunks(document_id,page_number,chunk_index,heading,content)
                    VALUES (?,?,?,?,?)""",
                    [
                        (
                            document_id,
                            item.get("page_number"),
                            item["index"],
                            item.get("heading", ""),
                            item["content"],
                        )
                        for item in chunks
                    ],
                )
            self._rebuild_chunk_fts()
            if document.get("conversation_id") is not None:
                self.db.execute(
                    "UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (document["conversation_id"],),
                )
            project = self._one(
                """SELECT COALESCE(d.project_id,m.project_id) AS project_id
                FROM documents d LEFT JOIN meetings m
                  ON m.document_id=d.id OR m.id=d.meeting_id
                WHERE d.id=? LIMIT 1""",
                (document_id,),
            )
            if project and project.get("project_id") is not None:
                self.db.execute(
                    "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (project["project_id"],),
                )
            self.db.commit()
            return self.get_document(document_id)

    def list_meeting_documents(self, meeting_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all(
                """SELECT d.id,d.project_id,d.meeting_id,d.name,d.mime_type,d.kind,d.status,
                d.metadata_json,d.created_at,
                CASE WHEN d.id=m.document_id THEN 1 ELSE 0 END AS is_source
                FROM meetings m JOIN documents d ON d.meeting_id=m.id OR d.id=m.document_id
                WHERE m.id=? ORDER BY is_source DESC,d.id DESC""",
                (meeting_id,),
            )
            return [_decode_json(row, ["metadata_json"]) or {} for row in rows]

    def rename_meeting_document(self, meeting_id: int, document_id: int, name: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._one(
                """SELECT d.id FROM documents d JOIN meetings m ON m.id=?
                WHERE d.id=? AND (d.meeting_id=m.id OR d.id=m.document_id)""",
                (meeting_id, document_id),
            )
            if not row:
                return None
            self.db.execute("UPDATE documents SET name=? WHERE id=?", (name, document_id))
            self.db.execute(
                "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=(SELECT project_id FROM meetings WHERE id=?)",
                (meeting_id,),
            )
            self.db.commit()
            return self.get_document(document_id)

    def delete_meeting_document(self, meeting_id: int, document_id: int) -> bool:
        with self.lock:
            meeting = self._one("SELECT id,document_id,project_id FROM meetings WHERE id=?", (meeting_id,))
            if not meeting or meeting["document_id"] == document_id:
                return False
            cursor = self.db.execute(
                "DELETE FROM documents WHERE id=? AND meeting_id=? AND kind='meeting'",
                (document_id, meeting_id),
            )
            if cursor.rowcount and meeting["project_id"] is not None:
                self.db.execute(
                    "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (meeting["project_id"],),
                )
            self.db.commit()
            return cursor.rowcount > 0

    def project_background_documents(
        self, project_id: int, max_characters: int = 24_000
    ) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all(
                """SELECT id,name,text_content FROM documents
                WHERE project_id=? AND kind='knowledge' ORDER BY id DESC""",
                (project_id,),
            )
        result: list[dict[str, Any]] = []
        remaining = max_characters
        for row in rows:
            if remaining <= 0:
                break
            content = str(row["text_content"])[:remaining]
            if content:
                result.append({"id": row["id"], "name": row["name"], "content": content})
                remaining -= len(content)
        return result

    def delete_project_document(self, project_id: int, document_id: int) -> bool:
        with self.lock:
            cursor = self.db.execute(
                "DELETE FROM documents WHERE id=? AND project_id=? AND kind='knowledge'",
                (document_id, project_id),
            )
            if cursor.rowcount:
                self.db.execute("UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
            self.db.commit()
            return cursor.rowcount > 0

    def search_chunks(self, conversation_id: int, terms: list[str], limit: int = 5) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all(
                """SELECT c.*,d.name FROM document_chunks c JOIN documents d ON d.id=c.document_id
                WHERE d.kind='knowledge' AND d.conversation_id=?""",
                (conversation_id,),
            )
        for row in rows:
            lower = row["content"].lower()
            row["score"] = sum(lower.count(term.lower()) for term in terms)
        return sorted((row for row in rows if row["score"] > 0), key=lambda row: row["score"], reverse=True)[
            :limit
        ]

    def search_project_chunks(
        self, project_id: int, terms: list[str], limit: int = 8
    ) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all(
                """SELECT c.*,d.name FROM document_chunks c JOIN documents d ON d.id=c.document_id
                WHERE d.kind='knowledge' AND d.project_id=?""",
                (project_id,),
            )
        for row in rows:
            lower = row["content"].lower()
            row["score"] = sum(lower.count(term.lower()) for term in terms)
        return sorted((row for row in rows if row["score"] > 0), key=lambda row: row["score"], reverse=True)[
            :limit
        ]

    def _fts_reciprocal_ranks(self, query: str) -> dict[int, float]:
        if not self.fts_enabled:
            return {}
        terms = tokenize(query)[:20]
        if not terms:
            return {}
        expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        try:
            rows = self._all(
                """SELECT CAST(chunk_id AS INTEGER) AS chunk_id,bm25(document_chunks_fts) AS rank
                FROM document_chunks_fts WHERE document_chunks_fts MATCH ? ORDER BY rank LIMIT 80""",
                (expression,),
            )
        except sqlite3.OperationalError:
            return {}
        return {row["chunk_id"]: 1.0 / (60 + index) for index, row in enumerate(rows, 1)}

    def _rank_chunk_rows(
        self,
        rows: list[dict[str, Any]],
        query: str,
        query_embedding: list[float] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        terms = tokenize(query)
        fts_scores = self._fts_reciprocal_ranks(query)
        ranked: list[dict[str, Any]] = []
        for row in rows:
            content = str(row.get("content") or "").lower()
            heading = str(row.get("heading") or "").lower()
            lexical = sum(content.count(term.lower()) for term in terms)
            heading_hits = sum(term.lower() in heading for term in terms)
            semantic = _cosine_similarity(query_embedding, _decode_embedding(row.get("embedding_json")))
            fts_score = fts_scores.get(row["id"], 0.0)
            if not lexical and not heading_hits and not fts_score and semantic < 0.32:
                continue
            score = lexical + heading_hits * 1.5 + fts_score * 120 + max(0.0, semantic) * 3
            ranked.append(
                {
                    **row,
                    "score": round(score, 6),
                    "retrieval": {
                        "lexical": lexical,
                        "fts": round(fts_score, 6),
                        "semantic": round(semantic, 6),
                        "heading": heading_hits,
                    },
                }
            )
        return sorted(ranked, key=lambda row: (row["score"], -row["chunk_index"]), reverse=True)[:limit]

    def search_chunks_hybrid(
        self,
        conversation_id: int,
        query: str,
        query_embedding: list[float] | None = None,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all(
                """SELECT c.*,d.name FROM document_chunks c JOIN documents d ON d.id=c.document_id
                WHERE d.kind='knowledge' AND d.conversation_id=?""",
                (conversation_id,),
            )
        return self._rank_chunk_rows(rows, query, query_embedding, limit)

    def search_project_chunks_hybrid(
        self,
        project_id: int,
        query: str,
        query_embedding: list[float] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all(
                """SELECT c.*,d.name FROM document_chunks c JOIN documents d ON d.id=c.document_id
                WHERE d.kind='knowledge' AND d.project_id=?""",
                (project_id,),
            )
        return self._rank_chunk_rows(rows, query, query_embedding, limit)

    def sample_latest_document_chunks(
        self, conversation_id: int, *, page_number: int | None = None, limit: int = 12
    ) -> list[dict[str, Any]]:
        with self.lock:
            document = self._one(
                "SELECT id FROM documents WHERE conversation_id=? AND kind='knowledge' ORDER BY id DESC LIMIT 1",
                (conversation_id,),
            )
            if not document:
                return []
            sql = """SELECT c.*,d.name FROM document_chunks c JOIN documents d ON d.id=c.document_id
                     WHERE c.document_id=?"""
            params: tuple[Any, ...] = (document["id"],)
            if page_number is not None:
                sql += " AND c.page_number=?"
                params = (document["id"], page_number)
            rows = self._all(sql + " ORDER BY c.chunk_index", params)
        if len(rows) <= limit:
            return rows
        indexes = {round(index * (len(rows) - 1) / (limit - 1)) for index in range(limit)}
        return [rows[index] for index in sorted(indexes)]

    def sample_project_document_chunks(self, project_id: int, limit: int = 8) -> list[dict[str, Any]]:
        with self.lock:
            return self._all(
                """SELECT c.*,d.name FROM document_chunks c JOIN documents d ON d.id=c.document_id
                WHERE d.kind='knowledge' AND d.project_id=?
                ORDER BY d.id DESC,c.chunk_index LIMIT ?""",
                (project_id, limit),
            )

    def referenced_project_documents(
        self, project_id: int, document_ids: list[int], max_characters: int = 36_000
    ) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(document_ids))[:8]
        if not unique_ids:
            return []
        placeholders = ",".join("?" for _ in unique_ids)
        with self.lock:
            rows = self._all(
                f"""SELECT DISTINCT d.id AS document_id,d.name,d.text_content
                FROM documents d
                LEFT JOIN meetings m
                  ON m.project_id=? AND (m.document_id=d.id OR d.meeting_id=m.id)
                WHERE d.id IN ({placeholders}) AND (d.project_id=? OR m.id IS NOT NULL)""",  # noqa: S608
                (project_id, *unique_ids, project_id),
            )
        by_id = {row["document_id"]: row for row in rows}
        result: list[dict[str, Any]] = []
        remaining = max_characters
        for document_id in unique_ids:
            row = by_id.get(document_id)
            if not row or remaining <= 0:
                continue
            content = str(row.get("text_content") or "")[:remaining]
            if content:
                result.append(
                    {
                        "document_id": document_id,
                        "name": row["name"],
                        "page_number": None,
                        "content": content,
                    }
                )
                remaining -= len(content)
        return result

    def create_meeting(
        self, document_id: int, data: dict[str, Any], project_id: int | None = None
    ) -> dict[str, Any]:
        with self.lock:
            cursor = self.db.execute(
                """INSERT INTO meetings(document_id,project_id,title,summary,participants_json,dates_json,
                locations_json,topics_json,risks_json,decisions_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    document_id,
                    project_id,
                    data["title"],
                    data["summary"],
                    *[
                        json.dumps(data[key], ensure_ascii=False)
                        for key in ("participants", "dates", "locations", "topics", "risks", "decisions")
                    ],
                ),
            )
            if project_id is not None:
                self.db.execute("UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
            self.db.commit()
            return self.get_meeting(cursor.lastrowid) or {}

    def get_meeting(self, meeting_id: int) -> dict[str, Any] | None:
        with self.lock:
            meeting = _decode_json(
                self._one(
                    """SELECT m.*,d.name AS document_name FROM meetings m
                    JOIN documents d ON d.id=m.document_id WHERE m.id=?""",
                    (meeting_id,),
                ),
                [
                    "participants_json",
                    "dates_json",
                    "locations_json",
                    "topics_json",
                    "risks_json",
                    "decisions_json",
                ],
            )
            if meeting:
                meeting["files"] = self.list_meeting_documents(meeting_id)
            return meeting

    def list_meetings(
        self,
        project_id: int | None = None,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self.lock:
            if project_id is not None:
                where = "WHERE m.project_id=?"
                params: tuple[Any, ...] = (project_id,)
            elif user_id is not None:
                where = """WHERE EXISTS(SELECT 1 FROM project_members pm
                WHERE pm.project_id=p.id AND pm.user_id=?)"""
                params = (user_id,)
            else:
                where = ""
                params = ()
            rows = self._all(
                f"""SELECT m.*,d.name AS document_name FROM meetings m
                JOIN documents d ON d.id=m.document_id
                LEFT JOIN projects p ON p.id=m.project_id {where} ORDER BY m.id DESC""",  # noqa: S608
                params,
            )
            fields = [
                "participants_json",
                "dates_json",
                "locations_json",
                "topics_json",
                "risks_json",
                "decisions_json",
            ]
            meetings = [_decode_json(row, fields) or {} for row in rows]
            for meeting in meetings:
                meeting["files"] = self.list_meeting_documents(meeting["id"])
            return meetings

    def rename_meeting(self, meeting_id: int, title: str) -> dict[str, Any] | None:
        with self.lock:
            meeting = self._one("SELECT id,project_id FROM meetings WHERE id=?", (meeting_id,))
            if not meeting:
                return None
            self.db.execute("UPDATE meetings SET title=? WHERE id=?", (title, meeting_id))
            if meeting["project_id"] is not None:
                self.db.execute(
                    "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (meeting["project_id"],),
                )
            self.db.commit()
            return self.get_meeting(meeting_id)

    def delete_meeting(self, meeting_id: int) -> bool:
        with self.lock:
            meeting = self._one("SELECT id,document_id,project_id FROM meetings WHERE id=?", (meeting_id,))
            if not meeting:
                return False
            self.db.execute("DELETE FROM todos WHERE meeting_id=?", (meeting_id,))
            self.db.execute("DELETE FROM memories WHERE source_type='meeting' AND source_id=?", (meeting_id,))
            self.db.execute("DELETE FROM meetings WHERE id=?", (meeting_id,))
            self.db.execute(
                "DELETE FROM documents WHERE meeting_id=? OR id=?",
                (meeting_id, meeting["document_id"]),
            )
            if meeting["project_id"] is not None:
                self.db.execute(
                    "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (meeting["project_id"],),
                )
            self.db.commit()
            return True

    def update_meeting_analysis(self, meeting_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        with self.lock:
            meeting = self._one("SELECT id,project_id FROM meetings WHERE id=?", (meeting_id,))
            if not meeting:
                return None
            self.db.execute(
                """UPDATE meetings SET summary=?,participants_json=?,dates_json=?,
                locations_json=?,topics_json=?,risks_json=?,decisions_json=? WHERE id=?""",
                (
                    data["summary"],
                    *[
                        json.dumps(data[key], ensure_ascii=False)
                        for key in ("participants", "dates", "locations", "topics", "risks", "decisions")
                    ],
                    meeting_id,
                ),
            )
            self.db.execute("DELETE FROM todos WHERE meeting_id=?", (meeting_id,))
            self.db.execute("DELETE FROM memories WHERE source_type='meeting' AND source_id=?", (meeting_id,))
            if meeting["project_id"] is not None:
                self.db.execute(
                    "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (meeting["project_id"],),
                )
            self.db.commit()
            return self.get_meeting(meeting_id)

    def add_todo(self, meeting_id: int, todo: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            cursor = self.db.execute(
                "INSERT INTO todos(meeting_id,title,description,owner,due_date,risk_level) VALUES (?,?,?,?,?,?)",
                (
                    meeting_id,
                    todo["title"],
                    todo.get("description", ""),
                    todo.get("owner", ""),
                    todo.get("dueDate", ""),
                    todo.get("riskLevel", "medium"),
                ),
            )
            self.db.commit()
            return self._one("SELECT * FROM todos WHERE id=?", (cursor.lastrowid,)) or {}

    def list_todos(
        self,
        project_id: int | None = None,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self.lock:
            if project_id is not None:
                where = "WHERE m.project_id=?"
                params: tuple[Any, ...] = (project_id,)
            elif user_id is not None:
                where = """WHERE EXISTS(SELECT 1 FROM project_members pm
                WHERE pm.project_id=p.id AND pm.user_id=?)"""
                params = (user_id,)
            else:
                where = ""
                params = ()
            return self._all(
                f"""SELECT t.*,m.title AS meeting_title,m.project_id FROM todos t
                LEFT JOIN meetings m ON m.id=t.meeting_id
                LEFT JOIN projects p ON p.id=m.project_id {where}
                ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END,t.id DESC""",  # noqa: S608
                params,
            )

    def get_todo(self, todo_id: int) -> dict[str, Any] | None:
        with self.lock:
            return self._one("SELECT * FROM todos WHERE id=?", (todo_id,))

    def update_todo(self, todo_id: int, fields: dict[str, str]) -> dict[str, Any] | None:
        allowed = {"status", "owner", "due_date", "email_status"}
        values = [(key, value) for key, value in fields.items() if key in allowed]
        if not values:
            return self.get_todo(todo_id)
        with self.lock:
            assignments = ",".join(f"{key}=?" for key, _ in values)
            self.db.execute(
                f"UPDATE todos SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE id=?",  # noqa: S608
                (*[value for _, value in values], todo_id),
            )
            self.db.commit()
            return self.get_todo(todo_id)

    @staticmethod
    def _memory_fingerprint(memory: dict[str, Any]) -> str:
        scope = (
            f"project:{memory.get('project_id')}"
            if memory.get("scope_type") == "project" and memory.get("project_id") is not None
            else (
                f"ordinary:{memory.get('workspace_id')}:{memory.get('created_by')}"
                if memory.get("workspace_id") is not None or memory.get("created_by") is not None
                else "ordinary"
            )
        )
        return re.sub(
            r"\s+",
            " ",
            f"{scope}|{memory['type']}|{memory.get('subject', '')}|{memory['content']}".lower(),
        ).strip()

    def _memory_scope(self, memory: dict[str, Any], project_id: int | None = None) -> tuple[str, int | None]:
        resolved_project_id = project_id if project_id is not None else memory.get("project_id")
        if resolved_project_id is None and memory.get("source_type") == "chat":
            source = self._one(
                """SELECT conversation.project_id FROM messages message
                JOIN conversations conversation ON conversation.id=message.conversation_id
                WHERE message.id=?""",
                (memory.get("source_id"),),
            )
            resolved_project_id = source.get("project_id") if source else None
        if resolved_project_id is None and memory.get("source_type") == "meeting":
            source = self._one("SELECT project_id FROM meetings WHERE id=?", (memory.get("source_id"),))
            resolved_project_id = source.get("project_id") if source else None
        return (
            ("project", int(resolved_project_id)) if resolved_project_id is not None else ("ordinary", None)
        )

    def add_memory(
        self,
        memory: dict[str, Any],
        project_id: int | None = None,
        *,
        workspace_id: int | None = None,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            scope_type, resolved_project_id = self._memory_scope(memory, project_id)
            if resolved_project_id is not None:
                project = self._one("SELECT workspace_id FROM projects WHERE id=?", (resolved_project_id,))
                workspace_id = project.get("workspace_id") if project else workspace_id
            elif memory.get("source_type") == "chat" and memory.get("source_id") is not None:
                source = self._one(
                    """SELECT c.workspace_id,c.created_by FROM messages m
                    JOIN conversations c ON c.id=m.conversation_id WHERE m.id=?""",
                    (memory.get("source_id"),),
                )
                if source:
                    workspace_id = source.get("workspace_id") or workspace_id
                    created_by = source.get("created_by") or created_by
            value = {
                **memory,
                "scope_type": scope_type,
                "project_id": resolved_project_id,
                "workspace_id": workspace_id,
                "created_by": created_by,
            }
            fingerprint = self._memory_fingerprint(value)
            existing = self._one("SELECT * FROM memories WHERE fingerprint=?", (fingerprint,))
            embedding_json = (
                json.dumps(value["embedding"], separators=(",", ":")) if value.get("embedding") else None
            )
            confidence = max(0.0, min(1.0, float(value.get("confidence", 0.8))))
            supersedes_id = value.get("supersedes_id")
            subject = str(value.get("subject") or "").strip()
            if (
                not existing
                and not supersedes_id
                and value["type"] in {"preference", "fact"}
                and subject
                and confidence >= 0.65
            ):
                conflict = self._one(
                    """SELECT id FROM memories WHERE scope_type=? AND project_id IS ?
                    AND workspace_id IS ? AND created_by IS ? AND type=?
                    AND subject=? AND status='active' ORDER BY id DESC LIMIT 1""",
                    (
                        scope_type,
                        resolved_project_id,
                        workspace_id,
                        created_by,
                        value["type"],
                        subject,
                    ),
                )
                supersedes_id = conflict["id"] if conflict else None
            self.db.execute(
                """INSERT INTO memories(type,subject,content,source_type,source_id,scope_type,project_id,
                workspace_id,created_by,
                importance,pinned,confidence,valid_from,valid_until,supersedes_id,status,sensitivity,
                embedding_json,fingerprint,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(fingerprint) DO UPDATE SET
                  source_type=excluded.source_type,source_id=excluded.source_id,
                  importance=MAX(memories.importance,excluded.importance),
                  pinned=MAX(memories.pinned,excluded.pinned),
                  confidence=MAX(memories.confidence,excluded.confidence),
                  valid_from=COALESCE(excluded.valid_from,memories.valid_from),
                  valid_until=COALESCE(excluded.valid_until,memories.valid_until),
                  sensitivity=excluded.sensitivity,
                  embedding_json=COALESCE(excluded.embedding_json,memories.embedding_json),
                  status='active',updated_at=CURRENT_TIMESTAMP""",
                (
                    value["type"],
                    subject,
                    value["content"],
                    value.get("source_type", "manual"),
                    value.get("source_id"),
                    scope_type,
                    resolved_project_id,
                    workspace_id,
                    created_by,
                    max(1, min(5, int(value.get("importance", 3)))),
                    1 if value.get("pinned") else 0,
                    confidence,
                    value.get("valid_from"),
                    value.get("valid_until"),
                    supersedes_id,
                    value.get("status", "active"),
                    value.get("sensitivity", "private"),
                    embedding_json,
                    fingerprint,
                ),
            )
            if supersedes_id:
                self.db.execute(
                    "UPDATE memories SET status='superseded',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (supersedes_id,),
                )
            self.db.commit()
            return self._decode_memory(
                self._one("SELECT * FROM memories WHERE fingerprint=?", (fingerprint,))
            )

    @staticmethod
    def _decode_memory(memory: dict[str, Any] | None) -> dict[str, Any]:
        if not memory:
            return {}
        result = dict(memory)
        result["embedding"] = _decode_embedding(result.pop("embedding_json", None))
        return result

    def _expire_memories(self) -> None:
        self.db.execute(
            """UPDATE memories SET status='expired',updated_at=CURRENT_TIMESTAMP
            WHERE status='active' AND valid_until IS NOT NULL AND valid_until<>'' AND valid_until<?""",
            (date.today().isoformat(),),
        )

    def list_memories(
        self,
        limit: int = 100,
        project_id: int | None = None,
        ordinary_only: bool = False,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self.lock:
            self._expire_memories()
            if ordinary_only:
                if user_id is not None:
                    rows = self._all(
                        """SELECT * FROM memories WHERE scope_type='ordinary' AND status='active'
                        AND created_by=?
                        ORDER BY pinned DESC,importance DESC,updated_at DESC,id DESC LIMIT ?""",
                        (user_id, limit),
                    )
                else:
                    rows = self._all(
                        """SELECT * FROM memories WHERE scope_type='ordinary' AND status='active'
                        ORDER BY pinned DESC,importance DESC,updated_at DESC,id DESC LIMIT ?""",
                        (limit,),
                    )
            elif project_id is not None:
                rows = self._all(
                    """SELECT * FROM memories WHERE scope_type='project' AND project_id=? AND status='active'
                    ORDER BY pinned DESC,importance DESC,updated_at DESC,id DESC LIMIT ?""",
                    (project_id, limit),
                )
            elif user_id is not None:
                rows = self._all(
                    """SELECT m.* FROM memories m WHERE m.status='active' AND (
                    (m.scope_type='ordinary' AND m.created_by=?) OR
                    (m.scope_type='project' AND EXISTS(
                      SELECT 1 FROM project_members pm
                      WHERE pm.project_id=m.project_id AND pm.user_id=?
                    ))) ORDER BY m.pinned DESC,m.importance DESC,m.updated_at DESC,m.id DESC LIMIT ?""",
                    (user_id, user_id, limit),
                )
            else:
                rows = self._all(
                    """SELECT * FROM memories WHERE status='active'
                    ORDER BY pinned DESC,importance DESC,updated_at DESC,id DESC LIMIT ?""",
                    (limit,),
                )
            self.db.commit()
            return [self._decode_memory(row) for row in rows]

    def search_memories(
        self,
        query: str,
        limit: int = 8,
        project_id: int | None = None,
        query_embedding: list[float] | None = None,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        terms = tokenize(query)
        values = self.list_memories(
            300,
            project_id=project_id,
            ordinary_only=project_id is None,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        for memory in values:
            content = f"{memory['subject']} {memory['content']}".lower()
            lexical = sum(term in content for term in terms)
            semantic = _cosine_similarity(query_embedding, memory.get("embedding"))
            memory["score"] = lexical + max(0.0, semantic) * 3
            memory["semantic_score"] = round(semantic, 6)
        selected = sorted(
            (item for item in values if item["pinned"] or item["score"] > 0.32),
            key=lambda item: (
                bool(item["pinned"]),
                item["score"],
                item["importance"],
                item["id"],
            ),
            reverse=True,
        )[:limit]
        if selected:
            placeholders = ",".join("?" for _ in selected)
            with self.lock:
                self.db.execute(
                    f"""UPDATE memories SET use_count=use_count+1,last_used_at=CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})""",  # noqa: S608
                    tuple(item["id"] for item in selected),
                )
                self.db.commit()
        return selected

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        with self.lock:
            value = self._decode_memory(self._one("SELECT * FROM memories WHERE id=?", (memory_id,)))
            return value or None

    def list_memory_versions(self, memory_id: int) -> list[dict[str, Any]]:
        with self.lock:
            memory = self._one("SELECT * FROM memories WHERE id=?", (memory_id,))
            if not memory:
                return []
            rows = self._all(
                """SELECT * FROM memories WHERE scope_type=? AND project_id IS ?
                AND workspace_id IS ? AND created_by IS ? AND type=? AND subject=?
                ORDER BY id DESC""",
                (
                    memory["scope_type"],
                    memory.get("project_id"),
                    memory.get("workspace_id"),
                    memory.get("created_by"),
                    memory["type"],
                    memory["subject"],
                ),
            )
            return [self._decode_memory(row) for row in rows]

    def update_memory(self, memory_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "type",
            "subject",
            "content",
            "importance",
            "pinned",
            "confidence",
            "valid_from",
            "valid_until",
            "status",
            "sensitivity",
            "embedding",
        }
        with self.lock:
            memory = self.get_memory(memory_id)
            if not memory:
                return None
            updated = {**memory, **{key: value for key, value in fields.items() if key in allowed}}
            updated["subject"] = str(updated.get("subject") or "")
            updated["content"] = str(updated.get("content") or "")
            updated["importance"] = max(1, min(5, int(updated.get("importance", 3))))
            updated["pinned"] = 1 if updated.get("pinned") else 0
            updated["confidence"] = max(0.0, min(1.0, float(updated.get("confidence", 0.8))))
            fingerprint = self._memory_fingerprint(updated)
            duplicate = self._one(
                "SELECT id FROM memories WHERE fingerprint=? AND id<>?", (fingerprint, memory_id)
            )
            if duplicate:
                raise ValueError("相同作用域中已存在内容一致的记忆")
            self.db.execute(
                """UPDATE memories SET type=?,subject=?,content=?,importance=?,pinned=?,confidence=?,
                valid_from=?,valid_until=?,status=?,sensitivity=?,embedding_json=?,fingerprint=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (
                    updated["type"],
                    updated["subject"],
                    updated["content"],
                    updated["importance"],
                    updated["pinned"],
                    updated["confidence"],
                    updated.get("valid_from"),
                    updated.get("valid_until"),
                    updated.get("status", "active"),
                    updated.get("sensitivity", "private"),
                    json.dumps(updated["embedding"], separators=(",", ":"))
                    if updated.get("embedding")
                    else None,
                    fingerprint,
                    memory_id,
                ),
            )
            self.db.commit()
            return self.get_memory(memory_id)

    def delete_memory(self, memory_id: int) -> bool:
        with self.lock:
            cursor = self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            self.db.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _decode_task(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        result = dict(row)
        for field in ("payload_json", "result_json", "error_json"):
            target = field.removesuffix("_json")
            raw = result.pop(field, None)
            try:
                result[target] = json.loads(raw) if raw else None
            except (TypeError, json.JSONDecodeError):
                result[target] = None
        return result

    def enqueue_task(
        self,
        *,
        task_id: str,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
        trace_id: str,
        max_attempts: int = 3,
    ) -> tuple[dict[str, Any], bool]:
        with self.lock:
            cursor = self.db.execute(
                """INSERT OR IGNORE INTO agent_tasks(
                id,kind,payload_json,idempotency_key,trace_id,max_attempts)
                VALUES (?,?,?,?,?,?)""",
                (
                    task_id,
                    kind,
                    json.dumps(payload, ensure_ascii=False),
                    idempotency_key,
                    trace_id,
                    max(1, max_attempts),
                ),
            )
            created = cursor.rowcount > 0
            self.db.commit()
            row = (
                self._one("SELECT * FROM agent_tasks WHERE id=?", (task_id,))
                if created
                else self._one(
                    "SELECT * FROM agent_tasks WHERE kind=? AND idempotency_key=?",
                    (kind, idempotency_key),
                )
            )
            return self._decode_task(row) or {}, created

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self._decode_task(self._one("SELECT * FROM agent_tasks WHERE id=?", (task_id,)))

    def list_tasks(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            where = "WHERE status=?" if status else ""
            params: tuple[Any, ...] = (status, limit) if status else (limit,)
            return [
                self._decode_task(row) or {}
                for row in self._all(
                    f"SELECT * FROM agent_tasks {where} ORDER BY created_at DESC LIMIT ?",  # noqa: S608
                    params,
                )
            ]

    def recover_tasks(self) -> list[dict[str, Any]]:
        with self.lock:
            self.db.execute(
                """UPDATE agent_tasks SET status='queued',available_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE status='running'"""
            )
            self.db.commit()
            rows = self._all(
                "SELECT * FROM agent_tasks WHERE status='queued' ORDER BY available_at,created_at"
            )
            return [self._decode_task(row) or {} for row in rows]

    def claim_task(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            cursor = self.db.execute(
                """UPDATE agent_tasks SET status='running',attempts=attempts+1,progress=5,
                started_at=COALESCE(started_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='queued' AND datetime(available_at)<=CURRENT_TIMESTAMP""",
                (task_id,),
            )
            self.db.commit()
            return self.get_task(task_id) if cursor.rowcount else None

    def update_task_progress(self, task_id: str, progress: int) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE agent_tasks SET progress=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (max(0, min(99, progress)), task_id),
            )
            self.db.commit()

    def complete_task(self, task_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
        with self.lock:
            self.db.execute(
                """UPDATE agent_tasks SET status='completed',progress=100,result_json=?,error_json=NULL,
                completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (json.dumps(result, ensure_ascii=False), task_id),
            )
            self.db.commit()
            return self.get_task(task_id)

    def fail_task(
        self,
        task_id: str,
        error: dict[str, Any],
        retry_delay_seconds: int,
        *,
        retryable: bool = True,
    ) -> tuple[dict[str, Any] | None, bool]:
        with self.lock:
            task = self._one("SELECT attempts,max_attempts FROM agent_tasks WHERE id=?", (task_id,))
            retrying = bool(retryable and task and task["attempts"] < task["max_attempts"])
            dead_lettering = bool(retryable and task and task["attempts"] >= task["max_attempts"])
            if retrying:
                available_at = (
                    datetime.now(UTC) + timedelta(seconds=max(0, retry_delay_seconds))
                ).isoformat()
                self.db.execute(
                    """UPDATE agent_tasks SET status='queued',progress=0,error_json=?,available_at=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (json.dumps(error, ensure_ascii=False), available_at, task_id),
                )
            else:
                self.db.execute(
                    """UPDATE agent_tasks SET status=?,error_json=?,completed_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (
                        "dead_letter" if dead_lettering else "failed",
                        json.dumps(error, ensure_ascii=False),
                        task_id,
                    ),
                )
                if dead_lettering:
                    self.db.execute(
                        """INSERT INTO dead_letter_tasks(task_id,error_json)
                        VALUES (?,?) ON CONFLICT(task_id) DO UPDATE SET
                        error_json=excluded.error_json,compensation_status='pending',
                        compensation_result_json=NULL,resolved_at=NULL,resolution=NULL,
                        updated_at=CURRENT_TIMESTAMP""",
                        (task_id, json.dumps(error, ensure_ascii=False)),
                    )
            self.db.commit()
            return self.get_task(task_id), retrying

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            self.db.execute(
                """UPDATE agent_tasks SET status='cancelled',completed_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'""",
                (task_id,),
            )
            self.db.commit()
            return self.get_task(task_id)

    def retry_task(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            cursor = self.db.execute(
                """UPDATE agent_tasks SET status='queued',attempts=0,progress=0,error_json=NULL,
                result_json=NULL,available_at=CURRENT_TIMESTAMP,started_at=NULL,completed_at=NULL,
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('failed','cancelled','dead_letter')""",
                (task_id,),
            )
            if cursor.rowcount:
                self.db.execute(
                    """UPDATE execution_traces SET status='running',error_json=NULL,
                    completed_at=NULL,duration_ms=NULL WHERE id=(SELECT trace_id FROM agent_tasks WHERE id=?)""",
                    (task_id,),
                )
                self.db.execute(
                    """UPDATE dead_letter_tasks SET resolved_at=CURRENT_TIMESTAMP,resolution='retried',
                    updated_at=CURRENT_TIMESTAMP WHERE task_id=? AND resolved_at IS NULL""",
                    (task_id,),
                )
            self.db.commit()
            return self.get_task(task_id)

    def get_dead_letter(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._one("SELECT * FROM dead_letter_tasks WHERE task_id=?", (task_id,))
            if not row:
                return None
            decoded = _decode_json(row, ["error_json", "compensation_result_json"]) or {}
            if decoded.get("compensation_result") == []:
                decoded["compensation_result"] = None
            decoded["task"] = self.get_task(task_id)
            return decoded

    def list_dead_letters(self, *, active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            where = "WHERE resolved_at IS NULL" if active_only else ""
            rows = self._all(
                f"SELECT * FROM dead_letter_tasks {where} ORDER BY created_at DESC LIMIT ?",  # noqa: S608
                (limit,),
            )
            result = []
            for row in rows:
                decoded = _decode_json(row, ["error_json", "compensation_result_json"]) or {}
                if decoded.get("compensation_result") == []:
                    decoded["compensation_result"] = None
                decoded["task"] = self.get_task(str(row["task_id"]))
                result.append(decoded)
            return result

    def update_dead_letter_compensation(
        self, task_id: str, status: str, result: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self.lock:
            self.db.execute(
                """UPDATE dead_letter_tasks SET compensation_status=?,compensation_result_json=?,
                updated_at=CURRENT_TIMESTAMP WHERE task_id=?""",
                (status, json.dumps(result, ensure_ascii=False), task_id),
            )
            self.db.commit()
            return self.get_dead_letter(task_id)

    def resolve_dead_letter(self, task_id: str, resolution: str = "dismissed") -> dict[str, Any] | None:
        with self.lock:
            cursor = self.db.execute(
                """UPDATE dead_letter_tasks SET resolved_at=CURRENT_TIMESTAMP,resolution=?,
                updated_at=CURRENT_TIMESTAMP WHERE task_id=? AND resolved_at IS NULL""",
                (resolution, task_id),
            )
            if cursor.rowcount:
                self.db.execute(
                    "UPDATE agent_tasks SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (task_id,),
                )
            self.db.commit()
            return self.get_dead_letter(task_id) if cursor.rowcount else None

    def rollback_execution(self, execution_id: str) -> dict[str, Any]:
        with self.lock:
            messages = self._all("SELECT id FROM messages WHERE execution_id=?", (execution_id,))
            artifacts = self._all("SELECT id,file_path FROM artifacts WHERE execution_id=?", (execution_id,))
            message_ids = [int(item["id"]) for item in messages]
            if message_ids:
                placeholders = ",".join("?" for _ in message_ids)
                self.db.execute(
                    f"DELETE FROM memories WHERE source_type='chat' AND source_id IN ({placeholders})",  # noqa: S608
                    tuple(message_ids),
                )
            self.db.execute("DELETE FROM messages WHERE execution_id=?", (execution_id,))
            self.db.execute("DELETE FROM artifacts WHERE execution_id=?", (execution_id,))
            self.db.commit()
            return {
                "messageIds": message_ids,
                "artifactIds": [int(item["id"]) for item in artifacts],
                "filePaths": [str(item["file_path"]) for item in artifacts],
            }

    def create_trace(
        self,
        trace_id: str,
        *,
        task_id: str | None = None,
        conversation_id: int | None = None,
        intent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self.db.execute(
                """INSERT OR IGNORE INTO execution_traces(
                id,task_id,conversation_id,intent,metadata_json) VALUES (?,?,?,?,?)""",
                (
                    trace_id,
                    task_id,
                    conversation_id,
                    intent,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            self.db.commit()
            return self.get_trace(trace_id) or {}

    def add_trace_event(
        self,
        trace_id: str,
        *,
        stage: str,
        event: str,
        status: str,
        attempt: int | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.lock:
            self.db.execute(
                """INSERT INTO trace_events(trace_id,stage,event,status,attempt,duration_ms,metadata_json)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    trace_id,
                    stage,
                    event,
                    status,
                    attempt,
                    duration_ms,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            self.db.commit()

    def update_trace_context(
        self,
        trace_id: str,
        *,
        conversation_id: int | None = None,
        intent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.lock:
            current = self._one("SELECT metadata_json FROM execution_traces WHERE id=?", (trace_id,))
            existing_metadata: dict[str, Any] = {}
            if current:
                try:
                    existing_metadata = json.loads(current.get("metadata_json") or "{}")
                except (TypeError, json.JSONDecodeError):
                    existing_metadata = {}
            self.db.execute(
                """UPDATE execution_traces SET conversation_id=COALESCE(?,conversation_id),
                intent=COALESCE(?,intent),metadata_json=? WHERE id=?""",
                (
                    conversation_id,
                    intent,
                    json.dumps({**existing_metadata, **(metadata or {})}, ensure_ascii=False),
                    trace_id,
                ),
            )
            self.db.commit()

    def finish_trace(
        self, trace_id: str, status: str, error: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        with self.lock:
            self.db.execute(
                """UPDATE execution_traces SET status=?,error_json=?,completed_at=CURRENT_TIMESTAMP,
                duration_ms=CAST((julianday(CURRENT_TIMESTAMP)-julianday(started_at))*86400000 AS INTEGER)
                WHERE id=?""",
                (status, json.dumps(error, ensure_ascii=False) if error else None, trace_id),
            )
            self.db.commit()
            return self.get_trace(trace_id)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._one("SELECT * FROM execution_traces WHERE id=?", (trace_id,))
            if not row:
                return None
            result = _decode_json(row, ["metadata_json", "error_json"]) or {}
            if result.get("error") == []:
                result["error"] = None
            events = self._all("SELECT * FROM trace_events WHERE trace_id=? ORDER BY id", (trace_id,))
            result["events"] = [_decode_json(item, ["metadata_json"]) or {} for item in events]
            return result

    def list_traces(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            rows = self._all("SELECT * FROM execution_traces ORDER BY started_at DESC LIMIT ?", (limit,))
            traces = [_decode_json(row, ["metadata_json", "error_json"]) or {} for row in rows]
            for trace in traces:
                if trace.get("error") == []:
                    trace["error"] = None
            return traces

    def claim_email_delivery(
        self,
        *,
        delivery_id: str,
        idempotency_key: str,
        source_type: str,
        source_id: int | None,
        provider: str,
        recipient: str,
        subject: str,
        body_hash: str,
    ) -> tuple[dict[str, Any], bool]:
        with self.lock:
            existing = self._one("SELECT * FROM email_deliveries WHERE idempotency_key=?", (idempotency_key,))
            if existing:
                if existing["status"] == "failed":
                    self.db.execute(
                        """UPDATE email_deliveries SET status='sending',attempts=attempts+1,
                        error_json=NULL,resolved_at=NULL,resolution=NULL,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (existing["id"],),
                    )
                    self.db.commit()
                    existing = self._one("SELECT * FROM email_deliveries WHERE id=?", (existing["id"],))
                    return self._decode_delivery(existing), True
                return self._decode_delivery(existing), False
            self.db.execute(
                """INSERT INTO email_deliveries(id,idempotency_key,source_type,source_id,provider,
                recipient,subject,body_hash) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    delivery_id,
                    idempotency_key,
                    source_type,
                    source_id,
                    provider,
                    recipient,
                    subject,
                    body_hash,
                ),
            )
            self.db.commit()
            return self._decode_delivery(
                self._one("SELECT * FROM email_deliveries WHERE id=?", (delivery_id,))
            ), True

    @staticmethod
    def _decode_delivery(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        result = dict(row)
        for field in ("result_json", "error_json"):
            target = field.removesuffix("_json")
            raw = result.pop(field, None)
            try:
                result[target] = json.loads(raw) if raw else None
            except (TypeError, json.JSONDecodeError):
                result[target] = None
        return result

    def complete_email_delivery(self, delivery_id: str, result: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.db.execute(
                """UPDATE email_deliveries SET status='sent',result_json=?,sent_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (json.dumps(result, ensure_ascii=False), delivery_id),
            )
            self.db.commit()
            return self._decode_delivery(
                self._one("SELECT * FROM email_deliveries WHERE id=?", (delivery_id,))
            )

    def fail_email_delivery(self, delivery_id: str, error: dict[str, Any]) -> None:
        with self.lock:
            self.db.execute(
                """UPDATE email_deliveries SET status='failed',error_json=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?""",
                (json.dumps(error, ensure_ascii=False), delivery_id),
            )
            self.db.commit()

    def list_email_deliveries(
        self, *, status: str | None = None, active_only: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.lock:
            clauses = []
            params: list[Any] = []
            if status:
                clauses.append("status=?")
                params.append(status)
            if active_only:
                clauses.append("resolved_at IS NULL")
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            rows = self._all(
                f"SELECT * FROM email_deliveries {where} ORDER BY created_at DESC LIMIT ?",  # noqa: S608
                tuple(params),
            )
            return [self._decode_delivery(row) for row in rows]

    def resolve_email_delivery(
        self, delivery_id: str, resolution: str = "acknowledged"
    ) -> dict[str, Any] | None:
        with self.lock:
            cursor = self.db.execute(
                """UPDATE email_deliveries SET resolved_at=CURRENT_TIMESTAMP,resolution=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='failed' AND resolved_at IS NULL""",
                (resolution, delivery_id),
            )
            self.db.commit()
            if not cursor.rowcount:
                return None
            return self._decode_delivery(
                self._one("SELECT * FROM email_deliveries WHERE id=?", (delivery_id,))
            )

    def add_artifact(
        self,
        *,
        conversation_id: int,
        kind: str,
        name: str,
        file_path: str,
        metadata: dict[str, Any],
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            cursor = self.db.execute(
                """INSERT OR IGNORE INTO artifacts(
                conversation_id,kind,name,file_path,metadata_json,execution_id) VALUES (?,?,?,?,?,?)""",
                (
                    conversation_id,
                    kind,
                    name,
                    file_path,
                    json.dumps(metadata, ensure_ascii=False),
                    execution_id,
                ),
            )
            self.db.commit()
            row = (
                self._one("SELECT * FROM artifacts WHERE execution_id=?", (execution_id,))
                if cursor.rowcount == 0 and execution_id
                else self._one("SELECT * FROM artifacts WHERE id=?", (cursor.lastrowid,))
            )
            return _decode_json(row, ["metadata_json"]) or {}

    def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        with self.lock:
            return _decode_json(
                self._one("SELECT * FROM artifacts WHERE id=?", (artifact_id,)), ["metadata_json"]
            )

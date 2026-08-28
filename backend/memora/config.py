from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    file = BACKEND_ROOT / ".env"
    if not file.exists():
        return
    for raw_line in file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def _boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LlmConfig:
    api_key: str
    base_url: str
    model: str


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str
    base_url: str
    model: str
    dimensions: int | None


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    secure: bool
    user: str
    password: str
    from_address: str


@dataclass(frozen=True)
class AgentMailConfig:
    api_key: str
    inbox_id: str
    base_url: str


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    app_name: str
    data_dir: Path
    llm: LlmConfig
    embedding: EmbeddingConfig
    tavily_api_key: str
    ocr_api_url: str
    ocr_api_key: str
    history_token_budget: int
    document_token_budget: int
    memory_token_budget: int
    web_token_budget: int
    provider_max_attempts: int
    provider_backoff_seconds: float
    provider_circuit_threshold: int
    provider_circuit_seconds: int
    frontend_origins: tuple[str, ...]
    smtp: SmtpConfig
    agentmail: AgentMailConfig


def load_config() -> Config:
    _load_dotenv()
    smtp_user = os.getenv("SMTP_USER", "")
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_base_url = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    embedding_dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "0")) or None
    return Config(
        host=os.getenv("BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        app_name=os.getenv("APP_NAME", "Memora"),
        data_dir=(BACKEND_ROOT / os.getenv("DATA_DIR", "data")).resolve(),
        llm=LlmConfig(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=os.getenv("LLM_MODEL", "qwen-plus"),
        ),
        embedding=EmbeddingConfig(
            api_key=os.getenv("EMBEDDING_API_KEY") or llm_api_key,
            base_url=(os.getenv("EMBEDDING_BASE_URL") or llm_base_url).rstrip("/"),
            model=os.getenv("EMBEDDING_MODEL", "text-embedding-v4"),
            dimensions=embedding_dimensions,
        ),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        ocr_api_url=os.getenv("OCR_API_URL", "").rstrip("/"),
        ocr_api_key=os.getenv("OCR_API_KEY", ""),
        history_token_budget=int(os.getenv("HISTORY_TOKEN_BUDGET", "3200")),
        document_token_budget=int(os.getenv("DOCUMENT_TOKEN_BUDGET", "7000")),
        memory_token_budget=int(os.getenv("MEMORY_TOKEN_BUDGET", "1200")),
        web_token_budget=int(os.getenv("WEB_TOKEN_BUDGET", "2200")),
        provider_max_attempts=int(os.getenv("PROVIDER_MAX_ATTEMPTS", "3")),
        provider_backoff_seconds=float(os.getenv("PROVIDER_BACKOFF_SECONDS", "0.5")),
        provider_circuit_threshold=int(os.getenv("PROVIDER_CIRCUIT_THRESHOLD", "5")),
        provider_circuit_seconds=int(os.getenv("PROVIDER_CIRCUIT_SECONDS", "30")),
        frontend_origins=tuple(
            item.strip()
            for item in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(
                ","
            )
            if item.strip()
        ),
        smtp=SmtpConfig(
            host=os.getenv("SMTP_HOST", ""),
            port=int(os.getenv("SMTP_PORT", "587")),
            secure=_boolean("SMTP_SECURE"),
            user=smtp_user,
            password=os.getenv("SMTP_PASS", ""),
            from_address=os.getenv("SMTP_FROM", smtp_user),
        ),
        agentmail=AgentMailConfig(
            api_key=os.getenv("AGENTMAIL_API_KEY", ""),
            inbox_id=os.getenv("AGENTMAIL_INBOX_ID", ""),
            base_url=os.getenv("AGENTMAIL_BASE_URL", "https://api.agentmail.to/v0").rstrip("/"),
        ),
    )


config = load_config()


def ensure_data_dirs(base_dir: Path | None = None) -> Path:
    target = (base_dir or config.data_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    (target / "artifacts").mkdir(exist_ok=True)
    return target

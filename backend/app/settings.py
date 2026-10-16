"""Configuration, read from the environment (and `.env` in development).

Every setting has a safe development default except secrets. `validate_for_env`
refuses to start a production process with development secrets.
"""

from __future__ import annotations

import zoneinfo
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder for development only; validate_for_env() refuses it in production.
DEV_SECRET_KEY = "dev-only-secret-change-me"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- process ----
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Assistant"
    host: str = "127.0.0.1"
    port: int = 4000
    log_level: str = "INFO"
    # Keys HMACs of one-time email codes. Must be set to a long random value in production.
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    # Shared with the web app's Better Auth (web.env): it authenticates its calls to
    # /internal/auth/* (app/auth/internal.py). Empty = those routes do not exist (404).
    auth_internal_token: SecretStr = SecretStr("")

    # ---- database (PostgreSQL + pgvector: the single source of truth) ----
    database_url: str = "postgresql+asyncpg://aichat:aichat@127.0.0.1:5432/aichat"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_connect_timeout_s: float = 5.0

    # ---- HTTP ----
    # Comma-separated browser origins. Empty = no CORS (the API is called by the web
    # app's server-side proxy, not by browsers directly).
    allowed_origins: str = ""
    # Only enable when the API is reachable exclusively through a trusted proxy.
    trust_forwarded_for: bool = False
    max_body_bytes: int = 64 * 1024

    # ---- auth ----
    email_code_ttl_minutes: int = 15
    email_code_max_attempts: int = 5
    code_requests_per_email: int = 5  # per auth_window_minutes
    auth_window_minutes: int = 15
    email_change_requests_per_user: int = 3  # per auth_window_minutes
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 64 * 1024
    argon2_parallelism: int = 2

    # ---- profile photo ----
    # The upload is the original file (JPEG/PNG/WebP); the stored photo is a 256 px WebP.
    # The web app's proxy caps uploads at the default (docs/openapi.json `x-max-bytes`), so
    # raising this alone changes nothing for browsers.
    avatar_max_bytes: int = Field(default=5 * 1024 * 1024, ge=64 * 1024, le=20 * 1024 * 1024)
    avatar_uploads_per_user: int = 10  # per auth_window_minutes

    # ---- progress ----
    # Decides which day "today" is for a user who has not chosen a time zone (users.timezone).
    default_timezone: str = "Asia/Kolkata"

    # ---- jobs worker (python -m app.jobs, started every minute by aichat-jobs.timer) ----
    # Read on every run, so a change to api.env applies from the next minute, no restart needed.
    jobs_enabled: bool = False
    # Rollout of emails to students: off (nothing is planned or sent) -> dry_run (planned and
    # recorded as `dry_run`, nothing sent) -> allowlist (sent only to NOTIFICATIONS_ALLOWLIST)
    # -> on. Support forwards to SUPPORT_EMAIL do not depend on this.
    notifications_mode: Literal["off", "dry_run", "allowlist", "on"] = "off"
    notifications_allowlist: str = ""  # comma-separated user ids or email addresses
    notifications_kinds: str = ""  # comma-separated kinds to allow; empty = every kind
    notifications_max_per_run: int = Field(default=50, ge=1, le=1000)
    # The public web address, for links in emails (unsubscribe). Required once emails are sent.
    public_app_url: str = ""
    # Where support requests are forwarded. Empty: requests are only stored.
    support_email: str = ""

    # ---- email ----
    email_backend: Literal["smtp", "ollastack", "memory"] = "smtp"
    email_from: str = "Assistant <no-reply@localhost>"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = False
    smtp_ssl: bool = False
    # Ollastack Agent Mail (EMAIL_BACKEND=ollastack): the mailbox sets the sender; EMAIL_FROM is unused.
    ollastack_base_url: str = "https://login.ollastack.com"
    ollastack_token: SecretStr = SecretStr("")
    ollastack_mailbox_id: str = ""

    # ---- LLM ----
    # "openai_compatible" uses the primary (and optional fallback) provider below.
    # "fake" is a deterministic local provider for tests and offline development.
    llm_provider: Literal["openai_compatible", "fake"] = "openai_compatible"
    llm_primary_name: str = "ollima"
    llm_primary_base_url: str = "https://api.ollima.com/v1"
    llm_primary_api_key: SecretStr = SecretStr("")
    llm_primary_model: str = "gemini-3.1-flash-lite"
    llm_primary_stream_usage: bool = True
    llm_fallback_name: str = "openrouter"
    llm_fallback_base_url: str = "https://openrouter.ai/api/v1"
    llm_fallback_api_key: SecretStr = SecretStr("")
    llm_fallback_model: str = ""  # empty = no fallback provider
    llm_fallback_stream_usage: bool = True
    llm_temperature: float = 0.7
    llm_max_output_tokens: int = 4096
    llm_connect_timeout_s: float = 10.0
    llm_first_token_timeout_s: float = 60.0
    llm_total_timeout_s: float = 180.0
    llm_fake_token_delay_s: float = 0.0
    # Total characters sent to the model per turn (system prompt + retrieved context +
    # history + new message). Characters approximate tokens (~4 chars/token for English;
    # Devanagari costs ~2.6x more tokens per character). See app/rag/context.py.
    llm_max_input_chars: int = 48_000

    # ---- chat ----
    chat_max_message_chars: int = 16_000
    chat_history_max_messages: int = 50
    chat_generations_per_minute: int = 20
    chat_generations_per_day: int = 500
    stream_keepalive_s: float = 15.0
    stream_stale_after_s: int = 300
    stream_cancel_poll_s: float = 1.0

    # ---- Study time (app/study): how long without input counts as idle, by mode. Reading allows
    # longer (reading and thinking need no clicks); the reading prompt is always shorter than this.
    study_idle_reading_s: int = Field(default=300, ge=60, le=1800)
    study_idle_solving_s: int = Field(default=120, ge=30, le=1800)

    # ---- RAG (LangGraph + LangChain retriever over PostgreSQL/pgvector) ----
    rag_enabled: bool = True
    rag_top_k: int = 5
    # Cosine similarity floor (0..1). Uncalibrated default: tune with scripts/eval_retrieval.py.
    rag_min_score: float = 0.30
    rag_max_context_chars: int = 8_000
    rag_retrieval_timeout_s: float = 8.0
    rag_hnsw_ef_search: int = 100
    # The NCERT Knowledge Service (app/rag/ncert.py): with a URL and a key, the tutor's knowledge
    # source; empty = the pgvector knowledge base. The key is the service's client key (a secret).
    # The timeout is the whole call; the service's vector search takes ~0.3 s (p95 0.5 s).
    ncert_kb_base_url: str = ""
    ncert_kb_api_key: SecretStr = SecretStr("")
    ncert_kb_timeout_s: float = Field(default=4.0, gt=0, le=10)
    rag_chunk_size: int = 1_000
    rag_chunk_overlap: int = 150
    rag_max_document_bytes: int = 5 * 1024 * 1024

    # ---- embeddings ----
    # "openai_compatible" calls an OpenAI-compatible /embeddings API.
    # "fake" is a deterministic keyword-hashing embedder for tests and offline development.
    embedding_provider: Literal["openai_compatible", "fake"] = "openai_compatible"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = "text-embedding-3-small"
    # Must equal the pgvector column dimension (app/db/models.py EMBEDDING_DIMENSIONS).
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 64
    embedding_timeout_s: float = 20.0

    # ---- user files: File Library and chat attachments (app/files) ----
    # Off = no uploads and no processing; READY attachments keep answering. Text chat never
    # depends on files, and no files setting can stop the API from starting.
    files_enabled: bool = True
    # Where untrusted files are parsed. "systemd": a sandboxed transient unit (no network, no
    # secrets, own memory limit); "subprocess": a plain child process with an empty environment
    # (development and tests); "auto": systemd in production, subprocess otherwise. Production
    # never parses unsandboxed: with anything but systemd there, files are unavailable.
    files_extractor: Literal["auto", "subprocess", "systemd"] = "auto"

    # ---- tutor ----
    # Teach the model the interactive practice blocks (quizzes, flashcards, graphs, file previews;
    # app/chat/assistant.py INTERACTIVE_BLOCKS). The web app renders them either way. Off until
    # the owner turns it on; it costs prompt characters on every turn.
    tutor_interactive_blocks: bool = False
    # Give the tutor its teaching defaults (app/chat/teaching.py: direct answers when asked, mistakes
    # diagnosed before they are corrected, one hint at a time when stuck); the student's own settings
    # still come first. Off until the owner turns it on; it costs prompt characters on every turn.
    tutor_teaching_policy: bool = False
    # Practice tests in the chat come only from the question bank (app/qbank/chat_tests.py): the
    # model names a chapter, the app sets stored questions, and a practice block the model writes
    # itself is never shown as a test. The owner's decision, 2026-10-16.
    question_bank_tests: bool = True

    @field_validator("default_timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("DEFAULT_TIMEZONE must be an IANA time zone name, e.g. Asia/Kolkata") from error
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def ncert_kb_enabled(self) -> bool:
        return bool(self.ncert_kb_base_url and self.ncert_kb_api_key.get_secret_value())

    @property
    def files_runner(self) -> Literal["subprocess", "systemd"] | None:
        """How files are parsed, or None when that would be unsafe (production without systemd)."""
        runner = self.files_extractor
        if runner == "auto":
            runner = "systemd" if self.is_production else "subprocess"
        if self.is_production and runner != "systemd":
            return None
        return runner

    @staticmethod
    def _items(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def notification_allowlist(self) -> set[str]:
        return {item.lower() for item in self._items(self.notifications_allowlist)}

    @property
    def notification_kinds(self) -> set[str] | None:
        """None = every kind."""
        return set(self._items(self.notifications_kinds)) or None

    def jobs_problems(self) -> list[str]:
        """What stops the worker from sending emails safely (checked by every run)."""
        problems = []
        if self.notifications_mode != "off" and not self.public_app_url.startswith(("https://", "http://")):
            problems.append("NOTIFICATIONS_MODE needs PUBLIC_APP_URL (the web app's address, for links in emails)")
        if self.notifications_mode == "allowlist" and not self.notification_allowlist:
            problems.append("NOTIFICATIONS_MODE=allowlist needs NOTIFICATIONS_ALLOWLIST")
        return problems

    def validate_for_env(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.secret_key.get_secret_value() in ("", DEV_SECRET_KEY) or len(self.secret_key.get_secret_value()) < 32:
            problems.append("SECRET_KEY must be a random value of at least 32 characters")
        if len(self.auth_internal_token.get_secret_value()) < 32:
            problems.append("AUTH_INTERNAL_TOKEN must be a random value of at least 32 characters")
        if "aichat:aichat@" in self.database_url:
            problems.append("DATABASE_URL uses the development credentials")
        if self.llm_provider == "fake":
            problems.append("LLM_PROVIDER=fake is not allowed in production")
        if self.email_backend not in ("smtp", "ollastack"):
            problems.append("EMAIL_BACKEND must be smtp or ollastack in production")
        if self.email_backend == "ollastack" and not (
            self.ollastack_token.get_secret_value() and self.ollastack_mailbox_id
        ):
            problems.append("EMAIL_BACKEND=ollastack needs OLLASTACK_TOKEN and OLLASTACK_MAILBOX_ID")
        if self.rag_enabled and self.embedding_provider == "fake":
            problems.append("EMBEDDING_PROVIDER=fake is not allowed in production while RAG is enabled")
        if self.ncert_kb_base_url and not self.ncert_kb_base_url.startswith(
            ("https://", "http://127.0.0.1:", "http://localhost:")
        ):
            problems.append("NCERT_KB_BASE_URL must be https:// or loopback (the key travels with every call)")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()

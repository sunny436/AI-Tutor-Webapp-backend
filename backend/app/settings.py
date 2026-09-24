"""Configuration, read from the environment (and `.env` in development).

Every setting has a safe development default except secrets. `validate_for_env`
refuses to start a production process with development secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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
    session_ttl_days: int = 30
    email_code_ttl_minutes: int = 15
    email_code_max_attempts: int = 5
    login_failures_per_email: int = 10  # per auth_window_minutes
    login_attempts_per_ip: int = 50  # per auth_window_minutes
    signup_attempts_per_ip: int = 20  # per auth_window_minutes
    code_requests_per_email: int = 5  # per auth_window_minutes
    auth_window_minutes: int = 15
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 64 * 1024
    argon2_parallelism: int = 2

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

    # ---- RAG (LangGraph + LangChain retriever over PostgreSQL/pgvector) ----
    rag_enabled: bool = True
    rag_top_k: int = 5
    # Cosine similarity floor (0..1). Uncalibrated default: tune with scripts/eval_retrieval.py.
    rag_min_score: float = 0.30
    rag_max_context_chars: int = 8_000
    rag_retrieval_timeout_s: float = 8.0
    rag_hnsw_ef_search: int = 100
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

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_env(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.secret_key.get_secret_value() in ("", DEV_SECRET_KEY) or len(self.secret_key.get_secret_value()) < 32:
            problems.append("SECRET_KEY must be a random value of at least 32 characters")
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
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()

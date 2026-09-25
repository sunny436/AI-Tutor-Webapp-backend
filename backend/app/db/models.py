"""PostgreSQL schema: the single source of truth for all application data.

User ─┬─ UserSettings
      ├─ LearnerProfile, LearnerSubject, LearningPreferences   (app/learning)
      ├─ AuthSession
      ├─ Conversation ── Message ── MessageFeedback
      └─ UsageEvent
EmailCode and AuthAttempt support sign-up, reset and throttling.

Knowledge base (RAG):
KnowledgeSource (global, or private to owner_user_id) ── Document ── DocumentChunk (pgvector embedding)

`metadata` JSONB columns absorb per-feature data without schema churn.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# clock_timestamp(), not now(): rows inserted in one transaction (a user message
# and its assistant placeholder) must still get distinct, ordered timestamps.
NOW = text("clock_timestamp()")

MESSAGE_ROLES = ("user", "assistant", "system")
MESSAGE_STATUSES = ("complete", "streaming", "cancelled", "error", "superseded")
CODE_PURPOSES = ("verify_email", "reset_password", "change_email")

# What a student can tell the tutor (app/learning). Every preference has a neutral "auto"
# that adds no instruction, so a student who sets nothing gets the tutor everyone gets.
MAIN_GOALS = ("board_exams", "competitive_exam", "better_marks", "understand_concepts", "homework_help", "other")
PREFERENCE_CHOICES: dict[str, tuple[str, ...]] = {
    # Learning preferences
    "language": ("auto", "english", "hindi", "hinglish"),
    "explanation_level": ("auto", "simple", "standard", "detailed"),
    "pace": ("auto", "slow", "steady", "fast"),
    "difficulty": ("auto", "easy", "medium", "hard"),
    "real_world_examples": ("auto", "more", "fewer"),
    "visual_explanations": ("auto", "more", "fewer"),
    # AI tutor
    "personality": ("auto", "friendly", "encouraging", "professional"),
    "response_length": ("auto", "short", "medium", "long"),
    "answer_mode": ("auto", "direct", "hints_first", "socratic"),
    "step_by_step": ("auto", "on", "off"),
    "ask_before_answer": ("auto", "on", "off"),
    "practice_questions": ("auto", "on", "off"),
    "mistake_correction": ("auto", "gentle", "direct"),
    "highlight_key_concepts": ("auto", "on", "off"),
}

# The pgvector column dimension. settings.embedding_dimensions must equal it (checked at
# startup); changing it needs a new migration and a re-ingest of every document.
EMBEDDING_DIMENSIONS = 1536


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=NOW)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    # Incremented by every change to the identity profile; writes must name the version they
    # read (optimistic concurrency), so a stale form cannot silently overwrite a newer edit.
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    timezone: Mapped[str | None] = mapped_column(String(64))  # IANA name, set by the user
    avatar_hash: Mapped[str | None] = mapped_column(String(32))  # names the current photo; None = no photo
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserAvatar(Base):
    """The profile photo, re-encoded server-side (WebP, at most 64 KB). See app/auth/avatar.py."""

    __tablename__ = "user_avatars"
    __table_args__ = (
        CheckConstraint("octet_length(image) <= 65536", name="image_size"),
        CheckConstraint("content_type = 'image/webp'", name="content_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    hash: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = _created()


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = _created()


class LearnerProfile(Base):
    """What a student tells the tutor about their studies. Codes come from the academic catalog
    (app/learning/catalog.py); free text is length-limited and reaches the model only as quoted
    information, never as instructions (app/learning/tutor.py)."""

    __tablename__ = "learner_profiles"
    __table_args__ = (
        CheckConstraint(f"main_goal IN {MAIN_GOALS}", name="main_goal"),
        CheckConstraint("target_score_percent BETWEEN 0 AND 100", name="target_score_percent"),
        CheckConstraint("daily_active_minutes_goal BETWEEN 0 AND 720", name="daily_active_minutes_goal"),
        CheckConstraint("weekly_active_minutes_goal BETWEEN 0 AND 5040", name="weekly_active_minutes_goal"),
        CheckConstraint("cardinality(weak_topics) <= 10", name="weak_topics"),
        CheckConstraint("board_state IS NULL OR board = 'state'", name="board_state"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Two independently edited resources, two versions (optimistic concurrency).
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    subjects_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    grade: Mapped[str | None] = mapped_column(String(40))
    board: Mapped[str | None] = mapped_column(String(40))
    board_state: Mapped[str | None] = mapped_column(String(40))
    medium: Mapped[str | None] = mapped_column(String(40))
    academic_year: Mapped[str | None] = mapped_column(String(40))
    main_goal: Mapped[str | None] = mapped_column(String(40))
    target_exam: Mapped[str | None] = mapped_column(String(80))
    target_score_percent: Mapped[int | None] = mapped_column(SmallInteger)
    weak_topics: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, server_default=text("'{}'"))
    daily_active_minutes_goal: Mapped[int | None] = mapped_column(SmallInteger)
    weekly_active_minutes_goal: Mapped[int | None] = mapped_column(SmallInteger)
    preferred_study_time: Mapped[time | None] = mapped_column(Time)
    short_term_goal: Mapped[str | None] = mapped_column(String(280))
    long_term_goal: Mapped[str | None] = mapped_column(String(280))
    updated_at: Mapped[datetime] = _created()


class LearnerSubject(Base):
    __tablename__ = "learner_subjects"
    __table_args__ = (
        UniqueConstraint("user_id", "position"),
        CheckConstraint("position BETWEEN 0 AND 29", name="position"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    subject_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    needs_improvement: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


def _choice() -> Mapped[str]:
    return mapped_column(String(20), nullable=False, server_default=text("'auto'"))


class LearningPreferences(Base):
    """How the student wants to be taught. Typed columns, one per concept, each with a CHECK."""

    __tablename__ = "learning_preferences"
    __table_args__ = tuple(
        CheckConstraint(f"{column} IN {choices}", name=column) for column, choices in PREFERENCE_CHOICES.items()
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    language: Mapped[str] = _choice()
    explanation_level: Mapped[str] = _choice()
    pace: Mapped[str] = _choice()
    difficulty: Mapped[str] = _choice()
    real_world_examples: Mapped[str] = _choice()
    visual_explanations: Mapped[str] = _choice()
    personality: Mapped[str] = _choice()
    response_length: Mapped[str] = _choice()
    answer_mode: Mapped[str] = _choice()
    step_by_step: Mapped[str] = _choice()
    ask_before_answer: Mapped[str] = _choice()
    practice_questions: Mapped[str] = _choice()
    mistake_correction: Mapped[str] = _choice()
    highlight_key_concepts: Mapped[str] = _choice()
    updated_at: Mapped[datetime] = _created()


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))


class EmailCode(Base):
    __tablename__ = "email_codes"
    __table_args__ = (
        CheckConstraint(f"purpose in {CODE_PURPOSES}", name="purpose"),
        CheckConstraint("purpose <> 'change_email' OR user_id IS NOT NULL", name="change_email_user"),
        Index("ix_email_codes_email_purpose", "email", "purpose"),
        Index("ix_email_codes_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    # Set only for change_email: the code moves THIS user's account to `email` (the new address).
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))


class AuthAttempt(Base):
    """One throttled auth event (failed login, sign-up, code request).

    Stored in PostgreSQL so limits survive restarts and hold across instances.
    `key_hash` is a SHA-256 of the email or IP, never the raw value.
    """

    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempts_scope_key_created", "scope", "key_hash", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", text("updated_at DESC"), "id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(f"role in {MESSAGE_ROLES}", name="role"),
        CheckConstraint(f"status in {MESSAGE_STATUSES}", name="status"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'complete'"))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created()


class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id"),
        CheckConstraint("rating in (-1, 1)", name="rating"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_events_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = _created()


class KnowledgeSource(Base):
    """A named collection of documents. owner_user_id NULL = global (every signed-in user)."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (Index("ix_knowledge_sources_owner_user_id", "owner_user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class Document(Base):
    """One ingested document, identified by (source, uri). Re-ingesting replaces its chunks."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_id", "uri"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # sha256 of content hash + embedding model + dimension + chunking parameters:
    # a document is re-embedded whenever any of them changes, and only then.
    ingest_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class DocumentChunk(Base):
    """A retrievable passage with its embedding. source_id is denormalised for index-friendly filtering."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal"),
        Index("ix_document_chunks_source_model", "source_id", "embedding_model"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_document_chunks_metadata_gin",
            "metadata",
            postgresql_using="gin",
            postgresql_ops={"metadata": "jsonb_path_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created()

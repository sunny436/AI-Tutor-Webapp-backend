"""PostgreSQL schema: the single source of truth for all application data.

User ─┬─ UserSettings
      ├─ LearnerProfile, LearnerSubject, LearningPreferences   (app/learning)
      ├─ ActivityDay   active time and questions per local day   (app/progress)
      ├─ NotificationPreferences, EmailOutbox                    (app/notifications)
      ├─ SupportRequest                                          (app/support)
      ├─ AppearanceSettings   theme, text size, contrast, motion   (app/appearance)
      ├─ AuthSession
      ├─ Conversation ── Message ── MessageFeedback
      └─ UsageEvent
EmailCode and AuthAttempt support sign-up, reset and throttling.

Knowledge base (RAG):
KnowledgeSource (global, or private to owner_user_id) ── Document ── DocumentChunk (pgvector embedding)

User files (app/files): UserFile ─┬─ UserFileBlob   the original bytes, in 1 MiB rows
                                  └─ FileChunk      extracted text with its embedding (derived data)
Message ── MessageAttachment ── UserFile   (SET NULL when the file is deleted; the name is kept)

`metadata` JSONB columns absorb per-feature data without schema churn.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
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

# Every state an outgoing email can be in (app/notifications/sender.py).
OUTBOX_STATUSES = ("pending", "sending", "sent", "failed", "unknown", "dry_run", "suppressed", "expired")
SUPPORT_KINDS = ("question", "bug", "feedback", "account")
# What an in-app notification is about (app/notifications/inbox.py). Plain text only.
IN_APP_KINDS = (
    "streak_milestone",
    "streak_reminder",
    "daily_reminder",
    "weekly_summary",
    "security_sign_in",
    "security_password_changed",
)
THEMES = ("system", "light", "dark")
FONT_SIZES = ("small", "medium", "large", "x_large")
SUPPORT_STATUSES = ("open", "closed")

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


class ActivityDay(Base):
    """Time active in PadhAI and questions asked, per day in the student's time zone.

    Active time is credited a minute at a time: at most one minute per UTC minute per user
    (`last_minute_utc`), however many tabs or devices report it (app/progress/activity.py).
    """

    __tablename__ = "activity_days"
    __table_args__ = (
        CheckConstraint("active_seconds BETWEEN 0 AND 86400", name="active_seconds"),
        CheckConstraint("questions >= 0", name="questions"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    active_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    questions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_minute_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPreferences(Base):
    """Which emails a student wants. Reminders are off until chosen; sign-in alerts are on.
    Partial indexes let the worker scan only the students who opted in to each reminder."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        Index("ix_notification_preferences_daily_reminder", "user_id", postgresql_where=text("daily_reminder")),
        Index("ix_notification_preferences_streak_warning", "user_id", postgresql_where=text("streak_warning")),
        Index("ix_notification_preferences_weekly_summary", "user_id", postgresql_where=text("weekly_summary")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    daily_reminder: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    streak_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    weekly_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    security_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Reminders in the app's bell (streak, daily, weekly); on unless turned off.
    in_app_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_at: Mapped[datetime] = _created()


class LearningDailyActivity(Base):
    """A day of meaningful learning, dated in India time (app/progress/learning.py): a row
    exists only for such a day, and the streak is derived from these rows alone."""

    __tablename__ = "learning_daily_activity"
    __table_args__ = (CheckConstraint("interactions >= 1", name="interactions"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    activity_date: Mapped[date] = mapped_column(Date, primary_key=True)
    interactions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class UserNotification(Base):
    """A notification in the app's bell. `dedup_key` makes each one happen once (a milestone
    ever, a reminder per day, an alert per event). Title and body are plain text."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        CheckConstraint(f"kind IN {IN_APP_KINDS}", name="kind"),
        UniqueConstraint("user_id", "dedup_key"),
        Index("ix_user_notifications_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(400), nullable=False)
    link: Mapped[str | None] = mapped_column(String(200))
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _created()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailOutbox(Base):
    """Emails the worker sends (python -m app.jobs), written in the transaction that decided to
    send them. At most once: a row found in `sending` after a crash becomes `unknown` and is
    never sent again. `send_before` keeps a late worker from sending stale news."""

    __tablename__ = "email_outbox"
    __table_args__ = (
        CheckConstraint(f"status IN {OUTBOX_STATUSES}", name="status"),
        CheckConstraint("attempts BETWEEN 0 AND 10", name="attempts"),
        Index("ix_email_outbox_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_email_outbox_user_id", "user_id"),
        Index("ix_email_outbox_final_at", "final_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Every email about a user carries their id, so deleting the account deletes its emails.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # "<user>:<kind>:<period>" for reminders: one per period however often the worker runs.
    dedup_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = _created()
    send_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class SupportRequest(Base):
    """A question or report from a signed-in student, kept until the account is deleted."""

    __tablename__ = "support_requests"
    __table_args__ = (
        CheckConstraint(f"kind IN {SUPPORT_KINDS}", name="kind"),
        CheckConstraint(f"status IN {SUPPORT_STATUSES}", name="status"),
        CheckConstraint("char_length(message) <= 4000", name="message_length"),
        UniqueConstraint("user_id", "client_request_id"),
        Index("ix_support_requests_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Chosen by the client, so a retried submit finds the request it already made.
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'open'"))
    created_at: Mapped[datetime] = _created()


class AppearanceSettings(Base):
    """How the app looks for this user, on every device. Presentation only: nothing here
    changes what the tutor says (that is app/learning)."""

    __tablename__ = "appearance_settings"
    __table_args__ = (
        CheckConstraint(f"theme IN {THEMES}", name="theme"),
        CheckConstraint(f"font_size IN {FONT_SIZES}", name="font_size"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    theme: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'system'"))
    font_size: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'medium'"))
    high_contrast: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reduce_motion: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reading_comfort: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    show_streak: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_at: Mapped[datetime] = _created()


class StudyGreeting(Base):
    """The app-level line above a new chat's composer (app/greetings). Not owned by any user: one
    greeting per week, the same for everyone. Live for whole weeks, from `active_from` until
    `retired_from` (both Mondays), so any week's set is fixed; retire, never delete."""

    __tablename__ = "study_greetings"
    __table_args__ = (
        UniqueConstraint("text"),
        CheckConstraint("char_length(btrim(text)) BETWEEN 1 AND 80", name="text"),
        CheckConstraint("EXTRACT(ISODOW FROM active_from) = 1", name="active_from_monday"),
        CheckConstraint(
            "retired_from IS NULL OR (EXTRACT(ISODOW FROM retired_from) = 1 AND retired_from > active_from)",
            name="retired_from",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    text: Mapped[str] = mapped_column(String(80), nullable=False)
    active_from: Mapped[date] = mapped_column(Date, nullable=False)
    retired_from: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _created()


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


# ---- user files (app/files) ----
FILE_KINDS = ("pdf", "docx", "pptx", "xlsx", "csv", "txt", "md", "image")
# processing: bytes stored and verified, text not yet usable; ready: the tutor can use it;
# failed: see error_code; stored: kept, but processing is unavailable right now.
FILE_STATUSES = ("processing", "ready", "failed", "stored")
FILE_BLOB_BYTES = 1024 * 1024


class UserFile(Base):
    """One file in a student's File Library: one row per (user, bytes)."""

    __tablename__ = "user_files"
    __table_args__ = (
        UniqueConstraint("user_id", "sha256"),
        CheckConstraint(f"kind in {FILE_KINDS}", name="kind"),
        CheckConstraint(f"status in {FILE_STATUSES}", name="status"),
        CheckConstraint("size_bytes > 0", name="size_bytes"),
        Index("ix_user_files_user_created", "user_id", text("created_at DESC")),
        Index(
            "ix_user_files_pending",
            "status",
            "updated_at",
            postgresql_where=text("status IN ('processing', 'stored')"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40))
    # Processing claims so far (at most 3); a graceful stop gives its claim back.
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    # When the latest claim started: the lease while status is processing, and the fairness key.
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    char_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class UserFileBlob(Base):
    """The original bytes of a file, in order. Never loaded whole: read and written one row at a time."""

    __tablename__ = "user_file_blobs"
    __table_args__ = (CheckConstraint(f"octet_length(data) BETWEEN 1 AND {FILE_BLOB_BYTES}", name="data"),)

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_files.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class FileChunk(Base):
    """A passage of a user file with its embedding. Derived data: excluded from backups, rebuilt on restore.

    No vector index: a turn searches only the few files attached to its conversation, exactly."""

    __tablename__ = "file_chunks"
    __table_args__ = (UniqueConstraint("file_id", "ordinal"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_files.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # {"page": n} (PDF), {"slide": n} (PPTX) or {"sheet": name} (XLSX); {} otherwise.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)


class MessageAttachment(Base):
    """A file attached to a user message. The filename is kept when the file is deleted (file_id NULL)."""

    __tablename__ = "message_attachments"
    __table_args__ = (UniqueConstraint("message_id", "position"), Index("ix_message_attachments_file_id", "file_id"))

    id: Mapped[uuid.UUID] = _uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_files.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = _created()

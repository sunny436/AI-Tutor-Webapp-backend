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

Question bank (app/qbank): QbSyllabusVersion, QbBook ── QbChapter ── QbTopic ─┬─ QbConcept
                                                                         ├─ QbCase
                                                                         └─ QbQuestion
User ── QbSet ── QbSetItem   (a question served to the student, and their answer)

`metadata` JSONB columns absorb per-feature data without schema churn.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID, ExcludeConstraint
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
    "security_google_linked",
    "security_two_factor_on",
    "security_two_factor_off",
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
    # Better Auth's flag. email_verified_at follows it both ways (trigger, 0012), for older code.
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The credential's argon2 hash, mirrored from auth_accounts both ways (trigger, 0012) so a
    # rollback signs people in with the password in force; None = no password (Google only).
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    # Incremented by every change to the identity profile; writes must name the version they
    # read (optimistic concurrency), so a stale form cannot silently overwrite a newer edit.
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    timezone: Mapped[str | None] = mapped_column(String(64))  # IANA name, set by the user
    avatar_hash: Mapped[str | None] = mapped_column(String(32))  # names the current photo; None = no photo
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image: Mapped[str | None] = mapped_column(Text)  # Better Auth's field; never filled (no Google photos)
    # Better Auth's two-step sign-in (0013): once true, every sign-in asks for the second step.
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


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
    # The exam the student prepares for (0017): the practice plan's exam window (app/progress/practice.py).
    exam_date: Mapped[date | None] = mapped_column(Date)


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
    # "Clear all": no longer in the bell, and read. The row (and its dedup_key) stays until
    # retention deletes it with the other read notifications.
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    # SHA-256 of the token: the API finds sessions by it. For Better Auth's sessions a trigger
    # computes it from `token` (0012); older sessions have only the hash. Nullable only because
    # Better Auth refuses to start while a column it never writes is required.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token: Mapped[str | None] = mapped_column(Text, unique=True)  # Better Auth's session token
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()  # Better Auth's updatedAt
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))


class AuthAccount(Base):
    """A way to sign in (Better Auth's `account`): provider_id "credential" holds the argon2 hash
    (account_id = the user id), "google" the Google user id. Written by the web app's Better Auth;
    the API reads the password to re-authenticate. Google's tokens are never stored."""

    __tablename__ = "auth_accounts"
    __table_args__ = (
        UniqueConstraint("provider_id", "account_id"),
        Index("ix_auth_accounts_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    id_token: Mapped[str | None] = mapped_column(Text)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str | None] = mapped_column(Text)
    password: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class AuthTwoFactor(Base):
    """Better Auth's `twoFactor` (0013): one user's authenticator secret and recovery codes, both
    encrypted with the web app's BETTER_AUTH_SECRET (the API never reads them), and the failure
    count that locks the second step after repeated wrong codes. Written by Better Auth only."""

    __tablename__ = "auth_two_factors"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    secret: Mapped[str] = mapped_column(Text, nullable=False)
    backup_codes: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    failed_verification_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class AuthVerification(Base):
    """Better Auth's `verification`: email codes (identifier "<type>-otp-<email>", value the
    code's SHA-256 + ":" + attempts) and OAuth states. Short-lived; retention deletes expired rows."""

    __tablename__ = "auth_verifications"
    __table_args__ = (
        Index("ix_auth_verifications_identifier", "identifier"),
        Index("ix_auth_verifications_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


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


# ---------------------------------------------------------------------------------- study time
# app/study: study sessions made of segments (studying or paused, each with its subject, chapter
# and activity), the active time credited inside them, and app presence. Every rule is in
# app/study/service.py; the database enforces what can be enforced (0014_study_time).
STUDY_STATUSES = ("active", "paused", "ended")
STUDY_END_REASONS = ("ended", "stale", "limit")
STUDY_SEGMENT_KINDS = ("study", "paused")
STUDY_ACTIVITIES = ("reading", "practice", "revision", "test")


class StudySession(Base):
    """One study session: from the student's Start to End, a stale end (no study activity for a
    while) or the length limit. At most one open session per student, on every device."""

    __tablename__ = "study_sessions"
    __table_args__ = (
        CheckConstraint(f"status in {STUDY_STATUSES}", name="status"),
        CheckConstraint(f"end_reason is null or end_reason in {STUDY_END_REASONS}", name="end_reason"),
        CheckConstraint("(status = 'ended') = (ended_at is not null)", name="ended"),
        CheckConstraint("(status = 'ended') = (end_reason is not null)", name="ended_reason"),
        CheckConstraint("(status = 'paused') = (paused_at is not null)", name="paused"),
        CheckConstraint("ended_at is null or ended_at >= started_at", name="order"),
        UniqueConstraint("id", "user_id"),
        Index("uq_study_sessions_open", "user_id", unique=True, postgresql_where=text("ended_at is null")),
        Index("ix_study_sessions_user_id_started_at", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(16))
    alive_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StudySegment(Base):
    """A stretch of one session in one state (studying or paused) and one context."""

    __tablename__ = "study_segments"
    __table_args__ = (
        CheckConstraint(f"kind in {STUDY_SEGMENT_KINDS}", name="kind"),
        CheckConstraint(f"activity in {STUDY_ACTIVITIES}", name="activity"),
        CheckConstraint("ended_at is null or ended_at >= started_at", name="order"),
        CheckConstraint(
            "(chapter_id is null) = (chapter_title is null) and (chapter_id is null) = (book_id is null)",
            name="chapter",
        ),
        UniqueConstraint("id", "user_id", "kind"),
        ForeignKeyConstraint(
            ["session_id", "user_id"], ["study_sessions.id", "study_sessions.user_id"], ondelete="CASCADE"
        ),
        Index("uq_study_segments_open", "session_id", unique=True, postgresql_where=text("ended_at is null")),
        Index("ix_study_segments_user_id_started_at", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_code: Mapped[str | None] = mapped_column(String(40))
    chapter_id: Mapped[str | None] = mapped_column(String(120))
    book_id: Mapped[str | None] = mapped_column(String(120))
    chapter_title: Mapped[str | None] = mapped_column(String(200))
    activity: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudyActiveInterval(Base):
    """Credited active study time: only inside a studying segment (the composite key includes the
    segment's kind, fixed to 'study'), and never overlapping another of the same student's."""

    __tablename__ = "study_active_intervals"
    __table_args__ = (
        CheckConstraint("segment_kind = 'study'", name="segment_kind"),
        CheckConstraint("started_at < ended_at", name="order"),
        ForeignKeyConstraint(
            ["segment_id", "user_id", "segment_kind"],
            ["study_segments.id", "study_segments.user_id", "study_segments.kind"],
            ondelete="CASCADE",
        ),
        ExcludeConstraint(
            ("user_id", "="),
            (text("tstzrange(started_at, ended_at)"), "&&"),
            name="ex_study_active_intervals_overlap",
            using="gist",
        ),
        Index("ix_study_active_intervals_user_id_started_at", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    segment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    segment_kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'study'"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StudyClient(Base):
    """One page load of PadhAI (a tab or a device): its last observation, from which its next
    active report is credited."""

    __tablename__ = "study_clients"
    __table_args__ = (Index("ix_study_clients_user_id_last_beat_at", "user_id", "last_beat_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    last_beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_beat_active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class StudyBeat(Base):
    """Beats already received (by their id), so a retried or replayed beat changes nothing."""

    __tablename__ = "study_beats"
    __table_args__ = (Index("ix_study_beats_user_id_received_at", "user_id", "received_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    beat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppSession(Base):
    """A run of time with PadhAI open (visible or not) on any of the student's tabs or devices:
    one row per run, however many are open."""

    __tablename__ = "app_sessions"
    __table_args__ = (
        CheckConstraint("last_seen_at >= started_at", name="order"),
        CheckConstraint("ended_at is null or ended_at = last_seen_at", name="ended"),
        Index("uq_app_sessions_open", "user_id", unique=True, postgresql_where=text("ended_at is null")),
        Index("ix_app_sessions_user_id_started_at", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ------------------------------------------------------------------ question bank (app/qbank)
QB_LANGUAGES = ("english", "hindi", "sanskrit")  # the language the content is written in
QB_DIFFICULTIES = ("easy", "medium", "hard")
QB_FORMATS = ("mcq", "assertion_reason", "case_based", "source_based")
QB_COMPETENCIES = ("knowledge_understanding", "application", "analysis_evaluation")
QB_SOURCE_KINDS = ("original", "ncert_exercise", "cbse_official")
QB_REVIEW_STATUSES = ("draft", "needs_review", "approved", "rejected")
QB_SET_MODES = ("adaptive", "test", "chat")  # 0017: "chat", a question-bank test in the chat
QB_SERVABLE = "review_status IN ('approved', 'needs_review') AND is_active"  # 0016: practice serves unreviewed ones


class QbSyllabusVersion(Base):
    """A curriculum's syllabus for one academic session (e.g. CBSE 2026-27): what a question was
    reviewed against."""

    __tablename__ = "qb_syllabus_versions"
    __table_args__ = (
        UniqueConstraint("curriculum", "academic_session"),
        CheckConstraint("curriculum IN ('cbse')", name="curriculum"),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    curriculum: Mapped[str] = mapped_column(Text, nullable=False)
    academic_session: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)


class QbBook(Base):
    """A textbook in one language (NCERT's id, e.g. science-c10-en): it fixes class, subject and language."""

    __tablename__ = "qb_books"
    __table_args__ = (
        UniqueConstraint("book_id", "class_level", "subject_code", "language"),
        CheckConstraint("curriculum IN ('cbse')", name="curriculum"),
        CheckConstraint("class_level BETWEEN 6 AND 12", name="class_level"),
        CheckConstraint(f"language IN {QB_LANGUAGES}", name="language"),
        CheckConstraint("subject_code ~ '^[a-z_]+$'", name="subject_code"),
    )

    book_id: Mapped[str] = mapped_column(Text, primary_key=True)
    curriculum: Mapped[str] = mapped_column(Text, nullable=False)
    class_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    subject_code: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    edition: Mapped[str] = mapped_column(Text, nullable=False)


class QbChapter(Base):
    """A chapter of one book. question_count is kept by the database (0015's triggers) and checked
    against max_questions, so the cap holds under concurrent writes."""

    __tablename__ = "qb_chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "chapter_number"),
        UniqueConstraint("chapter_id", "book_id"),
        CheckConstraint("max_questions BETWEEN 1 AND 1000", name="max_questions"),
        CheckConstraint("question_count BETWEEN 0 AND max_questions", name="question_count"),
    )

    chapter_id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(Text, ForeignKey("qb_books.book_id"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    old_chapter_number: Mapped[int | None] = mapped_column(SmallInteger)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    ncert_chapter_id: Mapped[str | None] = mapped_column(Text)
    max_questions: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1000"))
    question_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))


class QbTopic(Base):
    __tablename__ = "qb_topics"
    __table_args__ = (UniqueConstraint("chapter_id", "topic_number"), UniqueConstraint("topic_id", "chapter_id"))

    topic_id: Mapped[str] = mapped_column(Text, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(Text, ForeignKey("qb_chapters.chapter_id"), nullable=False)
    topic_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    ncert_sections: Mapped[str | None] = mapped_column(Text)


class QbConcept(Base):
    """What a question in a topic practises, and the learning objective behind it."""

    __tablename__ = "qb_concepts"
    __table_args__ = (CheckConstraint("concept_tag ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="concept_tag"),)

    topic_id: Mapped[str] = mapped_column(Text, ForeignKey("qb_topics.topic_id"), primary_key=True)
    concept_tag: Mapped[str] = mapped_column(Text, primary_key=True)
    learning_objective: Mapped[str] = mapped_column(Text, nullable=False)


class QbCase(Base):
    """A shared passage for case- and source-based questions of one topic."""

    __tablename__ = "qb_cases"
    __table_args__ = (
        UniqueConstraint("case_id", "topic_id"),
        CheckConstraint("length(body) BETWEEN 100 AND 4000", name="body"),
    )

    case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    topic_id: Mapped[str] = mapped_column(Text, ForeignKey("qb_topics.topic_id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class QbQuestion(Base):
    """One stored MCQ. Its place (book, class, subject, language, chapter, topic, concept, case) is
    tied together by composite keys; it is served only when approved and active."""

    __tablename__ = "qb_questions"
    __table_args__ = (
        UniqueConstraint("question_id", "topic_id"),
        UniqueConstraint("fingerprint"),
        ForeignKeyConstraint(
            ["book_id", "class_level", "subject_code", "language"],
            ["qb_books.book_id", "qb_books.class_level", "qb_books.subject_code", "qb_books.language"],
        ),
        ForeignKeyConstraint(["chapter_id", "book_id"], ["qb_chapters.chapter_id", "qb_chapters.book_id"]),
        ForeignKeyConstraint(["topic_id", "chapter_id"], ["qb_topics.topic_id", "qb_topics.chapter_id"]),
        ForeignKeyConstraint(["topic_id", "concept_tag"], ["qb_concepts.topic_id", "qb_concepts.concept_tag"]),
        ForeignKeyConstraint(["case_id", "topic_id"], ["qb_cases.case_id", "qb_cases.topic_id"]),
        ForeignKeyConstraint(["syllabus_version"], ["qb_syllabus_versions.code"]),
        CheckConstraint(f"difficulty IN {QB_DIFFICULTIES}", name="difficulty"),
        CheckConstraint(f"question_format IN {QB_FORMATS}", name="question_format"),
        CheckConstraint(f"competency IN {QB_COMPETENCIES}", name="competency"),
        CheckConstraint("(question_format IN ('case_based', 'source_based')) = (case_id IS NOT NULL)", name="case"),
        CheckConstraint("correct_option IN ('A', 'B', 'C', 'D')", name="correct_option"),
        CheckConstraint(
            "lower(option_a) NOT IN (lower(option_b), lower(option_c), lower(option_d)) "
            "AND lower(option_b) NOT IN (lower(option_c), lower(option_d)) AND lower(option_c) <> lower(option_d)",
            name="distinct_options",
        ),
        CheckConstraint("marks BETWEEN 1 AND 5", name="marks"),
        CheckConstraint(f"source_kind IN {QB_SOURCE_KINDS}", name="source_kind"),
        CheckConstraint("source_kind <> 'cbse_official' OR source_url IS NOT NULL", name="official_source"),
        CheckConstraint(f"review_status IN {QB_REVIEW_STATUSES}", name="review_status"),
        CheckConstraint(
            "review_status <> 'approved' OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_hash = content_hash)",
            name="approved",
        ),
        CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$' AND content_hash ~ '^[0-9a-f]{64}$'", name="hashes"),
        Index(
            "ix_qb_questions_select",
            "language",
            "class_level",
            "subject_code",
            "chapter_id",
            "topic_id",
            "difficulty",
            postgresql_where=text(QB_SERVABLE),
        ),
        Index("ix_qb_questions_adaptive", "topic_id", "level", "concept_tag", postgresql_where=text(QB_SERVABLE)),
    )

    question_id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(Text, nullable=False)
    class_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    subject_code: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_id: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[str] = mapped_column(Text, nullable=False)
    concept_tag: Mapped[str] = mapped_column(Text, nullable=False)
    syllabus_version: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(
        SmallInteger,
        Computed("CASE difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END", persisted=True),
        nullable=False,
    )
    question_format: Mapped[str] = mapped_column(Text, nullable=False)
    competency: Mapped[str] = mapped_column(Text, nullable=False)
    case_id: Mapped[str | None] = mapped_column(Text)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    option_a: Mapped[str] = mapped_column(Text, nullable=False)
    option_b: Mapped[str] = mapped_column(Text, nullable=False)
    option_c: Mapped[str] = mapped_column(Text, nullable=False)
    option_d: Mapped[str] = mapped_column(Text, nullable=False)
    correct_option: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    marks: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_hash: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class QbSet(Base):
    """A practice set (adaptive, one question at a time), a test, or a test in the chat (`chat`: its
    request_id is the reply's id; app/qbank/chat_tests.py), owned by one student. request_id makes
    creating it idempotent. It has no link to a conversation: deleting the chat keeps its answers."""

    __tablename__ = "qb_sets"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("user_id", "request_id"),
        CheckConstraint(f"mode IN {QB_SET_MODES}", name="mode"),
        CheckConstraint("requested BETWEEN 1 AND 100", name="requested"),
        CheckConstraint("served BETWEEN 0 AND requested", name="served"),
        Index("ix_qb_sets_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requested: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    served: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = _created()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QbSetItem(Base):
    """A question served in a set, and the student's answer: graded by the database, final once given."""

    __tablename__ = "qb_set_items"
    __table_args__ = (
        UniqueConstraint("set_id", "question_id"),
        ForeignKeyConstraint(["set_id", "user_id"], ["qb_sets.id", "qb_sets.user_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["question_id", "topic_id"], ["qb_questions.question_id", "qb_questions.topic_id"]),
        CheckConstraint("position >= 1", name="position"),
        CheckConstraint("chosen IN ('A', 'B', 'C', 'D')", name="chosen"),
        CheckConstraint(
            "(chosen IS NULL) = (answered_at IS NULL) AND (chosen IS NULL) = (is_correct IS NULL)", name="answer"
        ),
        CheckConstraint("answered_at IS NULL OR answered_at >= served_at", name="order"),
        Index("ix_qb_set_items_user_id_topic_id_answered_at", "user_id", "topic_id", "answered_at"),
    )

    set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    question_id: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[str] = mapped_column(Text, nullable=False)
    served_at: Mapped[datetime] = _created()
    chosen: Mapped[str | None] = mapped_column(CHAR(1))
    hinted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The question's content_hash when it was served, set by the trigger (0017); NULL before 0017.
    served_hash: Mapped[str | None] = mapped_column(Text)

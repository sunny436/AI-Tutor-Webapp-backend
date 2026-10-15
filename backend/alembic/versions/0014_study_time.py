"""Study time: study sessions, their segments, credited active intervals, clients, beats and
app sessions (app/study).

Revision ID: 0014_study_time
Revises: 0013_two_factor
Create Date: 2026-10-15

What the database itself guarantees (app/study/service.py has the rest):
- one open study session and one open app session per student (partial unique indexes);
- a segment belongs to its session's student, an interval to its segment's student, and an
  interval only to a *studying* segment (composite foreign keys; the interval carries the
  segment's kind, fixed to 'study');
- a student's credited intervals never overlap (gist EXCLUDE; needs btree_gist, a trusted
  extension);
- at commit (deferred constraint triggers): an interval lies inside its segment, a segment inside
  its session, and closing a segment or a session leaves nothing outside it.

Additive and backward compatible: new tables, an extension and triggers only; the release before
this one never reads them. NOT rollback-safe in the destructive sense: the downgrade drops every
study table and its data, so it must never run without the owner's explicit authorization (a
deploy never downgrades).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0014_study_time"
down_revision = "0013_two_factor"
branch_labels = None
depends_on = None

STUDY_STATUSES = ("active", "paused", "ended")
STUDY_END_REASONS = ("ended", "stale", "limit")
STUDY_SEGMENT_KINDS = ("study", "paused")
STUDY_ACTIVITIES = ("reading", "practice", "revision", "test")


def _uuid(name: str, **kwargs) -> sa.Column:
    return sa.Column(name, pg.UUID(as_uuid=True), **kwargs)


def _at(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


BOUNDS = """
CREATE FUNCTION study_bounds_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'study_active_intervals' THEN
        IF NOT EXISTS (
            SELECT 1 FROM study_segments s
            WHERE s.id = NEW.segment_id AND s.user_id = NEW.user_id AND s.kind = 'study'
              AND NEW.started_at >= s.started_at AND (s.ended_at IS NULL OR NEW.ended_at <= s.ended_at)
        ) THEN
            RAISE EXCEPTION 'study interval % lies outside its studying segment', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
    ELSIF TG_TABLE_NAME = 'study_segments' THEN
        IF NOT EXISTS (
            SELECT 1 FROM study_sessions x
            WHERE x.id = NEW.session_id AND x.user_id = NEW.user_id AND NEW.started_at >= x.started_at
              AND (x.ended_at IS NULL OR (NEW.ended_at IS NOT NULL AND NEW.ended_at <= x.ended_at))
        ) THEN
            RAISE EXCEPTION 'study segment % lies outside its session', NEW.id USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.ended_at IS NOT NULL AND EXISTS (
            SELECT 1 FROM study_active_intervals i WHERE i.segment_id = NEW.id AND i.ended_at > NEW.ended_at
        ) THEN
            RAISE EXCEPTION 'study segment % ends before its credited time', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
    ELSIF TG_TABLE_NAME = 'study_sessions' THEN
        IF NEW.ended_at IS NOT NULL AND EXISTS (
            SELECT 1 FROM study_segments s
            WHERE s.session_id = NEW.id AND (s.ended_at IS NULL OR s.ended_at > NEW.ended_at)
        ) THEN
            RAISE EXCEPTION 'study session % ends with a segment still open or later', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NULL;
END;
$$
"""
# One statement per execute (asyncpg prepares each).
TRIGGERS = [
    f"CREATE CONSTRAINT TRIGGER {table}_bounds AFTER {events} ON {table} "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION study_bounds_check()"
    for table, events in (
        ("study_active_intervals", "INSERT OR UPDATE"),
        ("study_segments", "INSERT OR UPDATE"),
        ("study_sessions", "UPDATE"),
    )
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "study_sessions",
        _uuid("id", server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("user_id", nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _at("started_at"),
        _at("paused_at", nullable=True),
        _at("ended_at", nullable=True),
        sa.Column("end_reason", sa.String(16)),
        _at("alive_at"),
        sa.CheckConstraint(f"status in {STUDY_STATUSES}", name=op.f("ck_study_sessions_status")),
        sa.CheckConstraint(
            f"end_reason is null or end_reason in {STUDY_END_REASONS}", name=op.f("ck_study_sessions_end_reason")
        ),
        sa.CheckConstraint("(status = 'ended') = (ended_at is not null)", name=op.f("ck_study_sessions_ended")),
        sa.CheckConstraint(
            "(status = 'ended') = (end_reason is not null)", name=op.f("ck_study_sessions_ended_reason")
        ),
        sa.CheckConstraint("(status = 'paused') = (paused_at is not null)", name=op.f("ck_study_sessions_paused")),
        sa.CheckConstraint("ended_at is null or ended_at >= started_at", name=op.f("ck_study_sessions_order")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_study_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_sessions")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_study_sessions_id_user_id")),
    )
    op.create_index(
        "uq_study_sessions_open",
        "study_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at is null"),
    )
    op.create_index("ix_study_sessions_user_id_started_at", "study_sessions", ["user_id", "started_at"])

    op.create_table(
        "study_segments",
        _uuid("id", server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("session_id", nullable=False),
        _uuid("user_id", nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("subject_code", sa.String(40)),
        sa.Column("chapter_id", sa.String(120)),
        sa.Column("book_id", sa.String(120)),
        sa.Column("chapter_title", sa.String(200)),
        sa.Column("activity", sa.String(16), nullable=False),
        _at("started_at"),
        _at("ended_at", nullable=True),
        sa.CheckConstraint(f"kind in {STUDY_SEGMENT_KINDS}", name=op.f("ck_study_segments_kind")),
        sa.CheckConstraint(f"activity in {STUDY_ACTIVITIES}", name=op.f("ck_study_segments_activity")),
        sa.CheckConstraint("ended_at is null or ended_at >= started_at", name=op.f("ck_study_segments_order")),
        sa.CheckConstraint(
            "(chapter_id is null) = (chapter_title is null) and (chapter_id is null) = (book_id is null)",
            name=op.f("ck_study_segments_chapter"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["study_sessions.id", "study_sessions.user_id"],
            ondelete="CASCADE",
            name=op.f("fk_study_segments_session_id_study_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_segments")),
        sa.UniqueConstraint("id", "user_id", "kind", name=op.f("uq_study_segments_id_user_id_kind")),
    )
    op.create_index(
        "uq_study_segments_open",
        "study_segments",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("ended_at is null"),
    )
    op.create_index("ix_study_segments_user_id_started_at", "study_segments", ["user_id", "started_at"])

    op.create_table(
        "study_active_intervals",
        _uuid("id", server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("segment_id", nullable=False),
        _uuid("user_id", nullable=False),
        sa.Column("segment_kind", sa.String(16), server_default=sa.text("'study'"), nullable=False),
        _at("started_at"),
        _at("ended_at"),
        sa.CheckConstraint("segment_kind = 'study'", name=op.f("ck_study_active_intervals_segment_kind")),
        sa.CheckConstraint("started_at < ended_at", name=op.f("ck_study_active_intervals_order")),
        sa.ForeignKeyConstraint(
            ["segment_id", "user_id", "segment_kind"],
            ["study_segments.id", "study_segments.user_id", "study_segments.kind"],
            ondelete="CASCADE",
            name=op.f("fk_study_active_intervals_segment_id_study_segments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_active_intervals")),
        pg.ExcludeConstraint(
            ("user_id", "="),
            (sa.text("tstzrange(started_at, ended_at)"), "&&"),
            name="ex_study_active_intervals_overlap",
            using="gist",
        ),
    )
    op.create_index("ix_study_active_intervals_user_id_started_at", "study_active_intervals", ["user_id", "started_at"])

    op.create_table(
        "study_clients",
        _uuid("user_id", nullable=False),
        _uuid("client_id", nullable=False),
        _at("last_beat_at"),
        sa.Column("last_beat_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_study_clients_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "client_id", name=op.f("pk_study_clients")),
    )
    op.create_index("ix_study_clients_user_id_last_beat_at", "study_clients", ["user_id", "last_beat_at"])

    op.create_table(
        "study_beats",
        _uuid("user_id", nullable=False),
        _uuid("beat_id", nullable=False),
        _at("received_at"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_study_beats_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "beat_id", name=op.f("pk_study_beats")),
    )
    op.create_index("ix_study_beats_user_id_received_at", "study_beats", ["user_id", "received_at"])

    op.create_table(
        "app_sessions",
        _uuid("id", server_default=sa.text("gen_random_uuid()"), nullable=False),
        _uuid("user_id", nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        _at("started_at"),
        _at("last_seen_at"),
        _at("ended_at", nullable=True),
        sa.CheckConstraint("last_seen_at >= started_at", name=op.f("ck_app_sessions_order")),
        sa.CheckConstraint("ended_at is null or ended_at = last_seen_at", name=op.f("ck_app_sessions_ended")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_app_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_sessions")),
    )
    op.create_index(
        "uq_app_sessions_open", "app_sessions", ["user_id"], unique=True, postgresql_where=sa.text("ended_at is null")
    )
    op.create_index("ix_app_sessions_user_id_started_at", "app_sessions", ["user_id", "started_at"])

    op.execute(BOUNDS)
    for trigger in TRIGGERS:
        op.execute(trigger)


def downgrade() -> None:
    # Destroys every study table and its data: never without the owner's explicit authorization.
    op.execute("DROP TRIGGER IF EXISTS study_sessions_bounds ON study_sessions")
    op.execute("DROP TRIGGER IF EXISTS study_segments_bounds ON study_segments")
    op.execute("DROP TRIGGER IF EXISTS study_active_intervals_bounds ON study_active_intervals")
    op.execute("DROP FUNCTION IF EXISTS study_bounds_check()")
    for table in ("app_sessions", "study_beats", "study_clients", "study_active_intervals", "study_segments"):
        op.drop_table(table)
    op.drop_table("study_sessions")

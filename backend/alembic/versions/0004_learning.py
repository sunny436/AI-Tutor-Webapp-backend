"""Learning: learner profile, subjects and learning preferences (what the tutor is told).

Revision ID: 0004_learning
Revises: 0003_identity
Create Date: 2026-09-25

Additive only: three new tables, each owned by a user (cascade on delete). Nothing the live
release reads changes. The choices are copied here, not imported, so this revision stays the
same when the application's lists grow (a new choice needs a new revision that replaces the
CHECK).

Constraint names go through op.f(): they are final. Without it the naming convention is applied
a second time (0001 and 0003 have such doubled names, e.g. ck_messages_ck_messages_role).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004_learning"
down_revision = "0003_identity"
branch_labels = None
depends_on = None

NOW = sa.text("clock_timestamp()")

MAIN_GOALS = ("board_exams", "competitive_exam", "better_marks", "understand_concepts", "homework_help", "other")
PREFERENCE_CHOICES = {
    "language": ("auto", "english", "hindi", "hinglish"),
    "explanation_level": ("auto", "simple", "standard", "detailed"),
    "pace": ("auto", "slow", "steady", "fast"),
    "difficulty": ("auto", "easy", "medium", "hard"),
    "real_world_examples": ("auto", "more", "fewer"),
    "visual_explanations": ("auto", "more", "fewer"),
    "personality": ("auto", "friendly", "encouraging", "professional"),
    "response_length": ("auto", "short", "medium", "long"),
    "answer_mode": ("auto", "direct", "hints_first", "socratic"),
    "step_by_step": ("auto", "on", "off"),
    "ask_before_answer": ("auto", "on", "off"),
    "practice_questions": ("auto", "on", "off"),
    "mistake_correction": ("auto", "gentle", "direct"),
    "highlight_key_concepts": ("auto", "on", "off"),
}


def _user_pk(table: str) -> list:
    return [
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=op.f(f"fk_{table}_user_id_users")),
    ]


def upgrade() -> None:
    op.create_table(
        "learner_profiles",
        *_user_pk("learner_profiles"),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("subjects_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("grade", sa.String(40)),
        sa.Column("board", sa.String(40)),
        sa.Column("board_state", sa.String(40)),
        sa.Column("medium", sa.String(40)),
        sa.Column("academic_year", sa.String(40)),
        sa.Column("main_goal", sa.String(40)),
        sa.Column("target_exam", sa.String(80)),
        sa.Column("target_score_percent", sa.SmallInteger()),
        sa.Column("weak_topics", pg.ARRAY(sa.String(60)), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("daily_active_minutes_goal", sa.SmallInteger()),
        sa.Column("weekly_active_minutes_goal", sa.SmallInteger()),
        sa.Column("preferred_study_time", sa.Time()),
        sa.Column("short_term_goal", sa.String(280)),
        sa.Column("long_term_goal", sa.String(280)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_learner_profiles")),
        sa.CheckConstraint(f"main_goal IN {MAIN_GOALS}", name=op.f("ck_learner_profiles_main_goal")),
        sa.CheckConstraint(
            "target_score_percent BETWEEN 0 AND 100", name=op.f("ck_learner_profiles_target_score_percent")
        ),
        sa.CheckConstraint(
            "daily_active_minutes_goal BETWEEN 0 AND 720", name=op.f("ck_learner_profiles_daily_active_minutes_goal")
        ),
        sa.CheckConstraint(
            "weekly_active_minutes_goal BETWEEN 0 AND 5040", name=op.f("ck_learner_profiles_weekly_active_minutes_goal")
        ),
        sa.CheckConstraint("cardinality(weak_topics) <= 10", name=op.f("ck_learner_profiles_weak_topics")),
        sa.CheckConstraint("board_state IS NULL OR board = 'state'", name=op.f("ck_learner_profiles_board_state")),
    )

    op.create_table(
        "learner_subjects",
        *_user_pk("learner_subjects"),
        sa.Column("subject_code", sa.String(40), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("is_priority", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("needs_improvement", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("user_id", "subject_code", name=op.f("pk_learner_subjects")),
        sa.UniqueConstraint("user_id", "position", name=op.f("uq_learner_subjects_user_id_position")),
        sa.CheckConstraint("position BETWEEN 0 AND 29", name=op.f("ck_learner_subjects_position")),
    )

    op.create_table(
        "learning_preferences",
        *_user_pk("learning_preferences"),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *[
            sa.Column(column, sa.String(20), nullable=False, server_default=sa.text("'auto'"))
            for column in PREFERENCE_CHOICES
        ],
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_learning_preferences")),
        *[
            sa.CheckConstraint(f"{column} IN {choices}", name=op.f(f"ck_learning_preferences_{column}"))
            for column, choices in PREFERENCE_CHOICES.items()
        ],
    )


def downgrade() -> None:
    op.drop_table("learning_preferences")
    op.drop_table("learner_subjects")
    op.drop_table("learner_profiles")

"""Initial schema: users, auth, conversations, messages, feedback, usage; pgvector enabled.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("clock_timestamp()")
UUID_PK = sa.text("gen_random_uuid()")
EMPTY_JSON = sa.text("'{}'::jsonb")


def _id():
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=UUID_PK)


def _ts(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=NOW)


def upgrade() -> None:
    # pgvector: the vector layer for future embeddings/RAG. No vector tables yet;
    # they arrive with the feature that chooses an embedding model and dimension.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        _id(),
        sa.Column("email", pg.CITEXT(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(80)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "user_settings",
        sa.Column("user_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("preferences", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_user_settings_user_id_users"),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_settings"),
    )

    op.create_table(
        "auth_sessions",
        _id(),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        _ts("created_at"),
        _ts("last_seen_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("ip", sa.String(64)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_auth_sessions_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    op.create_table(
        "email_codes",
        _id(),
        sa.Column("email", pg.CITEXT(), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        sa.CheckConstraint("purpose in ('verify_email', 'reset_password')", name="ck_email_codes_purpose"),
        sa.PrimaryKeyConstraint("id", name="pk_email_codes"),
    )
    op.create_index("ix_email_codes_email_purpose", "email_codes", ["email", "purpose"])

    op.create_table(
        "auth_attempts",
        _id(),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_attempts"),
    )
    op.create_index("ix_auth_attempts_scope_key_created", "auth_attempts", ["scope", "key_hash", "created_at"])

    op.create_table(
        "conversations",
        _id(),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("metadata", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_conversations_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", sa.text("updated_at DESC"), "id"])

    op.create_table(
        "messages",
        _id(),
        sa.Column("conversation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'complete'")),
        sa.Column("metadata", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
        _ts("created_at"),
        sa.CheckConstraint("role in ('user', 'assistant', 'system')", name="ck_messages_role"),
        sa.CheckConstraint(
            "status in ('complete', 'streaming', 'cancelled', 'error', 'superseded')", name="ck_messages_status"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
            name="fk_messages_conversation_id_conversations",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at", "id"])

    op.create_table(
        "message_feedback",
        _id(),
        sa.Column("message_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.String(2000)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("rating in (-1, 1)", name="ck_message_feedback_rating"),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="CASCADE", name="fk_message_feedback_message_id_messages"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_message_feedback_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_feedback"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_feedback_message_id_user_id"),
    )

    op.create_table(
        "usage_events",
        _id(),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", pg.UUID(as_uuid=True)),
        sa.Column("message_id", pg.UUID(as_uuid=True)),
        sa.Column("provider", sa.String(64)),
        sa.Column("model", sa.String(200)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("ttft_ms", sa.Integer()),
        sa.Column("outcome", sa.String(16), nullable=False),
        _ts("created_at"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_usage_events_user_id_users"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="SET NULL",
            name="fk_usage_events_conversation_id_conversations",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="SET NULL", name="fk_usage_events_message_id_messages"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_usage_events"),
    )
    op.create_index("ix_usage_events_user_created", "usage_events", ["user_id", "created_at"])


def downgrade() -> None:
    for table in (
        "usage_events",
        "message_feedback",
        "messages",
        "conversations",
        "auth_attempts",
        "email_codes",
        "auth_sessions",
        "user_settings",
        "users",
    ):
        op.drop_table(table)
    # Extensions are left in place: other objects may depend on them.

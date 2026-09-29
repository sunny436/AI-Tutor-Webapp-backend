"""User files: the File Library, chat attachments and their searchable text.

Revision ID: 0010_user_files
Revises: 0009_study_greetings
Create Date: 2026-09-30

Additive only: four new tables, no change to an existing one, so older code runs unchanged on
this schema (a rollback never needs the downgrade). The original bytes live in PostgreSQL in
1 MiB rows (user_file_blobs): deleted with the file or the account by FK cascade, and backed up
with everything else. file_chunks is derived data (re-created by re-processing), vector(1536)
like document_chunks, with no vector index: a turn searches only the few files attached to its
conversation, exactly. Choices are copied here, not imported.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

revision = "0010_user_files"
down_revision = "0009_study_greetings"
branch_labels = None
depends_on = None

NOW = sa.text("clock_timestamp()")
DIMENSIONS = 1536
FILE_KINDS = ("pdf", "docx", "pptx", "xlsx", "csv", "txt", "md", "image")
FILE_STATUSES = ("processing", "ready", "failed", "stored")
FILE_BLOB_BYTES = 1024 * 1024


def upgrade() -> None:
    op.create_table(
        "user_files",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_user_files_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_files")),
        sa.UniqueConstraint("user_id", "sha256", name=op.f("uq_user_files_user_id_sha256")),
        sa.CheckConstraint(f"kind in {FILE_KINDS}", name=op.f("ck_user_files_kind")),
        sa.CheckConstraint(f"status in {FILE_STATUSES}", name=op.f("ck_user_files_status")),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_user_files_size_bytes")),
    )
    op.create_index("ix_user_files_user_created", "user_files", ["user_id", sa.text("created_at DESC")])
    op.create_index(
        "ix_user_files_pending",
        "user_files",
        ["status", "updated_at"],
        postgresql_where=sa.text("status IN ('processing', 'stored')"),
    )

    op.create_table(
        "user_file_blobs",
        sa.Column("file_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["user_files.id"], ondelete="CASCADE", name=op.f("fk_user_file_blobs_file_id_user_files")
        ),
        sa.PrimaryKeyConstraint("file_id", "seq", name=op.f("pk_user_file_blobs")),
        sa.CheckConstraint(f"octet_length(data) BETWEEN 1 AND {FILE_BLOB_BYTES}", name=op.f("ck_user_file_blobs_data")),
    )

    op.create_table(
        "file_chunks",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("file_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("embedding", Vector(DIMENSIONS), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["user_files.id"], ondelete="CASCADE", name=op.f("fk_file_chunks_file_id_user_files")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_chunks")),
        sa.UniqueConstraint("file_id", "ordinal", name=op.f("uq_file_chunks_file_id_ordinal")),
    )

    op.create_table(
        "message_attachments",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("message_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="CASCADE", name=op.f("fk_message_attachments_message_id_messages")
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["user_files.id"], ondelete="SET NULL", name=op.f("fk_message_attachments_file_id_user_files")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_attachments")),
        sa.UniqueConstraint("message_id", "position", name=op.f("uq_message_attachments_message_id_position")),
    )
    op.create_index("ix_message_attachments_file_id", "message_attachments", ["file_id"])


def downgrade() -> None:
    op.drop_table("message_attachments")
    op.drop_table("file_chunks")
    op.drop_table("user_file_blobs")
    op.drop_table("user_files")

"""Knowledge base for RAG: sources, documents and chunks with pgvector embeddings.

Revision ID: 0002_knowledge_base
Revises: 0001_initial
Create Date: 2026-09-23

Embeddings are vector(1536) (OpenAI text-embedding-3-small). Changing the model or
dimension later needs a new migration and a re-ingest; nothing here re-embeds data.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

revision = "0002_knowledge_base"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

NOW = sa.text("clock_timestamp()")
UUID_PK = sa.text("gen_random_uuid()")
EMPTY_JSON = sa.text("'{}'::jsonb")
DIMENSIONS = 1536


def _id():
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=UUID_PK)


def _ts(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=NOW)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_sources",
        _id(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("owner_user_id", pg.UUID(as_uuid=True)),
        sa.Column("metadata", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], ondelete="CASCADE", name="fk_knowledge_sources_owner_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_sources"),
        sa.UniqueConstraint("name", name="uq_knowledge_sources_name"),
    )
    op.create_index("ix_knowledge_sources_owner_user_id", "knowledge_sources", ["owner_user_id"])

    op.create_table(
        "documents",
        _id(),
        sa.Column("source_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("uri", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("ingest_signature", sa.String(64), nullable=False),
        sa.Column("metadata", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.id"], ondelete="CASCADE", name="fk_documents_source_id_knowledge_sources"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("source_id", "uri", name="uq_documents_source_id_uri"),
    )

    op.create_table(
        "document_chunks",
        _id(),
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
        sa.Column("embedding", Vector(DIMENSIONS), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE", name="fk_document_chunks_document_id_documents"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["knowledge_sources.id"],
            ondelete="CASCADE",
            name="fk_document_chunks_source_id_knowledge_sources",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_document_chunks_document_id_ordinal"),
    )
    op.create_index("ix_document_chunks_source_model", "document_chunks", ["source_id", "embedding_model"])
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_document_chunks_metadata_gin",
        "document_chunks",
        ["metadata"],
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("knowledge_sources")

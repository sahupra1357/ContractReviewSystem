"""knowledge & index: pgvector, chunks, embedding cache, graph-lite

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-06
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("section_id", sa.String(50), nullable=False),
        sa.Column("part", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_sha256", sa.String(64), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_chunk_sha256", "chunks", ["chunk_sha256"])
    # sparse half of hybrid retrieval: generated tsvector + GIN
    op.execute(
        "ALTER TABLE chunks ADD COLUMN text_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
    )
    op.execute("CREATE INDEX ix_chunks_text_tsv ON chunks USING GIN (text_tsv)")

    op.create_table(
        "embedding_cache",
        sa.Column("chunk_sha256", sa.String(64), primary_key=True),
        sa.Column("model", sa.String(100), primary_key=True),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "entities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("ref", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=True),
        sa.Column("master_entity_id", sa.String(32), nullable=True),
        sa.Column("section_id", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_entities_document_id", "entities", ["document_id"])
    op.create_index("ix_entities_master_entity_id", "entities", ["master_entity_id"])

    op.create_table(
        "relationships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("from_entity_id", sa.String(32), nullable=False),
        sa.Column("rel_type", sa.String(50), nullable=False),
        sa.Column("to_entity_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_relationships_document_id", "relationships", ["document_id"])


def downgrade() -> None:
    op.drop_table("relationships")
    op.drop_table("entities")
    op.drop_table("embedding_cache")
    op.drop_table("chunks")

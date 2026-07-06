"""documents registry + jobs queue (design doc §5.1)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_ref", sa.String(1000), nullable=True),
        sa.Column("filename", sa.String(1000), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("urgency", sa.JSON(), nullable=True),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("raw_key", sa.String(1200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_documents_content_sha256", "documents", ["content_sha256"], unique=True
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_document_id", "jobs", ["document_id"])
    op.create_index("ix_jobs_state", "jobs", ["state"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("documents")

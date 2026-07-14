"""Extract holds: OCR confidence gate (design doc §3.2, §5.2)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extract_holds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("attempts", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_extract_holds_document_id", "extract_holds", ["document_id"])
    op.create_index("ix_extract_holds_status", "extract_holds", ["status"])


def downgrade() -> None:
    op.drop_table("extract_holds")

"""analyses table (design §5.1)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("family", sa.String(50), nullable=True),
        sa.Column("family_score", sa.Float(), nullable=True),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("key_terms", sa.JSON(), nullable=True),
        sa.Column("suggested_decision", sa.String(30), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("dropped_uncited", sa.Integer(), nullable=False),
        sa.Column("model_strong", sa.String(100), nullable=False),
        sa.Column("model_fast", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analyses_document_id", "analyses", ["document_id"], unique=True)


def downgrade() -> None:
    op.drop_table("analyses")

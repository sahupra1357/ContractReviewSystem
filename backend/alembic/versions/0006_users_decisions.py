"""users (RBAC) + decisions (design §5.1/§5.2)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("reviewer_id", sa.String(32), nullable=False),
        sa.Column("reviewer_username", sa.String(100), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decisions_document_id", "decisions", ["document_id"])


def downgrade() -> None:
    op.drop_table("decisions")
    op.drop_table("users")

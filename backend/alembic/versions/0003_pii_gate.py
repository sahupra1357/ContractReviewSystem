"""PII gate: master table, entity map, holds (design doc §3.3, §5.2)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pii_known_entities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("value", sa.String(500), nullable=False, unique=True),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "pii_entity_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("placeholder", sa.String(50), nullable=False),
        sa.Column("entity_value", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("layer", sa.String(20), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pii_entity_map_document_id", "pii_entity_map", ["document_id"])
    op.create_table(
        "pii_holds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("flag_type", sa.String(50), nullable=False),
        sa.Column("span_text", sa.String(500), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("detector", sa.String(50), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pii_holds_document_id", "pii_holds", ["document_id"])
    op.create_index("ix_pii_holds_status", "pii_holds", ["status"])


def downgrade() -> None:
    op.drop_table("pii_holds")
    op.drop_table("pii_entity_map")
    op.drop_table("pii_known_entities")

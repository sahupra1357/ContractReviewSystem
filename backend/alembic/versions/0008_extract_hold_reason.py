"""Extract-hold reason: low_confidence vs oversized (design doc §3.2, §5.2)

Distinguishes the OCR confidence hold from the large-document oversized hold
(page count > CRS_EXTRACT_MAX_PAGES). Existing rows are confidence holds.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extract_holds",
        sa.Column(
            "reason",
            sa.String(30),
            nullable=False,
            server_default="low_confidence",
        ),
    )


def downgrade() -> None:
    op.drop_column("extract_holds", "reason")

"""audit_events — append-only SOX-aware audit trail

Revision ID: 0001
Revises:
Create Date: 2026-07-06

Append-only is enforced at the database level, not by application
convention: a trigger rejects UPDATE and DELETE for every role, including
the table owner. This is invariant #3 of the design document (§2, §5.2).
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "actor_type",
            sa.Enum("human", "system", name="actor_type"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("object_type", sa.String(255), nullable=False),
        sa.Column("object_id", sa.String(255), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_object", "audit_events", ["object_type", "object_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])

    op.execute(
        """
        CREATE FUNCTION audit_events_block_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation();
        """
    )


def downgrade() -> None:
    # Deliberately not implemented: destroying the audit trail is never a
    # supported operation (SOX-aware invariant).
    raise NotImplementedError("audit_events cannot be downgraded/dropped")

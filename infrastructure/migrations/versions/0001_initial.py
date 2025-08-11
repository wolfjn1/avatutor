from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # expand: create tables
    op.create_table(
        "feature_flags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("rollout_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("props", sa.JSON, nullable=False),
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("decision_key", sa.String(255), nullable=False),
        sa.Column("issued_to", sa.String(255), nullable=False),
        sa.Column("jwt", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "dlq",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Optional: JSONB GIN index for Postgres. Skip on errors to keep migration compatible across envs.
    try:
        op.execute("CREATE INDEX IF NOT EXISTS idx_events_props ON events USING GIN ((props)::jsonb)")
    except Exception:
        pass


def downgrade() -> None:
    # contract: drop tables
    op.drop_table("dlq")
    op.drop_table("decisions")
    op.drop_table("approvals")
    op.drop_table("events")
    op.drop_table("feature_flags")



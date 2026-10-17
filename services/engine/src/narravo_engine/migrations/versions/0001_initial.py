"""Immutable snapshots and revisions; mutable branch heads and task checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("origin_type", sa.String, nullable=False),
        sa.Column("source_asset_id", sa.String),
        sa.Column("source_hash", sa.String),
        sa.Column("import_status", sa.String, nullable=False),
        sa.Column("updated_at", sa.String, nullable=False),
    )
    op.create_table(
        "revisions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("source", sa.String, nullable=False),
    )
    op.create_table(
        "planning",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("book_id", sa.String, sa.ForeignKey("books.id"), nullable=False),
        sa.Column("parent_id", sa.String, sa.ForeignKey("snapshots.id")),
        sa.Column("planning_id", sa.String, sa.ForeignKey("planning.id"), nullable=False),
        sa.Column("chapters", sa.JSON, nullable=False),
    )
    op.create_table(
        "branches",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("book_id", sa.String, sa.ForeignKey("books.id"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("parent_id", sa.String, sa.ForeignKey("branches.id")),
        sa.Column("head", sa.String, sa.ForeignKey("snapshots.id"), nullable=False),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_table(
        "generations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("generation_id", sa.String, sa.ForeignKey("generations.id"), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_table(
        "imports",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for name in [
        "imports",
        "decisions",
        "generations",
        "tasks",
        "branches",
        "snapshots",
        "planning",
        "revisions",
        "books",
    ]:
        op.drop_table(name)

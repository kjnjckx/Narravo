"""Independent roleplay roots, immutable revisions and recoverable turn checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rp_characters",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("head", sa.String, nullable=False),
        sa.Column("archived", sa.Boolean, nullable=False),
    )
    op.create_table(
        "rp_personas",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("character_id", sa.String, sa.ForeignKey("rp_characters.id"), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_table(
        "rp_conversations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("head", sa.String, nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("epoch", sa.Integer, nullable=False),
    )
    for name in ["rp_snapshots", "rp_messages", "rp_turns", "rp_memories"]:
        op.create_table(
            name,
            sa.Column("id", sa.String, primary_key=True),
            sa.Column(
                "conversation_id", sa.String, sa.ForeignKey("rp_conversations.id"), nullable=False
            ),
            sa.Column("payload", sa.JSON, nullable=False),
        )
        op.create_index(f"ix_{name}_conversation", name, ["conversation_id"])
    op.create_table(
        "rp_operations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "conversation_id", sa.String, sa.ForeignKey("rp_conversations.id"), nullable=False
        ),
        sa.Column("payload", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for name in [
        "rp_operations",
        "rp_memories",
        "rp_turns",
        "rp_messages",
        "rp_snapshots",
        "rp_conversations",
        "rp_personas",
        "rp_characters",
    ]:
        op.drop_table(name)

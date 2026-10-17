"""Provider metadata, network consent and verified audio assets. No credentials."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ["providers", "preferences", "audio_assets"]:
        op.create_table(
            name,
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("payload", sa.JSON, nullable=False),
        )


def downgrade() -> None:
    for name in ["audio_assets", "preferences", "providers"]:
        op.drop_table(name)

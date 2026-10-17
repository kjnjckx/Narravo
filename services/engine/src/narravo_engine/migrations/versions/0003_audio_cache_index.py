"""Persist a unique audio cache key and use indexed lookups."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audio_assets", sa.Column("cache_key", sa.String(), nullable=True))
    op.execute("UPDATE audio_assets SET cache_key = json_extract(payload, '$.cache_key')")
    op.create_index("audio_cache_key_unique", "audio_assets", ["cache_key"], unique=True)


def downgrade() -> None:
    op.drop_index("audio_cache_key_unique", table_name="audio_assets")
    op.drop_column("audio_assets", "cache_key")

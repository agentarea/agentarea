"""model_specs: the price of a generated image and of a second of generated video

A call on the platform's credentials is held before it runs, and these are what an
image or video call is held by. Null on a model nobody holds calls for.

video_generation_jobs.funding keeps a job's hold from submission to the check that
finds it done; billing keeps the line that check reported, for its retries.

Revision ID: 20261014_2000_media_prices
Revises: 20261014_1800_cache_write_price
Create Date: 2026-10-14 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261014_2000_media_prices"
down_revision: str | None = "20261014_1800_cache_write_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_specs", sa.Column("output_cost_per_image", sa.Numeric(20, 12), nullable=True)
    )
    op.add_column(
        "model_specs",
        sa.Column("output_cost_per_video_per_second", sa.Numeric(20, 12), nullable=True),
    )
    op.add_column("video_generation_jobs", sa.Column("funding", JSONB(), nullable=True))
    op.add_column("video_generation_jobs", sa.Column("billing", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("video_generation_jobs", "billing")
    op.drop_column("video_generation_jobs", "funding")
    op.drop_column("model_specs", "output_cost_per_video_per_second")
    op.drop_column("model_specs", "output_cost_per_image")

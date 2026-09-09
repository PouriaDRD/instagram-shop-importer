"""add instagram availability tracking

Revision ID: 6fd43a9c2e71
Revises: cbc429210ca8
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa


revision = "6fd43a9c2e71"
down_revision = "cbc429210ca8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("crawled_media", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_available",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_crawled_media_is_available",
            ["is_available"],
            unique=False,
        )
        batch_op.create_index(
            "ix_crawled_media_last_seen_at",
            ["last_seen_at"],
            unique=False,
        )

    with op.batch_alter_table("crawled_assets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_available",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_crawled_assets_is_available",
            ["is_available"],
            unique=False,
        )
        batch_op.create_index(
            "ix_crawled_assets_last_seen_at",
            ["last_seen_at"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("crawled_assets", schema=None) as batch_op:
        batch_op.drop_index(
            "ix_crawled_assets_last_seen_at"
        )
        batch_op.drop_index(
            "ix_crawled_assets_is_available"
        )
        batch_op.drop_column("last_seen_at")
        batch_op.drop_column("is_available")

    with op.batch_alter_table("crawled_media", schema=None) as batch_op:
        batch_op.drop_index(
            "ix_crawled_media_last_seen_at"
        )
        batch_op.drop_index(
            "ix_crawled_media_is_available"
        )
        batch_op.drop_column("last_seen_at")
        batch_op.drop_column("is_available")

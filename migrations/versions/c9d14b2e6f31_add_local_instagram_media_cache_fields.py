"""add local instagram media cache fields

Revision ID: c9d14b2e6f31
Revises: 7b51f8f31b0a
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa


revision = "c9d14b2e6f31"
down_revision = "7b51f8f31b0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "crawled_assets"
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "local_cache_path",
                sa.Text(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "local_cache_status",
                sa.String(length=32),
                nullable=False,
                server_default="missing",
            )
        )
        batch_op.add_column(
            sa.Column(
                "local_cached_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "local_content_type",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "local_file_size",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "local_sha256",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "local_cache_error",
                sa.Text(),
                nullable=True,
            )
        )

    with op.batch_alter_table(
        "crawled_assets"
    ) as batch_op:
        batch_op.alter_column(
            "local_cache_status",
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "crawled_assets"
    ) as batch_op:
        batch_op.drop_column(
            "local_cache_error"
        )
        batch_op.drop_column(
            "local_sha256"
        )
        batch_op.drop_column(
            "local_file_size"
        )
        batch_op.drop_column(
            "local_content_type"
        )
        batch_op.drop_column(
            "local_cached_at"
        )
        batch_op.drop_column(
            "local_cache_status"
        )
        batch_op.drop_column(
            "local_cache_path"
        )

"""rename local media cache fields to persistent storage fields

Revision ID: d2f4a8e71c90
Revises: c9d14b2e6f31
Create Date: 2026-09-09
"""

from alembic import op

revision = "d2f4a8e71c90"
down_revision = "c9d14b2e6f31"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("crawled_assets") as batch_op:
        batch_op.alter_column("local_cache_path", new_column_name="local_file_path")
        batch_op.alter_column("local_cache_status", new_column_name="local_file_status")
        batch_op.alter_column("local_cached_at", new_column_name="local_saved_at")
        batch_op.alter_column("local_cache_error", new_column_name="local_file_error")

def downgrade() -> None:
    with op.batch_alter_table("crawled_assets") as batch_op:
        batch_op.alter_column("local_file_path", new_column_name="local_cache_path")
        batch_op.alter_column("local_file_status", new_column_name="local_cache_status")
        batch_op.alter_column("local_saved_at", new_column_name="local_cached_at")
        batch_op.alter_column("local_file_error", new_column_name="local_cache_error")

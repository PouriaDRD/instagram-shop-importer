"""remote workspace coordination fields

Revision ID: 7b51f8f31b0a
Revises: 38b4db7f30c2
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa


revision = "7b51f8f31b0a"
down_revision = "38b4db7f30c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "import_drafts",
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "remote_workspace_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "remote_revision",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "remote_is_editable",
                sa.Boolean(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "remote_lock_token",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "remote_lock_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_import_drafts_remote_workspace_id",
            [
                "remote_workspace_id",
            ],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "import_drafts",
    ) as batch_op:
        batch_op.drop_index(
            "ix_import_drafts_remote_workspace_id"
        )
        batch_op.drop_column(
            "remote_lock_expires_at"
        )
        batch_op.drop_column(
            "remote_lock_token"
        )
        batch_op.drop_column(
            "remote_is_editable"
        )
        batch_op.drop_column(
            "remote_revision"
        )
        batch_op.drop_column(
            "remote_workspace_id"
        )

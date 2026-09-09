"""split workspace sync and workflow state

Revision ID: 38b4db7f30c2
Revises: 6fd43a9c2e71
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa


revision = "38b4db7f30c2"
down_revision = "6fd43a9c2e71"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        "import_drafts",
        schema=None,
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "local_sync_status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(
            sa.Column(
                "remote_workflow_status",
                sa.String(length=32),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(
            sa.Column(
                "last_synced_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "last_sync_error",
                sa.Text(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "remote_status_updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_import_drafts_local_sync_status",
            ["local_sync_status"],
            unique=False,
        )
        batch_op.create_index(
            "ix_import_drafts_remote_workflow_status",
            ["remote_workflow_status"],
            unique=False,
        )

    # Preserve meaning of any legacy rows that were previously marked sent.
    op.execute(
        """
        UPDATE import_drafts
        SET local_sync_status = 'synced'
        WHERE status = 'sent'
        """
    )


def downgrade():
    # Best-effort compatibility when rolling back.
    op.execute(
        """
        UPDATE import_drafts
        SET status = 'sent'
        WHERE local_sync_status = 'synced'
        """
    )

    with op.batch_alter_table(
        "import_drafts",
        schema=None,
    ) as batch_op:
        batch_op.drop_index(
            "ix_import_drafts_remote_workflow_status"
        )
        batch_op.drop_index(
            "ix_import_drafts_local_sync_status"
        )
        batch_op.drop_column(
            "remote_status_updated_at"
        )
        batch_op.drop_column(
            "last_sync_error"
        )
        batch_op.drop_column(
            "last_synced_at"
        )
        batch_op.drop_column(
            "remote_workflow_status"
        )
        batch_op.drop_column(
            "local_sync_status"
        )

"""Product metadata for Selora import from local editor.

Revision ID: f5c100000001
Revises: d2f4a8e71c90
"""
from alembic import op
import sqlalchemy as sa
revision = "f5c100000001"
down_revision = "d2f4a8e71c90"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("import_draft_product_data") as batch:
        batch.add_column(sa.Column("benefits", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("slug", sa.String(length=255), nullable=False, server_default=""))
        batch.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("subcategory_id", sa.Integer(), nullable=True))

def downgrade():
    with op.batch_alter_table("import_draft_product_data") as batch:
        batch.drop_column("subcategory_id")
        batch.drop_column("category_id")
        batch.drop_column("slug")
        batch.drop_column("benefits")

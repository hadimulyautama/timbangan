"""Alias sopir yang dikonfirmasi pemilik, tanpa mengubah tiket lama.

Revision ID: 0046_sopir_alias
Revises: 0045_sopir_unik
"""
from alembic import op
import sqlalchemy as sa

revision = "0046_sopir_alias"
down_revision = "0045_sopir_unik"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "timbangan_sopir_alias",
        sa.Column("kunci_nama", sa.String(200), primary_key=True),
        sa.Column("nama", sa.String(100), nullable=False),
        sa.Column("sopir_id", sa.Integer(), sa.ForeignKey("timbangan_sopir.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("timbangan_sopir_alias")

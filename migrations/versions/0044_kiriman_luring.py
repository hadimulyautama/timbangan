"""Tanda terima atomik untuk pengiriman ulang formulir timbang.

Revision ID: 0044_kiriman_luring
Revises: 0043_jasa_beras_masuk
"""
from alembic import op
import sqlalchemy as sa

revision = "0044_kiriman_luring"
down_revision = "0043_jasa_beras_masuk"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "timbangan_kiriman",
        sa.Column("kunci", sa.String(36), primary_key=True),
        sa.Column("akun_id", sa.Integer(), sa.ForeignKey("timbangan_akun.id"), nullable=False),
        sa.Column("jalur", sa.String(255), nullable=False),
        sa.Column("sidik", sa.String(64), nullable=False),
        sa.Column("jawaban", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("timbangan_kiriman")

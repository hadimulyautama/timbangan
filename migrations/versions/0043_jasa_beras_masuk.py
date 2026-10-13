"""Buka jenis barang masuk Beras untuk transaksi Jasa.

Revision ID: 0043_jasa_beras_masuk
Revises: 0042_muatan_produk_bersama
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0043_jasa_beras_masuk"
down_revision: Union[str, None] = "0042_muatan_produk_bersama"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE timbangan_jenis SET boleh_jasa = true "
        "WHERE kode = 'BERAS_MASUK'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE timbangan_jenis SET boleh_jasa = false "
        "WHERE kode = 'BERAS_MASUK'"
    )

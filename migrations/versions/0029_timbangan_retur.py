"""Retur: arah barang yang lawan transaksinya menyilang.

Barang yang dikembalikan pelanggan bergerak MASUK tetapi lawannya pelanggan;
barang yang kita tolak dan kirim balik bergerak KELUAR tetapi lawannya
supplier. Sebelum ini keduanya tidak punya tempat: arah MASUK memaksa memilih
dari daftar supplier, dan arah KELUAR memaksa memilih dari daftar pelanggan,
sehingga satu-satunya cara mencatat retur adalah mengetiknya sebagai nama
bebas — dan rekap per pihak jadi tidak menemukannya.

Migrasi ini hanya MELEBARKAN kolom `arah`. Nilai "RETUR_KELUAR" panjangnya 12
karakter dan tidak muat di String(10); di SQLite hal itu lolos tanpa keluhan,
di Postgres ia menolak menyimpan. Baris aturannya sendiri tidak ditulis di
sini — `service.pastikan_jenis_awal()` menyemainya saat aplikasi menyala, dan
baris yang sudah ada tidak pernah ditimpa.

Revision ID: 0029_timbangan_retur
Revises: 0028_timbangan_partai
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_timbangan_retur"
down_revision: Union[str, None] = "0028_timbangan_partai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "timbangan_transaksi", "arah",
        existing_type=sa.String(length=10), type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.alter_column(
        "timbangan_jenis", "arah",
        existing_type=sa.String(length=10), type_=sa.String(length=16),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Menyempitkan kembali akan memotong nilai RETUR_*; transaksi retur yang
    # sudah tercatat harus dipindahkan lebih dulu bila langkah ini dipakai.
    op.alter_column(
        "timbangan_jenis", "arah",
        existing_type=sa.String(length=16), type_=sa.String(length=10),
        existing_nullable=False,
    )
    op.alter_column(
        "timbangan_transaksi", "arah",
        existing_type=sa.String(length=16), type_=sa.String(length=10),
        existing_nullable=False,
    )

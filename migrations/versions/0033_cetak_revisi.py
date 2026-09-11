"""Riwayat cetak menyimpan nomor revisi tiket saat kertasnya keluar.

Temuan QA T-11, 11 September 2026.

Cetak ulang sesudah koreksi memuat angka yang berbeda dari cetakan
sebelumnya, dan tak ada apa pun yang membedakan kedua lembar itu. Sengketa
dibuka berbulan-bulan kemudian; yang ditanya adalah "lembar mana yang
dipegang pengirim", dan sampai kolom ini ada, pertanyaan itu tak punya
jawaban.

Baris lama diisi 0 — bukan tebakan, melainkan pernyataan yang benar: sebelum
kolom ini ada, tak ada satu pun cetakan yang nomor revisinya diketahui, dan
tiket yang belum pernah dikoreksi memang bernomor revisi 0.

Kolom yang DIBACA PRODUKSI tidak disentuh: produksi membaca
`timbangan_transaksi`, bukan `timbangan_cetak`.

Revision ID: 0033_cetak_revisi
Revises: 0032_partai_kunci_baris
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_cetak_revisi"
down_revision: Union[str, None] = "0032_partai_kunci_baris"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "timbangan_cetak",
        sa.Column("revisi", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("timbangan_cetak", "revisi")

"""Partai kecil: banyak penimbangan, tetap satu kode timbang.

Petani dan pedagang kecil menjual sedikit-sedikit, dan barangnya ditimbang
satu per satu. Sebelum ini alurnya tidak punya bentuk: satu transaksi hanya
mengenal timbang bermuatan dan timbang kosong. Memaksanya jadi banyak tiket
akan memecah satu penjualan menjadi banyak nota, dan rekap per pihak jadi
menyesatkan.

Tabel ini menyimpan tiap kali barang naik timbangan; jumlahnya disalin ke
`timbangan_transaksi.timbang1_kg` supaya laporan, bukti cetak, dan jembatan ke
modul produksi tetap membaca satu angka seperti transaksi lain.

Revision ID: 0028_timbangan_partai
Revises: 0027_pelanggan_transaksi
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_timbangan_partai"
down_revision: Union[str, None] = "0027_pelanggan_transaksi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timbangan_penimbangan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaksi_id", sa.Integer(), nullable=False),
        sa.Column("urutan", sa.Integer(), server_default="1", nullable=False),
        sa.Column("berat_kg", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("waktu", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waktu_sistem", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("petugas_id", sa.Integer(), nullable=True),
        sa.Column("catatan", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["transaksi_id"], ["timbangan_transaksi.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["petugas_id"], ["timbangan_akun.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_timbangan_penimbangan_transaksi_id",
                    "timbangan_penimbangan", ["transaksi_id"])


def downgrade() -> None:
    op.drop_index("ix_timbangan_penimbangan_transaksi_id",
                  table_name="timbangan_penimbangan")
    op.drop_table("timbangan_penimbangan")

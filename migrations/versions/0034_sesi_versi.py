"""Akun pos timbang punya versi sesi, supaya token yang beredar bisa dicabut.

Temuan QA T-19, 11 September 2026.

Token sesi berlaku 180 hari, bertanda tangan HMAC, dan tidak tercatat di mana
pun. Akibatnya ia tak bisa dihentikan oleh tindakan apa pun: sesudah petugas
mengganti sandinya lalu menekan Keluar, cookie lama di perangkat lain tetap
dijawab 200 — selama enam bulan.

Kolom ini ikut di dalam token dan naik saat petugas keluar, mengganti sandi,
atau perannya diubah. Nilai awal 1 untuk semua baris, dan token lama yang
belum membawa nomor versi dianggap versi 1 juga, jadi deploy ini tidak
memutus siapa pun yang sedang bertugas.

Kolom yang DIBACA PRODUKSI tidak disentuh: produksi membaca
`timbangan_transaksi`, bukan `timbangan_akun`.

Revision ID: 0034_sesi_versi
Revises: 0033_cetak_revisi
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034_sesi_versi"
down_revision: Union[str, None] = "0033_cetak_revisi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "timbangan_akun",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("timbangan_akun", "token_version")

"""`timbangan_transaksi.jasa` — penanda yang TERSIMPAN, bukan diturunkan.

Cacat lapangan 2 Oktober 2026 (laporan pemilik langsung dari layar Stok): PK
yang dititipkan pelanggan terbaca sebagai pembelian pabrik, dan pemasok PALSU
bernama pelanggan ikut tercatat — persis yang spek larang keras.

Akarnya: SATU-SATUNYA penanda "tiket ini jasa" yang dibaca produksi
(`timbang_link.adalah_jasa`) adalah `pelanggan_id IS NOT NULL`. Tetapi borang
jasa SENGAJA punya pintu ketik-bebas untuk pelanggan baru yang belum sampai ke
cermin Kledo — dan saat nama diketik bebas, `pelanggan_id` yang terkirim tetap
kosong (`_pasang_pihak(trx, arah, pihak_id=None, jasa=True)` mengosongkan
KEDUA kolom FK). Baris tiket "jasa-pelanggan-baru" dan
"pembelian-pemasok-baru" jadi IDENTIK bentuknya — tak ada yang membedakan.

    SEBELUM: jasa = (pelanggan_id is not None)      ⚠ salah untuk pelanggan baru
    SESUDAH: jasa = kolom ini, diisi `simpan_timbang_pertama` dari `data.jasa`
             — fakta yang BENAR-BENAR diketahui petugas saat ia menekan
             "Barang masuk jasa", lepas dari apakah pelanggannya sudah
             terdaftar atau belum.

Idempoten seperti migrasi lain di titik sambungnya — basis data uji produksi
membangun dari rantai produksi saja, dan kolom ini dibaca lintas rantai lewat
SQL mentah di `timbang_link.py`.

Revision ID: 0041_tanda_jasa
Revises: 0040_jasa_tiga_komoditas
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_tanda_jasa"
down_revision: Union[str, None] = "0040_jasa_tiga_komoditas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    kolom = {c["name"] for c in inspector.get_columns("timbangan_transaksi")}
    if "jasa" not in kolom:
        op.add_column(
            "timbangan_transaksi",
            sa.Column("jasa", sa.Boolean(), nullable=False,
                     server_default=sa.false()))
    # Baris LAMA: `jasa = (pelanggan_id IS NOT NULL)` — satu-satunya kebenaran
    # yang tersedia untuk riwayat sebelum migrasi ini ada. Tiket jasa lama
    # yang pelanggannya diketik bebas TETAP salah tanda (tak ada cara menebak
    # dari data yang sudah terlanjur identik dengan pembelian biasa) — migrasi
    # ini menghentikan kerusakan BARU, bukan membetulkan yang sudah terjadi.
    op.execute(
        "UPDATE timbangan_transaksi SET jasa = true WHERE pelanggan_id IS NOT NULL"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    kolom = {c["name"] for c in inspector.get_columns("timbangan_transaksi")}
    if "jasa" in kolom:
        op.drop_column("timbangan_transaksi", "jasa")

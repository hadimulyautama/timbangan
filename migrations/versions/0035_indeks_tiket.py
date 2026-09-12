"""Indeks pada kolom yang selalu dipakai mencari isi sebuah tiket.

Temuan QA T-22, 11 September 2026.

`timbangan_muatan` dan `timbangan_foto` selalu ditanya "semua baris milik
tiket nomor sekian", dan tak satu pun punya indeks untuk itu. Selama tiketnya
ratusan, Postgres membaca seluruh tabel dan tak ada yang merasakan apa pun;
biayanya naik diam-diam seiring tabelnya tumbuh — dan `timbangan_foto`
tumbuhnya paling cepat, karena isinya BLOB.

Isi foto sendiri kini `deferred` di model, jadi daftar tiket tak lagi menarik
berpuluh megabyte BLOB hanya untuk menampilkan nomor polisi dan berat.

Kolom yang DIBACA PRODUKSI tidak disentuh.

Revision ID: 0035_indeks_tiket
Revises: 0034_sesi_versi
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0035_indeks_tiket"
down_revision: Union[str, None] = "0034_sesi_versi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEKS = [
    ("ix_timbangan_muatan_transaksi", "timbangan_muatan", "transaksi_id"),
    ("ix_timbangan_foto_transaksi", "timbangan_foto", "transaksi_id"),
]


def upgrade() -> None:
    for nama, tabel, kolom in INDEKS:
        op.execute(f"CREATE INDEX IF NOT EXISTS {nama} ON {tabel} ({kolom})")


def downgrade() -> None:
    for nama, _t, _k in INDEKS:
        op.execute(f"DROP INDEX IF EXISTS {nama}")

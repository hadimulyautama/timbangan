"""Buang dua indeks yang menduplikasi constraint unik di kolom yang sama.

Temuan QA X-19, 11 September 2026.

`timbangan_kendaraan.nomor_polisi` dan `timbangan_transaksi.kode` masing-masing
punya constraint unik DAN indeks biasa pada kolom yang persis sama. Constraint
unik sudah berindeks, jadi yang kedua murni duplikat: memakan ruang, dan
melambatkan setiap tulis ke dua tabel yang paling sering ditulis di pos timbang
— tiap tiket baru menulis keduanya.

Ia juga membuat `alembic check` mengusulkan menukar keduanya tiap kali
dijalankan, sehingga selisih model ↔ migrasi yang SUNGGUHAN tenggelam di
antara usulan yang tak berarti apa-apa.

Kolom yang DIBACA PRODUKSI tidak disentuh: yang dibuang indeksnya, bukan
keunikannya. `timbangan_transaksi.kode` tetap unik.

Revision ID: 0036_indeks_duplikat
Revises: 0035_indeks_tiket
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0036_indeks_duplikat"
down_revision: Union[str, None] = "0035_indeks_tiket"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEKS = [
    ("ix_timbangan_kendaraan_nomor_polisi", "timbangan_kendaraan", "nomor_polisi"),
    ("ix_timbangan_transaksi_kode", "timbangan_transaksi", "kode"),
]


def upgrade() -> None:
    for nama, _t, _k in INDEKS:
        op.execute(f"DROP INDEX IF EXISTS {nama}")


def downgrade() -> None:
    for nama, tabel, kolom in INDEKS:
        op.execute(f"CREATE INDEX IF NOT EXISTS {nama} ON {tabel} ({kolom})")

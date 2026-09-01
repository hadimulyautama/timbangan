"""Kolom pelanggan pada catatan timbang.

Sampai sekarang lawan transaksi disimpan di `supplier_id` untuk KEDUA arah,
sehingga pengiriman menunjuk baris supplier — daftar orang yang menjual kepada
kita, bukan yang membeli dari kita.

Dua kolom, bukan satu, karena keduanya menunjuk tabel berbeda: `suppliers`
untuk barang masuk, `pelanggan` untuk pengiriman. Satu kolom polimorfik akan
melepas integritas referensialnya, dan itu justru jaminan yang paling ingin
dipertahankan pada catatan timbang.

Tabel `pelanggan` dimiliki sistem penggilingan (migrasi 0029 di sana) dan
disinkron dari kontak Kledo bertipe 3. Repo ini hanya membacanya — lihat
`app/models.py`.

Revision ID: 0027_pelanggan_transaksi
Revises: 0026_timbangan_hapus_pengawas
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_pelanggan_transaksi"
down_revision: Union[str, None] = "0026_timbangan_hapus_pengawas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "timbangan_transaksi", sa.Column("pelanggan_id", sa.Integer())
    )
    # SQLite tidak mendukung ALTER constraint sama sekali, dan uji kesepadanan
    # skema memutar ulang migrasi ini di atasnya. Produksi memakai Postgres
    # dan tetap mendapat constraint-nya — integritas catatan timbang terlalu
    # berharga untuk dilepas hanya demi menyenangkan dialek uji.
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_timbangan_transaksi_pelanggan", "timbangan_transaksi",
            "pelanggan", ["pelanggan_id"], ["id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_timbangan_transaksi_pelanggan", "timbangan_transaksi",
            type_="foreignkey",
        )
    op.drop_column("timbangan_transaksi", "pelanggan_id")

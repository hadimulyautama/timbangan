"""Tautkan rincian tiket timbang ke master produk dan kemasan bersama.

Setiap baris muatan dapat menunjuk kualitas, merek produk, jenis karung, dan
ukuran yang sama dengan yang dipakai aplikasi Operasional. Kolom nullable
menjaga tiket lama serta barang curah tetap valid. Master acuannya dimiliki
aplikasi Operasional/core; migrasi Timbangan hanya menambah FK.

Revision ID: 0042_muatan_produk_bersama
Revises: 0041_tanda_jasa
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_muatan_produk_bersama"
down_revision: Union[str, None] = "0041_tanda_jasa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


KOLOM = {
    "kualitas_id": sa.Integer(),
    "merek_produk_id": sa.Integer(),
    "packaging_material_id": sa.Integer(),
    "package_size_id": sa.Integer(),
}
FK = {
    "kualitas_id": ("rice_quality_standards", "id"),
    "merek_produk_id": ("brands", "id"),
    "packaging_material_id": ("packaging_materials", "id"),
    "package_size_id": ("package_sizes", "id"),
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    kolom_ada = {c["name"] for c in inspector.get_columns("timbangan_muatan")}
    for nama, tipe in KOLOM.items():
        if nama not in kolom_ada:
            op.add_column("timbangan_muatan", sa.Column(nama, tipe, nullable=True))

    fk_ada = {c["name"] for c in inspector.get_foreign_keys("timbangan_muatan")}
    for nama, (tabel, kolom) in FK.items():
        nama_fk = f"fk_timbangan_muatan_{nama}"
        if nama_fk not in fk_ada:
            op.create_foreign_key(nama_fk, "timbangan_muatan", tabel, [nama], [kolom])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    fk_ada = {c["name"] for c in inspector.get_foreign_keys("timbangan_muatan")}
    for nama in reversed(tuple(FK)):
        nama_fk = f"fk_timbangan_muatan_{nama}"
        if nama_fk in fk_ada:
            op.drop_constraint(nama_fk, "timbangan_muatan", type_="foreignkey")
    kolom_ada = {c["name"] for c in inspector.get_columns("timbangan_muatan")}
    for nama in reversed(tuple(KOLOM)):
        if nama in kolom_ada:
            op.drop_column("timbangan_muatan", nama)

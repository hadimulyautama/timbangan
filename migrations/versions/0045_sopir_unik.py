"""Daftar nama sopir unik tanpa menulis ulang tiket historis.

Revision ID: 0045_sopir_unik
Revises: 0044_kiriman_luring
"""
from unicodedata import normalize

from alembic import op
import sqlalchemy as sa

revision = "0045_sopir_unik"
down_revision = "0044_kiriman_luring"
branch_labels = None
depends_on = None


def upgrade():
    tabel = op.create_table(
        "timbangan_sopir",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nama", sa.String(100), nullable=False),
        sa.Column("kunci_nama", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kunci_nama", name="uq_timbangan_sopir_kunci_nama"),
    )
    # Ejaan pertama dipakai untuk masukan berikutnya. Tiket dan audit lama
    # tetap apa adanya, termasuk variasi ejaan yang pernah dicatat petugas.
    nama_unik = {}
    for nama in op.get_bind().execute(sa.text(
        "SELECT nama_sopir FROM timbangan_transaksi WHERE nama_sopir IS NOT NULL ORDER BY id"
    )).scalars():
        bersih = " ".join(normalize("NFKC", nama).split())
        if bersih:
            nama_unik.setdefault(bersih.casefold(), bersih)
    if nama_unik:
        op.bulk_insert(tabel, [{"nama": n, "kunci_nama": k} for k, n in nama_unik.items()])


def downgrade():
    op.drop_table("timbangan_sopir")

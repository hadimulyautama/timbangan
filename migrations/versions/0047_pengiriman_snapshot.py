"""Cuplikan sumber kiriman gabungan, tanpa backfill tiket historis."""
from alembic import op
import sqlalchemy as sa
revision='0047_pengiriman_snapshot'
down_revision='0046_sopir_alias'
branch_labels=depends_on=None

def upgrade():
    op.add_column('timbangan_transaksi',sa.Column('pengiriman_snapshot',sa.JSON(),nullable=True))

def downgrade():
    # Jangan menghilangkan satu-satunya bukti alokasi per pelanggan/item.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM timbangan_transaksi WHERE pengiriman_snapshot IS NOT NULL AND pengiriman_snapshot::text <> 'null'")):
        raise RuntimeError('Cuplikan kiriman sudah digunakan; gunakan aplikasi kompatibel tanpa menghapus riwayat.')
    op.drop_column('timbangan_transaksi','pengiriman_snapshot')

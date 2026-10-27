"""Identitas/snapshot lintasan pilihan; tiket lama tetap tanpa pemetaan rekaan."""
from alembic import op
import sqlalchemy as sa
revision='0048_lintasan_transfer'
down_revision='0047_pengiriman_snapshot'
branch_labels=depends_on=None

def upgrade():
    op.add_column('timbangan_transaksi',sa.Column('lintasan_transfer',sa.JSON(),nullable=True))

def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM timbangan_transaksi WHERE lintasan_transfer IS NOT NULL AND lintasan_transfer::text <> 'null'")):
        raise RuntimeError('Lintasan sudah digunakan; gunakan aplikasi kompatibel tanpa menghapus snapshot.')
    op.drop_column('timbangan_transaksi','lintasan_transfer')

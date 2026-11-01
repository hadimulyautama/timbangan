"""Urutan stabil tiket aktif untuk daftar dan pemantauan bertahap."""
from alembic import op

revision='0050_indeks_urut_aktif'
down_revision='0049_pekerjaan_cetak'
branch_labels=depends_on=None

def upgrade():
    op.create_index('ix_timbangan_transaksi_aktif_urut','timbangan_transaksi',
        ['status_transaksi','tanggal','id'])

def downgrade():
    op.drop_index('ix_timbangan_transaksi_aktif_urut',table_name='timbangan_transaksi')

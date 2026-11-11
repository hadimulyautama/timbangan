"""Satu tiket timbang untuk satu perjalanan PK yang telah disetujui."""
from alembic import op
import sqlalchemy as sa
revision='0051_pengiriman_pk'
down_revision='0050_indeks_urut_aktif'
branch_labels=depends_on=None

def upgrade():
    with op.batch_alter_table('timbangan_transaksi') as batch:
        batch.add_column(sa.Column('pengiriman_pk_id',sa.Integer(),nullable=True))
        batch.add_column(sa.Column('pengiriman_pk_status',sa.String(24),nullable=True))
        batch.create_unique_constraint('uq_timbangan_pengiriman_pk',['pengiriman_pk_id'])

def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM timbangan_transaksi WHERE pengiriman_pk_id IS NOT NULL LIMIT 1')).first():
        raise RuntimeError('Tiket transfer bertahap sudah ada; rollback tidak boleh menghapus hubungan perjalanan.')
    with op.batch_alter_table('timbangan_transaksi') as batch:
        batch.drop_constraint('uq_timbangan_pengiriman_pk',type_='unique')
        batch.drop_column('pengiriman_pk_status');batch.drop_column('pengiriman_pk_id')

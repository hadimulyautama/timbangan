"""Ikat hasil cetak pada pekerjaan, pelaku, alasan, dan revisi saat dikirim."""
from alembic import op
import sqlalchemy as sa
revision = '0049_pekerjaan_cetak'
down_revision = '0048_lintasan_transfer'
branch_labels = depends_on = None

def upgrade():
    op.create_table('timbangan_pekerjaan_cetak',
        sa.Column('kunci',sa.String(64),primary_key=True),
        sa.Column('transaksi_id',sa.Integer(),sa.ForeignKey('timbangan_transaksi.id'),nullable=False),
        sa.Column('oleh_id',sa.Integer(),sa.ForeignKey('timbangan_akun.id'),nullable=False),
        sa.Column('nama_pencetak',sa.String(255),nullable=False),
        sa.Column('format',sa.String(10),nullable=False),
        sa.Column('keluaran',sa.String(10),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('sidik',sa.String(64),nullable=False),
        sa.Column('versi_tiket',sa.String(100),nullable=False),
        sa.Column('revisi',sa.Integer(),nullable=False),
        sa.Column('urutan',sa.Integer(),nullable=False),
        sa.Column('alasan',sa.Text()),sa.Column('konten',sa.LargeBinary(),nullable=False),
        sa.Column('metode',sa.String(30)),
        sa.Column('cetak_id',sa.Integer(),sa.ForeignKey('timbangan_cetak.id')),
        sa.Column('waktu',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index('ix_timbangan_pekerjaan_cetak_transaksi_id','timbangan_pekerjaan_cetak',['transaksi_id'])

def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM timbangan_pekerjaan_cetak')):
        raise RuntimeError('Pekerjaan cetak sudah terisi; pertahankan jejaknya dengan aplikasi kompatibel.')
    op.drop_table('timbangan_pekerjaan_cetak')

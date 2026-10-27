"""Alembic check dengan relasi lintas aplikasi yang sengaja tidak dipetakan ORM.

Model Timbangan menjelaskan bahwa jasa_id adalah Integer tanpa FK ORM karena
jasa dimiliki PadiFlow. Migrasi PadiFlow 0064 tetap memasang FK dan indeks di DB.
Tambahkan keduanya hanya ke metadata proses pemeriksa ini, bukan ke aplikasi
atau database, agar check memeriksa kontrak lengkap tanpa menyarankan penghapusan.
Semua selisih lain tetap membuat command.check gagal.
"""
from alembic import command
from alembic.config import Config
from sqlalchemy import Column, ForeignKeyConstraint, Index, Integer, Table, text
import app.models  # noqa: F401
from app.database import Base
from app.timbangan import models  # noqa: F401

if 'jasa' not in Base.metadata.tables:
    Table('jasa', Base.metadata, Column('id', Integer, primary_key=True))
tiket = Base.metadata.tables['timbangan_transaksi']
assert not tiket.c.jasa_id.foreign_keys
ForeignKeyConstraint([tiket.c.jasa_id], ['jasa.id'], name='timbangan_transaksi_jasa_id_fkey')
Index('ix_timbangan_transaksi_jasa', tiket.c.jasa_id,
      postgresql_where=text('jasa_id IS NOT NULL'))
command.check(Config('alembic.ini'))

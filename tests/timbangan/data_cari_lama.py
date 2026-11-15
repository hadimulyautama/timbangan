"""Data tiket arsip sintetis; tidak membuka koneksi selain fixture pemanggil."""
from datetime import timedelta
from sqlalchemy import select
from app import database
from app.timbangan.db import hari_ini
from app.timbangan.models import TimbanganTransaksi, TimbanganAkun, ROLE_PETUGAS, ROLE_ADMIN, ROLE_SUPERADMIN
from app.timbangan.security import hash_sandi
from data_riwayat import isi_riwayat


async def arsip(peran='operator'):
    ids=await isi_riwayat(database.SessionLocal,145)
    async with database.SessionLocal() as db:
        for i,t in enumerate((await db.scalars(select(TimbanganTransaksi).order_by(TimbanganTransaksi.id))).all()):
            if i<80:
                t.tanggal=hari_ini()-timedelta(days=45)
                t.kode=f'ARSIP-{i:04}'
                t.pihak_nama='Arsip Sintetis'
                t.arah='MASUK';t.jenis_kode='GABAH_BASAH';t.status_kontrol='NORMAL';t.status_tiket='SELESAI'
            if i==144:
                t.kode='DUATAHUN-SINTETIS';t.tanggal=hari_ini()-timedelta(days=500)
        role={'operator':ROLE_PETUGAS,'admin':ROLE_ADMIN,'superadmin':ROLE_SUPERADMIN}[peran]
        db.add(TimbanganAkun(username='fixture-'+peran,nama='Fixture '+peran,role=role,
            password_hash=hash_sandi('rahasia123'),perangkat_kode='P1'))
        await db.commit()
    return ids

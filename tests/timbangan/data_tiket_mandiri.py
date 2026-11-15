"""Tiket Timbang Bebas sintetis; tidak membuat transfer atau pekerjaan PadiFlow."""
from datetime import timedelta
from app import database
from app.timbangan.db import sekarang
from app.timbangan.models import TimbanganTransaksi,TimbanganAkun,ROLE_PETUGAS,ROLE_ADMIN,ROLE_SUPERADMIN
from app.timbangan.security import hash_sandi

async def isi(peran='operator',jumlah=110):
    async with database.SessionLocal() as db:
        kini=sekarang()
        db.add(TimbanganAkun(username='fixture-'+peran,nama='Fixture '+peran,
            role={'operator':ROLE_PETUGAS,'admin':ROLE_ADMIN,'superadmin':ROLE_SUPERADMIN}[peran],
            password_hash=hash_sandi('rahasia123'),perangkat_kode='P1'))
        for i in range(1,jumlah+1):
            db.add(TimbanganTransaksi(kode=f'UJB-{i:04}',tanggal=kini.date(),arah='BEBAS',jenis_kode='BEBAS',
                nomor_polisi=f'AD {1000+i} UJ',pihak_nama='Pemilik Fiktif',nama_sopir='Sopir Fiktif',
                timbang1_kg=15000,timbang1_waktu=kini+timedelta(seconds=i),timbang2_kg=5000,
                timbang2_waktu=kini+timedelta(seconds=i),status_tiket='SELESAI',status_transaksi='AKTIF',
                netto_timbangan_kg=10000,berat_barang_kg=10000,status_kontrol='TANPA_KONTROL'))
        await db.commit()

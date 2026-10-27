"""Penutupan lembar bersamaan tidak boleh menimpa hasil/audit pertama."""
import asyncio
import pytest
from sqlalchemy import select,func
from app.timbangan import service
from app.timbangan.models import TimbanganAkun,TimbanganTransaksi,TimbanganPemeriksaan,TimbanganAudit

async def test_penutupan_bersamaan_dengan_lembar_orm_lama(mesin):
    async with mesin() as db:
        a=TimbanganAkun(username='admin',nama='Admin Sintetis',role='ADMIN',password_hash='x',perangkat_kode='U1');db.add(a);await db.flush()
        from app.timbangan.db import sekarang,hari_ini
        t=TimbanganTransaksi(kode='UJI-INSPEKSI',tanggal=hari_ini(),jenis_kode='GABAH_BASAH',arah='MASUK',timbang1_kg=1000,timbang1_waktu=sekarang(),timbang1_petugas_id=a.id,status_kontrol='PERLU_PEMERIKSAAN',berat_barang_kg=900,selisih_kg=-100,status_tiket='SELESAI');db.add(t);await db.flush()
        l=TimbanganPemeriksaan(transaksi_id=t.id);db.add(l);await db.commit();aid,lid=a.id,l.id
    siap=0;gerbang=asyncio.Event()
    async def tutup(i):
        nonlocal siap
        async with mesin() as db:
            a=await db.get(TimbanganAkun,aid);l=await db.get(TimbanganPemeriksaan,lid)
            siap+=1
            if siap==5:gerbang.set()
            await gerbang.wait()
            try:
                await service.selesaikan_pemeriksaan(db,akun=a,lembar=l,langkah={},kategori_hasil='SALAH_CATAT',catatan_resolusi=f'Uji balapan {i}',dilaporkan_ke='Miftah')
                return 'sukses'
            except service.LayananError:return 'ditolak'
    hasil=await asyncio.gather(*[tutup(i) for i in range(5)])
    assert hasil.count('sukses')==1,hasil
    async with mesin() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit).where(TimbanganAudit.aksi=='PEMERIKSAAN_SELESAI'))==1
        t=await db.get(TimbanganTransaksi,t.id);assert (t.berat_barang_kg,t.selisih_kg,t.status_kontrol)==(900,-100,'PERLU_PEMERIKSAAN')

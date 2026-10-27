"""Benih sintetis untuk kontrak layar; tidak diimpor aplikasi produksi."""
from datetime import timedelta
from sqlalchemy import select
from app.timbangan.db import sekarang
from app.timbangan.models import (
    CARA_PARTAI, TimbanganAkun, TimbanganPenimbangan, TimbanganTransaksi,
    TimbanganPemeriksaan,
)

async def isi_riwayat(Sesi, jumlah=64):
    async with Sesi() as db:
        petugas = await db.scalar(select(TimbanganAkun).order_by(TimbanganAkun.id.desc()))
        kini=sekarang();hasil=[]
        kegiatan=[('GABAH_BASAH','MASUK'),('PENGIRIMAN','KELUAR'),
                  ('TRANSFER','TRANSFER'),('RETUR_PELANGGAN','RETUR_MASUK'),
                  ('RETUR_SUPPLIER','RETUR_KELUAR'),('BEBAS','BEBAS'),('GABAH_KERING','MASUK')]
        status=['NORMAL','PERLU_PEMERIKSAAN','INVESTIGASI','KURANG','KELEBIHAN','TANPA_KONTROL']
        for i in range(jumlah):
            jenis,arah=kegiatan[i%len(kegiatan)]
            partai=i in (7,8)
            if partai: jenis,arah='GABAH_KERING','MASUK'
            ouvert=i in (0,7,10)
            t=TimbanganTransaksi(
                kode=f'UJR-{i:04}',tanggal=kini.date()-timedelta(days=i//56),
                arah=arah,jenis_kode=jenis,pihak_nama=f'Pihak Sintetis {i}',
                nomor_polisi=None if partai else f'W {1000+i} UJ',
                nama_sopir=f'Sopir Regresi {i}',jasa=i==6,
                timbang1_kg=28.023 if partai else 15000,
                timbang1_waktu=kini-timedelta(hours=i),timbang1_petugas_id=petugas.id,
                timbang2_kg=None if ouvert or partai else 5000,
                timbang2_waktu=None if ouvert else kini-timedelta(minutes=i),
                status_tiket='TERBUKA' if ouvert else 'SELESAI',
                status_transaksi='VOID' if i==4 else 'AKTIF',
                netto_timbangan_kg=None if ouvert else 10000,
                berat_barang_kg=None if ouvert else (28.023 if partai else 9975),
                total_tara_kg=0 if partai else 25,
                selisih_kg=None if ouvert else (-48.5 if i%2 else 12.5),
                selisih_persen=None if ouvert else -0.5,
                status_kontrol=None if ouvert else status[i%len(status)],
                **({'cara_timbang':CARA_PARTAI} if partai else {}))
            if i==2:
                t.status_tiket='DITUTUP_PAKSA';t.timbang2_kg=None;t.timbang2_waktu=None
                t.berat_barang_kg=None;t.tutup_paksa_alasan='Truk sudah pergi, data sintetis'
            if i==9:t.berat_barang_kg=0;t.selisih_kg=0
            db.add(t);await db.flush();hasil.append(t.id)
            if partai:
                for n,w in enumerate([12.345,15.678]):
                    db.add(TimbanganPenimbangan(transaksi_id=t.id,urutan=n+1,berat_kg=w,petugas_id=petugas.id))
            if i in (1,3):
                db.add(TimbanganPemeriksaan(transaksi_id=t.id,status='SELESAI' if i==1 else 'DIBUKA',catatan_resolusi='Selesai diperiksa secara sintetis' if i==1 else None))
        await db.commit()
        return hasil

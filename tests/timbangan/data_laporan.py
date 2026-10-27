"""Data sintetis beragam tanggal/status; tidak diimpor aplikasi produksi."""
from datetime import timedelta
from sqlalchemy import select,func
from app.models import Supplier
from app.timbangan.db import hari_ini,sekarang
from app.timbangan.models import TimbanganAkun,TimbanganTransaksi,TimbanganPemeriksaan,TimbanganTaraStandar,TimbanganSupplierProfil

async def isi_laporan(Sesi):
    async with Sesi() as db:
        a=await db.scalar(select(TimbanganAkun).order_by(TimbanganAkun.id));kini=sekarang();hari=hari_ini()
        suppliers=[]
        for nama in ['Pemasok Sintetis — Nama Panjang untuk Pemeriksaan Responsif','Pemasok Data Belum Lengkap','Pemasok Belum Cukup Transaksi']:
            s=Supplier(nama_supplier=nama);db.add(s);await db.flush();suppliers.append(s.id)
        hasil=[]
        specs=[('MASUK',1000,-100,'PERLU_PEMERIKSAAN',0),('RETUR_MASUK',250,-25,'KURANG',0),('KELUAR',700,0,'NORMAL',0),('RETUR_KELUAR',100,-10,'KELEBIHAN',0),('TRANSFER',900,-90,'INVESTIGASI',0),('BEBAS',800,0,'NORMAL',0),('MASUK',999,-99,'INVESTIGASI',0),('MASUK',None,None,None,0),('MASUK',0,0,'NORMAL',0),('MASUK',975,-25,'NORMAL',60),('MASUK',600,-60,'PERLU_PEMERIKSAAN',70)]
        for i,(arah,kg,diff,status,age) in enumerate(specs):
            jenis={'MASUK':'GABAH_BASAH','RETUR_MASUK':'RETUR_PELANGGAN','KELUAR':'PENGIRIMAN','RETUR_KELUAR':'RETUR_SUPPLIER','TRANSFER':'TRANSFER','BEBAS':'BEBAS'}[arah]
            t=TimbanganTransaksi(kode=f'UJL-{i:03}',tanggal=hari-timedelta(days=age),arah=arah,jenis_kode=jenis,supplier_id=suppliers[0] if arah=='MASUK' else None,pihak_nama='=Pihak Sintetis' if i==3 else 'Pihak Pengujian',nomor_polisi=f'W {100+i} UJ',nama_sopir='Sopir Sintetis',timbang1_kg=1500,timbang1_waktu=kini-timedelta(days=age),timbang1_petugas_id=a.id,timbang2_kg=500 if kg is not None else None,timbang2_waktu=kini if kg is not None else None,status_tiket='SELESAI' if kg is not None else 'TERBUKA',status_transaksi='VOID' if i==6 else 'AKTIF',berat_barang_kg=kg,netto_timbangan_kg=1000 if kg is not None else None,selisih_kg=diff,selisih_persen=diff/10 if diff is not None else None,berat_acuan_kg=1100 if diff else None,status_kontrol=status)
            db.add(t);await db.flush();hasil.append(t.id)
            if i in (0,3,9,10):db.add(TimbanganPemeriksaan(transaksi_id=t.id,status='SELESAI' if i==3 else 'DIBUKA',catatan_resolusi='Sudah ditelusuri' if i==3 else None))
        for idx,jumlah in [(1,3),(2,2)]:
            for i in range(jumlah):
                t=TimbanganTransaksi(kode=f'UJL-S{idx}-{i}',tanggal=hari,arah='MASUK',jenis_kode='GABAH_BASAH',supplier_id=suppliers[idx],timbang1_kg=1500,timbang1_waktu=kini,timbang1_petugas_id=a.id,status_tiket='TERBUKA');db.add(t)
        db.add(TimbanganSupplierProfil(supplier_id=suppliers[0],status_monitoring='AKTIF'))
        db.add(TimbanganTaraStandar(jenis_kode='GABAH_BASAH',tara_per_karung_kg=.123,jumlah_sampel=10,total_berat_kg=1.23,berlaku_mulai=hari-timedelta(days=20),berlaku_sampai=hari+timedelta(days=2)))
        await db.commit();return hasil,suppliers

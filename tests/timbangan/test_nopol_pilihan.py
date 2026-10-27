"""Daftar kendaraan dibaca tanpa mengubah master ataupun tiket historis."""
import pytest
from sqlalchemy import select,func
from app.timbangan import service
from app.timbangan.models import TimbanganKendaraan,TimbanganTransaksi
from test_pemasok_kledo import masukan

@pytest.mark.usefixtures('jenis_tersemai')
async def test_pilihan_master_dan_riwayat_valid_tanpa_menulis_ulang(db,petugas,supplier):
 t=await service.simpan_timbang_pertama(db,akun=petugas,data=masukan(supplier.id))
 t.nomor_polisi='H9313 IC';t.kendaraan_id=None
 db.add_all([
  TimbanganKendaraan(nomor_polisi='H 9313 IC'),
  TimbanganKendaraan(nomor_polisi='H9313IC'),
  TimbanganKendaraan(nomor_polisi='B 2002 BB'),
  TimbanganKendaraan(nomor_polisi='ZZ 9 ZZ',status='nonaktif'),
  TimbanganKendaraan(nomor_polisi='-'),
  TimbanganKendaraan(nomor_polisi='3840'),
  TimbanganKendaraan(nomor_polisi='K 8382 CC'),
  TimbanganKendaraan(nomor_polisi='K 8482 CC'),
 ])
 await db.commit()
 before=await db.scalar(select(func.count()).select_from(TimbanganKendaraan))
 options=await service.kendaraan_pilihan(db)
 assert {o.nomor_polisi for o in options}=={'AD 1234 UJ','H 9313 IC','B 2002 BB','K 8382 CC','K 8482 CC'}
 assert sum(o.nomor_polisi=='H 9313 IC' for o in options)==1
 assert next(o for o in options if o.nomor_polisi=='H 9313 IC').sopir_terakhir=='Sopir Uji'
 assert await db.scalar(select(func.count()).select_from(TimbanganKendaraan))==before
 await db.refresh(t)
 assert t.nomor_polisi=='H9313 IC' and t.kendaraan_id is None
 assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==1

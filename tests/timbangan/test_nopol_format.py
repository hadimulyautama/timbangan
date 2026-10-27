"""Format baru tegas; identitas dan catatan historis tetap dapat dikerjakan."""
import pytest
from sqlalchemy import select,func
from app.timbangan import service
from app.timbangan.models import TimbanganTransaksi,TimbanganKendaraan
from hmu_core import normalisasi_nomor_polisi
from hmu_core.armada import validasi_nomor_polisi
from test_pemasok_kledo import masukan

@pytest.mark.parametrize('raw,expected',[
 ('H9313IC','H 9313 IC'),('H9313 IC','H 9313 IC'),(' ad8872la ','AD 8872 LA'),
 ('AD 8872LA','AD 8872 LA'),('ＡＤ１２３４ＸＹ','AD 1234 XY'),('AD0001AB','AD 0001 AB'),
 (' A D  88 72  L A ','AD 8872 LA'),(None,None),('  ',None)])
def test_rapikan_tanpa_mengganti_rangkaian_karakter(raw,expected):
 assert normalisasi_nomor_polisi(raw)==validasi_nomor_polisi(raw)==expected

@pytest.mark.parametrize('bad',['3840','ABCD','-','???','123AB','AB123','AB12CD3','AD-1234-XY','AD 12.34 XY'])
def test_format_tidak_lengkap_atau_tanda_baca_ditolak(bad):
 with pytest.raises(ValueError,match='Format nomor polisi'):validasi_nomor_polisi(bad)

@pytest.mark.usefixtures('jenis_tersemai')
@pytest.mark.parametrize('cara',['DUA_KALI','PARTAI'])
@pytest.mark.parametrize('bad',['3840','ABCD','-','AB12CD3'])
async def test_server_tolak_tiket_baru_sebelum_mendaftarkan_kendaraan(db,petugas,supplier,cara,bad):
 data=masukan(supplier.id,cara=cara);data.nomor_polisi=bad
 with pytest.raises(service.LayananError,match='Format nomor polisi'):
  await service.simpan_timbang_pertama(db,akun=petugas,data=data)
 assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==0
 assert await db.scalar(select(func.count()).select_from(TimbanganKendaraan))==0

@pytest.mark.usefixtures('jenis_tersemai')
async def test_kendaraan_tanpa_spasi_dan_dengan_spasi_tetap_satu(db,admin,supplier):
 for plate in ['H9313IC','H 9313 IC','h9313 ic']:
  data=masukan(supplier.id);data.nomor_polisi=plate
  t=await service.simpan_timbang_pertama(db,akun=admin,data=data)
  assert t.nomor_polisi=='H 9313 IC'
 assert await db.scalar(select(func.count()).select_from(TimbanganKendaraan))==1
 assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==3

@pytest.mark.usefixtures('jenis_tersemai')
@pytest.mark.parametrize('old',['3840','-','ABCD','H9313 IC'])
async def test_catatan_lama_tidak_terkunci_oleh_aturan_baru(db,admin,supplier,old):
 data=masukan(supplier.id)
 t=await service.simpan_timbang_pertama(db,akun=admin,data=data)
 t.nomor_polisi=old;t.kendaraan_id=None
 await db.commit()
 data.nomor_polisi=old
 replay=await service.simpan_timbang_pertama(db,akun=admin,data=data)
 assert replay.id==t.id and replay.nomor_polisi==normalisasi_nomor_polisi(old)
 # Tiket lama tanpa nomor lengkap tidak ditawarkan untuk perjalanan baru.
 saran=await service.kendaraan_dikenal(db)
 assert (len(saran)==1)==(old=='H9313 IC')
 hasil=await service.simpan_timbang_kedua(db,akun=admin,kode=t.kode,berat_kg=5000)
 assert float(hasil.berat_barang_kg)==10000
 await service.koreksi_transaksi(db,akun=admin,trx=hasil,perubahan={'nomor_polisi':hasil.nomor_polisi,'catatan':'Riwayat tetap aman'})
 with pytest.raises(service.LayananError,match='Format nomor polisi'):
  await service.koreksi_transaksi(db,akun=admin,trx=hasil,perubahan={'nomor_polisi':'9999'})

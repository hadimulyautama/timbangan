from types import SimpleNamespace as NS
import pytest
from app.timbangan.breadcrumb import susun

@pytest.mark.parametrize('path,ctx,title,labels,back',[
 ('/timbangan/',{},'Pos Timbang',['Beranda'],None),
 ('/timbangan/transaksi',{},'Riwayat Timbang',['Beranda','Riwayat Timbang'],'/timbangan/'),
 ('/timbangan/transaksi/8',{'b':NS(trx=NS(kode='TT-008'))},'B 123 XY',['Beranda','Riwayat Timbang','TT-008'],'/timbangan/transaksi'),
 ('/timbangan/transaksi/8?kembali=%2Ftimbangan%2Ftransaksi%3Fcari%3DSuroto',{'b':NS(trx=NS(kode='TT-008'))},'Detail tiket',['Beranda','Riwayat Timbang','TT-008'],'/timbangan/transaksi?cari=Suroto'),
 ('/timbangan/transaksi/8/koreksi',{'b':NS(trx=NS(kode='TT-008'))},'Koreksi TT-008',['Beranda','Riwayat Timbang','TT-008','Koreksi tiket'],'/timbangan/transaksi/8'),
 ('/timbangan/tiket/8',{'b':NS(trx=NS(kode='TT-008'))},'B 123 XY',['Beranda','Tiket Aktif','TT-008'],'/timbangan/tiket'),
 ('/timbangan/pengguna/8',{},'Ubah akun',['Beranda','Pengaturan','Pengguna','Ubah akun'],'/timbangan/pengguna'),
 ('/timbangan/printer',{},'Pos & printer',['Beranda','Pengaturan','Pos & printer'],'/timbangan/pengaturan'),
 ('/timbangan/printer',{'kembali':'/timbangan/transaksi/8'},'Pos & printer',['Beranda','Riwayat Timbang','Detail tiket','Pos & printer'],'/timbangan/transaksi/8'),
])
def test_rantai_desktop_tidak_melewati_induk(path,ctx,title,labels,back):
 d=susun(path,ctx,title);assert [x['nama'] for x in d['items']]==labels;assert d['kembali']==back
 assert d['items'][-1]['alamat'] is None
 assert not back or back==d['items'][-2]['alamat']

@pytest.mark.parametrize('arah',['MASUK','KELUAR','TRANSFER','RETUR_MASUK','RETUR_KELUAR','BEBAS'])
def test_semua_jenis_riwayat_memakai_parent_dan_kode_yang_sama(arah):
 d=susun('/timbangan/transaksi/8',{'b':NS(trx=NS(kode='TT-8',arah=arah)),'kembali':'/timbangan/'},'Judul jenis berbeda')
 assert [x['nama'] for x in d['items']]==['Beranda','Riwayat Timbang','TT-8'] and d['kembali']=='/timbangan/transaksi'

def test_koreksi_detail_daftar_mempertahankan_filter_dua_kali_kembali():
 from urllib.parse import quote,urlsplit,parse_qs
 target='/timbangan/transaksi?cari=Suroto&arah=KELUAR'
 d=susun('/timbangan/transaksi/8/koreksi?kembali='+quote(target,safe=''),{'b':NS(trx=NS(kode='TT-8')),'kembali':'/timbangan/transaksi/8'},'Koreksi')
 assert parse_qs(urlsplit(d['kembali']).query)['kembali']==[target]
 detail=susun(d['kembali'],{'b':NS(trx=NS(kode='TT-8')),'kembali':'/timbangan/'},'Detail')
 assert detail['kembali']==target

from types import SimpleNamespace as N
import pytest
from app.timbangan.rincian_keluar import tahap_pengiriman

@pytest.mark.parametrize('weigh,void,production,expected',[
 ('SELESAI','AKTIF','menunggu','Selesai timbang'),
 ('TERBUKA','AKTIF','terverifikasi','Menunggu timbang kedua'),
 ('SELESAI','VOID','terverifikasi','Tiket dibatalkan'),
 ('DITUTUP_PAKSA','AKTIF','tidak_pasti','Ditutup tanpa timbang kedua'),
])
def test_timbang_dan_status_produksi_independen(weigh,void,production,expected):
 p=dict(kode=production,label='Status asli PadiFlow',perintah=[dict(status='dimuat')])
 d=tahap_pengiriman(N(status_tiket=weigh,status_transaksi=void),p)
 assert d['timbang']==expected and d['verifikasi']=='Status asli PadiFlow'
 if production=='tidak_pasti':assert 'belum dapat dibaca' in d['berikut']

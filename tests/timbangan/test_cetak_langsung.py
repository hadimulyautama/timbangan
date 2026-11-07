"""Konteks baca saja dan kontrol bersama di seluruh jenis detail."""
import pytest
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_rincian_supplier import tiket
from test_timbang_kedua_desain_browser import ALUR,tiket_uji
from app import database
from app.timbangan.models import TimbanganPekerjaanCetak as Job
from test_pdf_digital import keadaan

async def test_konteks_baca_saja_dan_ncr_tidak_ditawarkan(klien):
    tid=await tiket();await login(klien,'wahid');before=await keadaan(tid)
    for _ in range(2):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/konteks');assert r.status_code==200
        assert r.json()['ulang'] is False and r.json()['pekerjaan'] is None
    assert await keadaan(tid)==before
    r=await klien.get(f'/timbangan/transaksi/{tid}/cetak')
    assert 'PDF setengah NCR' not in r.text and 'value="NCR"' not in r.text

@pytest.mark.parametrize('arah,kode',ALUR)
async def test_kontrol_semua_detail_tiket_terbuka_tidak_menawarkan_bukti(klien,arah,kode):
    await login(klien,'wahid');tid=await tiket_uji(arah,kode)
    r=await klien.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200
    assert 'data-cetak-langsung data-tiket' not in r.text
    r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/konteks');assert r.status_code==409

@pytest.mark.parametrize('jenis',['masuk','keluar','transfer','retur_pelanggan','retur_supplier'])
async def test_kontrol_selesai_konsisten_semua_jenis(klien,jenis):
    from test_web import _selesaikan
    from test_rincian_keluar import buat_tiket
    from test_rincian_transfer import master,tiket as transfer
    from test_rincian_retur import tiket as retur
    await login(klien,'wahid')
    if jenis=='masuk':tid=await _selesaikan(klien,'GABAH_BASAH')
    elif jenis=='keluar':tid=await buat_tiket()
    elif jenis=='transfer':await master();tid=await transfer()
    elif jenis=='retur_pelanggan':tid=await retur()
    else:tid=await tiket()
    r=await klien.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200
    assert 'data-cetak-langsung data-tiket' in r.text and '>Lihat</button>' in r.text and '>Bagikan</a>' in r.text
    assert 'cetak-langsung.js?v=109' in r.text
    r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/konteks');assert r.status_code==200

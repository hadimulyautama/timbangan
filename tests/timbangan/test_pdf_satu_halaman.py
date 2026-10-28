"""Nota normal utuh dalam satu lembar 80 mm maupun setengah NCR."""
import io
from copy import deepcopy
from decimal import Decimal
from datetime import date
from types import SimpleNamespace
import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm
from test_epos import _trx,_aturan
from app.timbangan import pdf


def contoh(*,panjang=False,arah='MASUK'):
    t=_trx(arah=arah,kode='MSK-UJI-20261028-001',
        tanggal=date(2026,10,28),berat_bermuatan_kg=12000,berat_kosong_kg=1990,
        nama_sopir='Sopir Uji dengan Nama Panjang' if panjang else 'Sopir Uji',
        jumlah_karung=125,total_tara_kg=Decimal('12.5'),tara_lain_kg=0,
        netto_timbangan_kg=10010,berat_barang_kg=Decimal('9997.5'),
        berat_acuan_kg=10000,selisih_kg=Decimal('-2.5'))
    return dict(trx=t,aturan=_aturan(nama='Beras putih'),pihak='Pemasok Uji',
        petugas='Petugas Uji dengan Nama Panjang' if panjang else 'Petugas Uji',muatan=[],
        perusahaan='PERUSAHAAN UJI - BUKAN TRANSAKSI',
        alamat='Jalan Contoh 123, Kabupaten Contoh',telepon='Telepon uji',
        arah_masuk=arah=='MASUK')


@pytest.mark.parametrize('format',['80mm','ncr'])
@pytest.mark.parametrize('panjang',[False,True])
@pytest.mark.parametrize('arah',['MASUK','KELUAR'])
@pytest.mark.parametrize('tambahan',[False,True])
def test_nota_normal_dan_tanda_tangan_tetap_satu_halaman(format,panjang,arah,tambahan):
    u=contoh(panjang=panjang,arah=arah)
    if tambahan:
        u['muatan']=[SimpleNamespace(nomor_acuan='NOTA-UJI-20261028-001')]
        u['trx'].catatan='Catatan penerimaan uji sesuai jumlah timbang yang tersimpan.'
    awal=deepcopy(vars(u['trx']))
    cetak=pdf.bukti_thermal if format=='80mm' else pdf.bukti_ncr
    raw=cetak(**u,tampilkan_selisih=True);reader=PdfReader(io.BytesIO(raw))
    assert len(reader.pages)==1
    page=reader.pages[0];text=page.extract_text()
    for token in ('MSK-UJI-20261028-001','Pemasok Uji','Beras putih','BERAT BARANG',
                  '9.998 kg','Petugas pencetak','Sopir / saksi','Ditandatangani kedua pihak'):
        assert token in text
    assert ('Menurut dokumen' in text)==(format=='80mm')
    assert ('Selisih' in text)==(format=='80mm')
    assert float(page.mediabox.width)==pytest.approx((80 if format=='80mm' else 215)*mm,abs=.01)
    if format=='ncr':
        assert float(page.mediabox.height)==pytest.approx(165*mm,abs=.01)
        assert 'Lembar 1' in text and 'Lembar 2' in text
    assert vars(u['trx'])==awal
    assert raw==cetak(**u,tampilkan_selisih=True)


@pytest.mark.parametrize('format',['80mm','ncr'])
def test_partai_kecil_tetap_utuh_satu_halaman(format):
    u=contoh(panjang=True);u['trx'].partai=True
    u['trx'].penimbangan=[SimpleNamespace(urutan=i+1,berat_kg=n,waktu=u['trx'].timbang1_waktu)
                         for i,n in enumerate([3000,3000,4010])]
    cetak=pdf.bukti_thermal if format=='80mm' else pdf.bukti_ncr
    reader=PdfReader(io.BytesIO(cetak(**u,tampilkan_selisih=True)))
    assert len(reader.pages)==1
    text=reader.pages[0].extract_text()
    for label in ('Timbang 1','Timbang 2','Timbang 3','Jumlah 3 kali timbang',
                  'Petugas pencetak','Ditandatangani kedua pihak'):
        assert label in text

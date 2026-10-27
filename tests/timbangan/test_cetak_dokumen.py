"""Keluaran nyata dari fixture sintetis: panjang, privasi, ukuran, dan angka."""
import io
from copy import deepcopy
from pathlib import Path
from decimal import Decimal
from xml.etree import ElementTree as ET
import pytest
from pypdf import PdfReader
from test_epos import _trx,_aturan
from test_pengiriman_gabungan import payload
from app.timbangan import pdf,epos,pengiriman,bukti
OUT=Path('/Users/wahidnurhani/Developer/Hadi Mulya Systems/output/pratinjau-cetak-20261027')

def data(panjang=False):
    p=payload()
    if panjang:
        p['muatan']=[dict(p['muatan'][i%4],outgoing_item_id=1000+i,nama=f'PRODUK-UJI-{i:03d} kemasan panjang') for i in range(72)]
    t=_trx(arah='KELUAR',jenis_kode='PENGIRIMAN',pengiriman_snapshot=pengiriman.cuplikan(p),jumlah_revisi=2,
           catatan='Catatan sintetis utuh: '+('teks panjang untuk pengujian. '*15 if panjang else 'tanpa rincian tambahan'),
           nama_sopir='Saksi Sintetis dengan Nama Sangat Panjang Sampai Ujung',jumlah_karung=100,total_tara_kg=Decimal('10.58'),tara_lain_kg=2)
    return dict(trx=t,aturan=_aturan(rahasia=True),pihak='Pengiriman gabungan',petugas='Pencetak Sintetis dengan Nama Sangat Panjang Sampai Akhir',muatan=[],
                perusahaan='PERUSAHAAN UJI BUKAN TRANSAKSI',alamat='ALAMAT SINTETIS',telepon='',arah_masuk=False)

@pytest.mark.parametrize('format',['80MM','NCR'])
@pytest.mark.parametrize('panjang',[False,True])
def test_pdf_semua_barang_ttd_ukuran_dan_rahasia(format,panjang):
    u=data(panjang);before=deepcopy(vars(u['trx']))
    raw=pdf.bukti_ncr(**u) if format=='NCR' else pdf.bukti_thermal(**u,tampilkan_selisih=False)
    assert raw==(pdf.bukti_ncr(**u) if format=='NCR' else pdf.bukti_thermal(**u,tampilkan_selisih=False))
    reader=PdfReader(io.BytesIO(raw));text='\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)>1 if panjang else len(reader.pages)>=1
    for i in range(72 if panjang else 0):assert f'PRODUK-UJI-{i:03d}' in text
    for nama in ('Penerima Uji 0','Penerima Uji 1','Petugas pencetak','Sopir / saksi','Sampai Akhir','Sampai Ujung'):assert nama in text.replace('\n',' ')
    for forbidden in ('Menurut dokumen','Selisih','Subtotal muat','Total acuan'):assert forbidden not in text
    assert text.index('Tara truk')<text.index('Bruto')
    assert '- 8,580 kg' in text and '- 2,00 kg' in text
    labelpage=[p for p in reader.pages if 'Petugas pencetak' in p.extract_text()];assert len(labelpage)==1
    p=labelpage[0];assert 'Sampai Akhir' in p.extract_text().replace('\n',' ') and 'Sampai Ujung' in p.extract_text().replace('\n',' ')
    coords=[]
    def visit(s,cm,tm,font,fs):
        if s.strip():coords.append((s.strip(),tm[4]*cm[0]+tm[5]*cm[2]+cm[4],tm[4]*cm[1]+tm[5]*cm[3]+cm[5],fs))
    p.extract_text(visitor_text=visit)
    label=next(c for c in coords if c[0]=='Petugas pencetak')
    nama=next(c for c in coords if c[0].startswith('Pencetak Sintetis'))
    # Baseline label ke bagian atas nama, dikurangi tinggi baris label/nama.
    assert label[2]-nama[2]-2*label[3] >= (25 if format=='NCR' else 20)*72/25.4
    for page in reader.pages:
        assert float(page.mediabox.width)==pytest.approx((215 if format=='NCR' else 80)*72/25.4,abs=.01)
        if format=='NCR':assert float(page.mediabox.height)==pytest.approx(165*72/25.4,abs=.01)
    assert vars(u['trx'])==before
    OUT.mkdir(parents=True,exist_ok=True);(OUT/f'dokumen-{format}-{panjang}.pdf').write_bytes(raw)

def test_epos_nama_barang_tidak_terpotong_feed_dan_potong_akhir():
    u=data(True);xml=epos.struk_timbang(**u,tampilkan_selisih=False)
    els=list(ET.fromstring(xml).iter());texts=[e for e in els if e.tag.endswith('text')]
    text='\n'.join(e.text or '' for e in texts)
    for i in range(72):assert f'PRODUK-UJI-{i:03d}' in text
    assert 'Sampai Akhir' in text and 'Sampai Ujung' in text
    for e in texts:
        for line in (e.text or '').splitlines():assert len(line)<=(24 if e.get('dw')=='true' else 48)
    sig=next(i for i,e in enumerate(els) if 'Petugas pencetak' in (e.text or ''))
    assert els[sig+1].attrib=={'unit':'160'}
    assert 160/203*25.4>=20
    assert els[-1].tag.endswith('cut') and xml.count('<cut')==1
    assert 'Subtotal muat' not in text and 'Menurut dokumen' not in text

@pytest.mark.parametrize('arah',['MASUK','KELUAR','TRANSFER','RETUR_MASUK','RETUR_KELUAR'])
def test_tara_dan_urutan_tidak_mengubah_hasil(arah):
    t=_trx(arah=arah,total_tara_kg=Decimal('10.58'),tara_lain_kg=2,jumlah_karung=100)
    masuk=arah not in ('KELUAR','RETUR_KELUAR');rows=bukti.baris_angka(t,masuk);s='\n'.join(b.label+' '+b.nilai for b in rows)
    assert rows[0].label.startswith('Bruto' if masuk else 'Tara truk')
    if arah.startswith('RETUR'):assert 'Tara kemasan' not in s and 'Tara lain' not in s
    else:assert '- 8,580 kg' in s and '- 2,00 kg' in s and '- 10,580' not in s
    assert t.berat_barang_kg==8240

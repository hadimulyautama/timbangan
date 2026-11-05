"""Data perusahaan berubah; renderer dan ukuran NCR/thermal tetap sama."""
from io import BytesIO
from types import SimpleNamespace as N
from pypdf import PdfReader
import pytest
from test_pdf_satu_halaman import contoh
from app.timbangan import cetak

@pytest.mark.asyncio
async def test_bahan_cetak_memakai_identitas_tersimpan(monkeypatch,db):
    from hmu_dokumen import perusahaan
    u=contoh()
    u["trx"].muatan=[]
    async def identitas(db):return perusahaan.Perusahaan(nama='PT Identitas Terbaru',alamat='Alamat terbaru',telepon='080000',email='uji@example.com',website='https://example.com')
    async def ambil(db,tid):return N(trx=u['trx'],pihak_tampil=u['pihak'])
    async def urutan(db,tid):return 1
    import json
    from sqlalchemy import text
    await db.execute(text('INSERT INTO setelan_pabrik (kunci,nilai) VALUES (:k,:v)'),
        {'k':perusahaan.KUNCI,'v':json.dumps((await identitas(db)).data())})
    await db.commit()
    monkeypatch.setattr(cetak.service,'ambil_transaksi',ambil)
    monkeypatch.setattr(cetak.service,'pastikan_boleh_cetak',lambda trx:None)
    monkeypatch.setattr(cetak.service,'aturan_dari_snapshot',lambda trx:u['aturan'])
    monkeypatch.setattr(cetak.service,'cetakan_ke',urutan)
    _,_,baru=await cetak.bahan(db,1,N(nama='Petugas Uji'))
    assert baru['perusahaan']=='PT Identitas Terbaru'
    for format in ['NCR','80MM']:
        reader=PdfReader(BytesIO(cetak.dokumen(baru,format)))
        text=' '.join(p.extract_text() for p in reader.pages)
        assert 'PT Identitas Terbaru' in text and 'uji@example.com' in text and 'https://example.com' in text
        assert len(reader.pages)==1

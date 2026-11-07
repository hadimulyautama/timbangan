"""PDF digital berulang tidak mengubah pekerjaan, audit, atau urutan cetak fisik."""
import io
import pytest
from pypdf import PdfReader
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_rincian_supplier import tiket
from test_cetak_pratinjau import siapkan
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganCetak,TimbanganPekerjaanCetak as Job,TimbanganAudit

async def keadaan(tid):
    async with database.SessionLocal() as db:
        return [await db.scalar(select(func.count()).select_from(m)) for m in (TimbanganCetak,Job,TimbanganAudit)] + [await service.cetakan_ke(db,tid)]

@pytest.mark.parametrize('pending',[False,True])
async def test_pdf_setelah_cetak_tetap_bebas_alasan_dan_tidak_mutasi(klien,pending):
    tid=await tiket();await login(klien,'wahid')
    j,_=await siapkan(klien,tid);base=f'/timbangan/transaksi/{tid}/cetak'
    await klien.post(base+'/pekerjaan/'+j['kunci']+'/kirim',json={})
    assert (await klien.post(base+'/pekerjaan/'+j['kunci']+'/hasil',json={'hasil':'printer_berhasil'})).status_code==200
    if pending:await siapkan(klien,tid,alasan='Salinan fisik tertunda')
    before=await keadaan(tid);assert before[0]==1 and before[-1]==2
    for _ in range(2):
        for fmt in ('80mm','ncr'):
            r=await klien.get(base+'/'+fmt);assert r.status_code==200 and r.headers['content-type']=='application/pdf'
            text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
            assert 'CETAKAN ULANG' not in text
            assert 'Petugas pencetak' in text
    assert await keadaan(tid)==before
    r=await klien.get(base);assert 'data-pdf-digital' in r.text and 'data-cetak-fisik' in r.text

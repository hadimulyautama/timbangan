"""Retur supplier: WebKit dan printer simulasi, database SQLite tiap kasus."""
import asyncio,io,os
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from pypdf import PdfReader
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_supplier import tiket,sumber
from test_rincian_retur import tautkan
from hmu_identitas import peran as P
from app import database
from app.timbangan.models import TimbanganCetak,TimbanganTransaksi

OUT=Path(os.environ.get('UJI_BUKTI_RS','/private/tmp/uji-supplier-lanjutan'))

@pytest.mark.skipif(not os.environ.get('UJI_WEBKIT_PATH'), reason='Profil WebKit lokal memerlukan UJI_WEBKIT_PATH')
@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_webkit_panel_dan_printer_gagal_klik_ganda(klien,alamat_ui,monkeypatch,role):
    tid=await tiket();await tautkan('miftah',role);await sumber(monkeypatch,tid);await login(klien,'miftah')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,320,'dark',browser='webkit')
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
        assert await page.locator('[data-retur-supplier]').count()==1
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        OUT.mkdir(parents=True,exist_ok=True);await page.screenshot(path=str(OUT/f'webkit-supplier-{role}-320.png'),full_page=True)
        await page.get_by_role('link',name='Cetak bukti timbang').click()
        await page.evaluate("localStorage.setItem('timbangan-printer','http://127.0.0.1:9999')")
        jobs=[];fail={'yes':True}
        async def printer(r):
            jobs.append(r.request.post_data)
            await asyncio.sleep(.1)
            await r.fulfill(status=200,content_type='text/xml',body='<response success="false" code="EPTR_COVER_OPEN"/>' if fail['yes'] else '<response success="true"/>')
        await page.route('**/cgi-bin/epos/**',printer)
        await page.locator('[data-cetak]').evaluate('(e)=>{e.click();e.click()}')
        await page.wait_for_function("document.querySelector('[data-hasil-cetak]').textContent.includes('Penutup printer terbuka')")
        assert len(jobs)==1
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        fail['yes']=False
        await page.locator('[data-cetak]').evaluate('(e)=>{e.click();e.click()}')
        await page.wait_for_url(lambda u:'ok=' in str(u));assert len(jobs)==2
        await page.locator('[data-cetak]').click()
        assert await page.evaluate("document.activeElement.name==='alasan'")
        assert len(jobs)==2
        await page.locator('form[data-catat-cetak] [name=alasan]').fill('UJI cetak ulang supplier, kertas simulasi')
        await page.locator('[data-cetak]').evaluate('(e)=>{e.click();e.click()}')
        await page.wait_for_function("document.querySelector('form[data-catat-cetak] [name=alasan]').value===''")
        async with database.SessionLocal() as db:
            rows=(await db.scalars(select(TimbanganCetak).order_by(TimbanganCetak.urutan))).all()
            assert len(rows)==2 and rows[1].alasan=='UJI cetak ulang supplier, kertas simulasi'
            assert (await db.get(TimbanganTransaksi,tid)).berat_barang_kg==70.1
        assert len(jobs)==3
        assert all('Retur' in x and '70' in x for x in jobs)
        await b.close()

async def test_pdf_epos_supplier_tanpa_pembanding_dan_tanpa_catatan_cetak(klien):
    tid=await tiket();await login(klien,'wahid');OUT.mkdir(parents=True,exist_ok=True)
    for fmt in ('80mm','ncr','epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/{fmt}');assert r.status_code==200
        if fmt=='epos':
            txt=r.text;(OUT/'supplier-epos.xml').write_text(txt)
        else:
            doc=PdfReader(io.BytesIO(r.content));txt='\n'.join(p.extract_text() for p in doc.pages)
            (OUT/f'supplier-{fmt}.pdf').write_bytes(r.content)
        assert 'Retur' in txt and '70' in txt
        assert 'Selesai di gudang' not in txt and '249' not in txt
        assert 'Selisih' not in txt and 'SELISIH' not in txt
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
@pytest.mark.parametrize('keadaan',['TERBUKA','DITUTUP_PAKSA','VOID'])
async def test_supplier_belum_sah_ditolak_semua_jalur_cetak(klien,keadaan,role):
    tid=await tiket(selesai=False);await tautkan('miftah',role);await login(klien,'miftah')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        if keadaan=='VOID':t.status_transaksi=keadaan
        else:t.status_tiket=keadaan
        await db.commit()
    for fmt in ('','/80mm','/ncr','/epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak'+fmt,follow_redirects=False)
        assert r.status_code in (303,400,409),r.status_code
        if r.status_code==303:assert 'err=' in r.headers['location']
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0

"""Cetak nyata dari detail memakai printer simulasi; tidak ada printer fisik."""
import asyncio,os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_supplier import tiket
from test_cetak_pratinjau import siapkan,jumlah
from app import database
from app.timbangan.models import TimbanganPekerjaanCetak as Job,TimbanganCetak,TimbanganTransaksi

@pytest.mark.parametrize('width', [1440,390,320])
async def test_satu_klik_cetak_dan_ulang_di_detail(klien,alamat_ui,width):
    tid=await tiket();await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,'dark' if width==390 else 'light')
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}?kembali=/timbangan/transaksi%3Fhal=2')
        lokasi=page.url;errors=[];requests=[];mode={'value':'ok'}
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def printer(r):
            if '<text' not in (r.request.post_data or ''):
                return await r.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
            requests.append(r.request.post_data);await asyncio.sleep(.1)
            if mode['value']=='unknown':return await r.abort()
            xml='<response success="false" code="EPTR_COVER_OPEN"/>' if mode['value']=='gagal' else '<response success="true"/>'
            await r.fulfill(status=200,content_type='text/xml',body=xml)
        await page.route('**/cgi-bin/epos/**',printer)
        await page.evaluate("localStorage.setItem('timbangan-printer','http://127.0.0.1:9999')")
        await page.get_by_role('button',name='Lihat',exact=True).click()
        await page.wait_for_function("document.querySelector('.tf-pdf-dialog [data-pdf-status]').textContent.endsWith('halaman')",timeout=15000)
        await page.get_by_role('button',name='Tutup PDF').click()
        assert page.url==lokasi and await jumlah()==0
        await page.locator('[data-cetak-langsung]').evaluate('(e)=>{e.click();e.click()}')
        try:await page.wait_for_function("document.querySelector('[data-cetak-langsung-hasil]').textContent.includes('berhasil')",timeout=8000)
        except Exception:assert False,dict(errors=errors,isi=await page.locator('.tf-cetak-dialog').text_content(),requests=requests)
        assert len(requests)==1 and await jumlah()==1 and page.url==lokasi
        assert not await page.locator('.tf-cetak-dialog').evaluate('e=>e.open')
        assert await page.locator('[data-cetak-langsung]').evaluate('e=>e===document.activeElement')
        await page.locator('[data-cetak-langsung]').click()
        alasan=page.locator('.tf-cetak-dialog [name=alasan]');await alasan.wait_for(state='visible')
        assert len(requests)==1
        await page.locator('.tf-cetak-dialog [data-cp-jalankan]').click();assert len(requests)==1
        await alasan.fill('Salinan untuk sopir')
        mode['value']='gagal';await page.locator('.tf-cetak-dialog [data-cp-jalankan]').click()
        await page.wait_for_function("document.querySelector('.tf-cetak-dialog [data-cp-status]').textContent.includes('Penutup printer')")
        assert await jumlah()==1 and await alasan.input_value()=='Salinan untuk sopir'
        mode['value']='unknown';await page.locator('.tf-cetak-dialog [data-cp-jalankan]').click()
        await page.wait_for_function("document.querySelector('.tf-cetak-dialog [data-cp-status]').textContent.includes('Jangan kirim ulang')")
        assert await jumlah()==1 and len(requests)==3
        await page.locator('.tf-cetak-dialog [data-tutup]').click()
        await page.locator('[data-cetak-langsung]').click()
        await page.locator('.tf-cetak-dialog [data-cp-ya]').wait_for(state='visible')
        assert len(requests)==3
        await page.locator('.tf-cetak-dialog [data-cp-ya]').click()
        await page.locator('.tf-cetak-dialog').wait_for(state='hidden')
        assert await jumlah()==2 and page.url==lokasi
        async with database.SessionLocal() as db:
            rows=(await db.scalars(select(TimbanganCetak).order_by(TimbanganCetak.urutan))).all()
            assert rows[-1].format=='80MM' and rows[-1].alasan=='Salinan untuk sopir'
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.locator('[data-cetak-langsung]').click();await alasan.wait_for(state='visible')
        assert await page.locator('.tf-cetak-dialog input[value=NCR]').count()==0
        assert await page.locator('.tf-cetak-dialog input[value=pdf]').count()==0
        assert await page.evaluate('document.querySelector(".tf-cetak-dialog").scrollWidth<=document.querySelector(".tf-cetak-dialog").clientWidth')
        assert await page.locator('.tf-cetak-dialog').evaluate("e=>getComputedStyle(e).backgroundColor!=='rgba(0, 0, 0, 0)'")
        out=Path(os.environ['UJI_CETAK_OUT']);out.mkdir(exist_ok=True,parents=True)
        await page.screenshot(path=str(out/f'cetak-detail-{width}.png'),full_page=True)
        await page.locator('.tf-cetak-dialog [data-tutup]').click()
        # PDF langsung tidak membuat pekerjaan atau cetak fisik meski sudah dicetak.
        async with database.SessionLocal() as db:before=await db.scalar(select(func.count()).select_from(Job))
        await page.evaluate("() => {Object.defineProperty(navigator,'userAgent',{value:'iPhone'});navigator.canShare=()=>true;navigator.share=async d=>{window.__pdf=d.files[0].type};}")
        await page.get_by_role('link',name='Bagikan',exact=True).click()
        await page.wait_for_function("window.__pdf==='application/pdf'")
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(Job))==before
        assert await jumlah()==2 and page.url==lokasi and not errors
        await b.close()

async def test_konteks_gagal_tidak_mencetak_dan_tiket_berubah(klien,alamat_ui):
    tid=await tiket();await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
        await page.route('**/cetak/konteks',lambda r:r.abort())
        await page.locator('[data-cetak-langsung]').click()
        await page.wait_for_function("!document.querySelector('.tf-cetak-dialog [data-tutup]').disabled")
        assert await jumlah()==0
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(Job))==0
        await page.locator('.tf-cetak-dialog [data-tutup]').click()
        await page.unroute('**/cetak/konteks')
        # Tiket yang dibatalkan setelah detail terbuka tetap ditolak server.
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid);t.status_transaksi='VOID';await db.commit()
        await page.locator('[data-cetak-langsung]').click()
        await page.wait_for_function("document.querySelector('.tf-cetak-dialog [data-isi]').textContent.includes('batal')")
        assert await jumlah()==0
        await b.close()

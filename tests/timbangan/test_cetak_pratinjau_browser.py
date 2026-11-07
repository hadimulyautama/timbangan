"""Interaksi aplikasi asli dan printer simulasi; tidak menyentuh perangkat."""
import os,asyncio
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_supplier import tiket
from test_rincian_retur import tautkan
from app import database
from app.timbangan.models import TimbanganCetak,TimbanganPekerjaanCetak as Job
from hmu_identitas import peran as P
OUT=Path(os.environ.get('UJI_CETAK_OUT','/tmp/pratinjau-cetak-uji'))

@pytest.mark.parametrize('width,theme,role',[(1440,'light',P.SUPERADMIN),(390,'dark',P.ADMIN),(320,'light',P.OPERATOR)])
async def test_ui_pratinjau_hasil_tidak_pasti_dan_cetak_ulang(klien,alamat_ui,width,theme,role):
    tid=await tiket();await tautkan('miftah',role);await login(klien,'miftah')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,theme,browser=os.environ.get('UJI_BROWSER','chromium'))
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}/cetak')
        await page.locator('[data-cetak-halaman]').wait_for()
        await page.evaluate("localStorage.setItem('timbangan-printer','http://127.0.0.1:9999')")
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        OUT.mkdir(exist_ok=True,parents=True)
        await page.screenshot(path=str(OUT/f'cetak-{width}-{theme}-{os.environ.get("UJI_BROWSER","chromium")}.png'),full_page=True)
        jobs=[];mode={'value':'unknown'}
        async def printer(r):
            if '<text' not in (r.request.post_data or ''):
                return await r.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
            jobs.append(r.request.post_data);await asyncio.sleep(.1)
            if mode['value']=='unknown':return await r.abort()
            return await r.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
        await page.route('**/cgi-bin/epos/**',printer)
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        await page.locator('[data-cp-jalankan]').evaluate('(e)=>{e.click();e.click()}')
        await page.wait_for_function("document.querySelector('[data-cp-status]').textContent.includes('Jangan kirim ulang')")
        assert len(jobs)==1
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        assert await page.locator('[data-cp-jalankan]').is_disabled()
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        await page.reload();await page.locator('[data-cp-ya]').wait_for(state='visible')
        await page.locator('[data-cp-ya]').evaluate('(e)=>{e.click();e.click()}')
        await page.wait_for_function("document.querySelector('.cp-history').textContent.includes('Cetak ke-1')")
        assert len(jobs)==1
        mode['value']='success'
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        await page.locator('[data-cp-jalankan]').click()
        assert len(jobs)==1
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        await page.locator('[name=alasan]').fill('UJI salinan printer simulasi')
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        await page.locator('[data-cp-jalankan]').evaluate('(e)=>{e.click();e.click()}')
        await page.wait_for_function("document.querySelector('.cp-history').textContent.includes('Cetak ke-2')")
        assert len(jobs)==2
        assert await page.locator('[name=cp-format][value=NCR]').count()==0
        assert not errors,errors
        await b.close()

async def test_printer_belum_ada_pdf_keyboard_dan_versi_berubah(klien,alamat_ui):
    from app.timbangan.models import TimbanganTransaksi
    tid=await tiket();await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,768,browser=os.environ.get('UJI_BROWSER','chromium'))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}/cetak')
        await page.evaluate("window.TeraFlowPrinter.alamat=()=>''")
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        await page.locator('[data-cp-jalankan]').press('Enter')
        assert 'Printer belum disetel' in await page.locator('[data-cp-status]').text_content()
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(Job))==0
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        # Jalur Bagikan iOS disimulasikan: berkas PDF asli, bukan cetak fisik.
        await page.evaluate("() => {Object.defineProperty(navigator,'userAgent',{value:'iPhone'});navigator.canShare=()=>true;navigator.share=async d=>{window.__dibagikan=d.files[0].type};}")
        # URL dokumen sebenarnya mengembalikan PDF tanpa menambah audit cetak.
        async with page.expect_response(lambda r:r.url.endswith('/cetak/80mm')) as resp:
            await page.locator('[data-pdf-digital-link]').first.click()
        response=await resp.value
        assert response.status==200 and response.headers['content-type']=='application/pdf'
        await page.wait_for_function("window.__dibagikan==='application/pdf'")
        await page.route('**/cetak/80mm',lambda r:r.fulfill(status=200,content_type='text/html',body='Halaman masuk sintetis'))
        await page.locator('[data-pdf-digital-link]').first.click()
        await page.locator('[data-hasil-unduh]').wait_for(state='visible')
        assert 'belum dapat dibuka' in await page.locator('[data-hasil-unduh]').text_content()
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        await page.unroute('**/cetak/80mm')
        await page.evaluate("window.TeraFlowPrinter.alamat=()=> 'http://127.0.0.1:9999'")
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid);t.jumlah_revisi+=1;await db.commit()
        async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).jumlah_revisi==1
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        await page.locator('[data-cp-jalankan]').click()
        await page.wait_for_function("document.querySelector('[data-cp-status]').textContent.includes('berubah')",timeout=5000)
        assert await page.locator('[data-cp-segar]').is_visible()
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await b.close()

@pytest.mark.parametrize('browser',['chromium','webkit'])
async def test_admin_menuntaskan_pekerjaan_shift_lama_tanpa_kirim_ulang(klien,alamat_ui,browser):
    from test_cetak_pratinjau import siapkan
    tid=await tiket();await login(klien,'budi');job,_=await siapkan(klien,tid)
    await klien.post(f'/timbangan/transaksi/{tid}/cetak/pekerjaan/'+job['kunci']+'/kirim',json={})
    await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,390,browser=browser)
        errors=[];prints=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.route('**/cgi-bin/epos/**',lambda r:prints.append(r.request.url))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}/cetak')
        await page.locator('[data-cetak-fisik]').evaluate('e=>e.open=true')
        assert await page.locator('[data-cp-jalankan]').is_disabled()
        await page.locator('[data-cp-ya]').click()
        assert 'Isi alasan' in await page.locator('[data-cp-status]').text_content()
        await page.locator('[name=alasan_penyelesaian]').fill('Shift sebelumnya berhenti mengirim; kedua lembar diperiksa')
        await page.locator('[data-cp-ya]').click()
        await page.wait_for_function("document.querySelector('.cp-history').textContent.includes('Cetak ke-1')")
        assert not prints and not errors
        async with database.SessionLocal() as db:
            assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==1
        await b.close()

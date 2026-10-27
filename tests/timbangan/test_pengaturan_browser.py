"""Pengaturan asli melalui browser, database uji terpisah, printer/jaringan tiruan."""
import os, asyncio
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login,_jadi_super,_master_tara_kemasan
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_pengaturan_kategori import produksi_terpisah
from app import database
from app.timbangan.models import TimbanganConfig,TimbanganTransaksi,TimbanganCetak
OUT=Path(os.environ.get('UJI_PENGATURAN_OUT', '/tmp/uji-pengaturan-teraflow'))

@pytest.mark.parametrize('width,theme,who',[(1440,'light','wahid'),(390,'dark','wahid'),(320,'light','budi'),(768,'dark','miftah')])
async def test_semua_kategori_navigasi_keyboard_tampilan(klien,app_uji,alamat_ui,width,theme,who):
    await _jadi_super(app_uji,'miftah');await _master_tara_kemasan();await login(klien,who)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,theme,browser=os.environ.get('UJI_BROWSER','chromium'))
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+'/timbangan/pengaturan')
        links=await page.locator('.set-kategori__baris').evaluate_all('(es)=>es.map(e=>e.href)')
        OUT.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(OUT/f'kategori-{width}-{theme}-{os.environ.get("UJI_BROWSER","chromium")}.png'),full_page=True)
        for url in links:
            await page.locator('.set-kategori__baris').filter(has=page.locator('strong')).first.focus()
            await page.goto(url);await page.locator('[data-pengaturan]').wait_for()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),url
            assert (await page.locator('.bawah__isi>a.aktif').inner_text()).strip()=='Pengaturan'
            assert await page.locator('.set-kembali').is_visible()
            assert await page.locator('a[href="/timbangan/tara"],form[action="/timbangan/tara"]').count()==0
            await page.screenshot(path=str(OUT/f'{url.split("bagian=")[1]}-{width}-{theme}-{os.environ.get("UJI_BROWSER","chromium")}.png'),full_page=True)
            await page.locator('.set-kembali').press('Enter');await page.locator('.set-kategori').wait_for()
        await page.goto(alamat_ui+'/timbangan/pengaturan?bagian=operasional')
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path=str(OUT/f'operasional-{width}-{theme}-{os.environ.get("UJI_BROWSER","chromium")}.png'),full_page=True)
        await page.goto(alamat_ui+'/timbangan/pengaturan?ok=UJI#tara-kemasan')
        await page.wait_for_url(lambda u:'bagian=aturan' in str(u));assert 'ok=UJI' in page.url
        assert await page.locator('#tara-kemasan').count()==(0 if who=='budi' else 1)
        assert not errors,errors
        await b.close()

async def test_printer_lokal_simpan_gagal_bawaan_periksa_tanpa_kertas(klien,alamat_ui):
    await login(klien)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,320,browser=os.environ.get('UJI_BROWSER','chromium'))
        await buka(page,alamat_ui+'/timbangan/printer?asal=cetak')
        calls=[]
        async def jaringan(r):
            calls.append((r.request.method,r.request.post_data or ''))
            return await r.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
        await page.route('https://printer.invalid/**',jaringan)
        await page.locator('[name=printer_url]').fill('https://printer.invalid/')
        await page.locator('[data-simpan-printer]').press('Enter')
        assert await page.evaluate("localStorage.getItem('timbangan-printer')")=='https://printer.invalid'
        assert 'belum diperiksa' in await page.locator('[data-hasil-cetak]').text_content()
        assert not calls
        await page.locator('[data-periksa-printer]').evaluate('(e)=>{e.click();e.click()}')
        await page.wait_for_function("document.querySelector('[data-periksa-printer]').dataset.sibuk!=='1'")
        assert calls and all('<text' not in body and '<cut' not in body and '<feed' not in body for _,body in calls)
        # Kegagalan penyimpanan lokal tidak kehilangan ketikan / mengaku berhasil.
        await page.evaluate("() => {window.__setItem=Storage.prototype.setItem;Storage.prototype.setItem=function(){throw new Error('UJI kuota')};}")
        await page.locator('[name=printer_url]').fill('https://baru.invalid')
        await page.locator('[data-simpan-printer]').click()
        assert 'menolak menyimpan' in await page.locator('[data-hasil-cetak]').text_content()
        assert await page.locator('[name=printer_url]').input_value()=='https://baru.invalid'
        await page.evaluate('() => {Storage.prototype.setItem=window.__setItem;}')
        await page.locator('[name=printer_url]').fill('');await page.locator('[data-simpan-printer]').click()
        assert await page.evaluate("localStorage.getItem('timbangan-printer')") is None
        assert await page.evaluate("window.TeraFlowPrinter.alamat()===(document.body.dataset.printer||'').replace(/\\/+$/,'')")
        await page.evaluate("document.body.dataset.printer=''")
        await page.locator('[data-periksa-printer]').click()
        await page.wait_for_function("document.querySelector('[data-laporan-printer]').textContent.includes('Belum disetel')")
        await page.locator('[name=printer_url]').fill('http://printer.invalid');await page.locator('[data-simpan-printer]').click()
        await page.locator('[data-periksa-printer]').click()
        await page.wait_for_function("document.querySelector('[data-laporan-printer]').textContent.includes('Harus https://')")
        async with database.SessionLocal() as db:
            for model in (TimbanganConfig,TimbanganTransaksi,TimbanganCetak):assert await db.scalar(select(func.count()).select_from(model))==0
        await b.close()

async def test_simpan_operasional_dan_tara_ui(klien,app_uji,alamat_ui):
    await _jadi_super(app_uji);await _master_tara_kemasan();await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,390,browser=os.environ.get('UJI_BROWSER','chromium'))
        await buka(page,alamat_ui+'/timbangan/pengaturan?bagian=operasional')
        f=page.locator('form').filter(has=page.locator('[name=kunci][value=kapasitas_jembatan_kg]')).filter(has=page.locator('[name=nilai]'))
        await f.locator('[name=nilai]').fill('25.000');await f.get_by_role('button',name='Simpan',exact=True).click()
        await page.wait_for_url(lambda u:'ok=' in str(u));assert 'kini 25.000 kg' in await page.locator('main').inner_text()
        await f.locator('[name=nilai]').fill('-1');await f.get_by_role('button',name='Simpan',exact=True).click()
        await page.wait_for_url(lambda u:'err=' in str(u));assert await f.locator('[name=nilai]').input_value()=='25000'
        await page.goto(alamat_ui+'/timbangan/pengaturan?bagian=aturan')
        tf=page.locator('#tara-kemasan form').first
        await tf.locator('[name=tara_per_karung_kg]').fill('0,0858');await tf.get_by_role('button',name='Simpan',exact=True).click()
        await page.wait_for_url(lambda u:'ok=' in str(u));assert '0,0858' in await page.locator('main').inner_text()
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await b.close()

async def test_uji_printer_sukses_gagal_tidak_pasti_tanpa_transaksi(klien,alamat_ui):
    await login(klien)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,390,browser=os.environ.get('UJI_BROWSER','chromium'))
        await buka(page,alamat_ui+'/timbangan/pengaturan?bagian=printer')
        await page.locator('[name=printer_url]').fill('https://printer.invalid');await page.locator('[data-simpan-printer]').click()
        calls=[];mode={'value':'success'}
        async def printer(r):
            calls.append(r.request.post_data);await asyncio.sleep(.15)
            if mode['value']=='unknown':return await r.abort()
            xml='<response success="true"/>' if mode['value']=='success' else '<response success="false" code="EPTR_COVER_OPEN"/>'
            return await r.fulfill(status=200,content_type='text/xml',body=xml)
        await page.route('https://printer.invalid/**',printer)
        for value,pesan in [('success','Struk keluar'),('failed','Penutup printer terbuka'),('unknown','belum dapat dipastikan')]:
            mode['value']=value;before=len(calls)
            await page.locator('[data-cetak]').evaluate('(e)=>{e.click();e.click()}')
            await page.wait_for_function("document.querySelector('[data-cetak]').dataset.sibuk!=='1'")
            text=await page.locator('[data-hasil-cetak]').text_content()
            assert pesan.lower() in text.lower(),text
            assert len(calls)==before+1
            assert 'perintah' not in page.url
        async with database.SessionLocal() as db:
            for model in (TimbanganTransaksi,TimbanganCetak,TimbanganConfig):assert await db.scalar(select(func.count()).select_from(model))==0
        # Context browser baru tidak membawa alamat printer browser sebelumnya.
        lain=await b.new_context();other=await lain.new_page();await other.goto(alamat_ui+'/timbangan/masuk')
        assert await other.evaluate("localStorage.getItem('timbangan-printer')") is None
        await lain.close();await b.close()

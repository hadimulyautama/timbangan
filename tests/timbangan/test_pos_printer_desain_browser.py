"""Desain printer dengan HTTP loopback, SQLite uji dan printer tiruan."""
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from test_web import app_uji,klien,login  # noqa: F401
from test_pengiriman_gabungan_browser import alamat_ui  # noqa: F401
from test_rincian_transfer_browser import browser_uji
OUT=Path(__file__).resolve().parents[3]/'gambar'

@pytest.mark.parametrize('width',[320,390,1440])
async def test_petunjuk_dirty_hasil_dan_cetak_tidak_pasti(klien,alamat_ui,width):
    await login(klien,'budi' if width==320 else 'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,'dark' if width==390 else 'light');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(alamat_ui+'/timbangan/printer?asal=cetak');await page.locator('[data-pos-printer][data-pp-ready]').wait_for();await page.locator('#pembuka').wait_for(state='hidden')
        calls=[];mode={'kind':'ok'}
        async def printer(route):
            req=route.request
            if '<text' not in (req.post_data or ''):
                return await route.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
            calls.append((req.method,req.post_data or ''))
            if req.method=='POST' and mode['kind']=='unknown':return await route.abort()
            body='<response success="true"/>' if mode['kind']=='ok' else '<response success="false" code="EPTR_COVER_OPEN"/>'
            await route.fulfill(status=200,content_type='text/xml',body=body)
        await page.route('https://printer.invalid/**',printer)
        storage=await page.evaluate("localStorage.getItem('timbangan-printer')")
        await page.get_by_role('button',name='Petunjuk',exact=True).click()
        assert await page.locator('#pp-petunjuk').evaluate('e=>e.open')
        text=await page.locator('[data-pp-help-content]').text_content();assert '48 kolom' in text and 'PDF' in text and 'Kode perangkat akun' in text
        await page.keyboard.press('Escape');assert await page.evaluate("localStorage.getItem('timbangan-printer')")==storage
        OUT.mkdir(parents=True,exist_ok=True);await page.screenshot(path=str(OUT/f'printer-{width}.png'),full_page=True)
        await page.locator('[name=printer_url]').fill('https://printer.invalid')
        assert await page.locator('[data-periksa-printer]').is_disabled()
        assert await page.locator('[data-cetak]').get_attribute('aria-disabled')=='true'
        await page.locator('[data-cetak]').evaluate('e=>e.click()');assert not calls
        await page.locator('[data-simpan-printer]').click();assert 'belum diperiksa' in await page.locator('[data-pp-summary]').inner_text()
        await page.locator('[data-periksa-printer]').click();await page.wait_for_function("document.querySelector('[data-pp-status]').textContent==='Sambungan berhasil'")
        assert all('<text' not in body and '<feed' not in body and '<cut' not in body for method,body in calls)
        assert 'Alamat disimpan' not in await page.locator('[data-pp-result]').inner_text()
        await page.locator('[data-pp-details]>summary').click();assert 'Layanan cetak' in await page.locator('[data-laporan-printer]').inner_text()
        mode['kind']='cover';await page.locator('[data-cetak]').click();await page.wait_for_function("document.querySelector('[data-pp-summary]').textContent.includes('Penutup printer terbuka')")
        mode['kind']='unknown';before=len(calls)
        await page.locator('[data-cetak]').evaluate('e=>{e.click();e.click()}')
        await page.wait_for_function("document.querySelector('[data-pp-status]').textContent==='Hasil cetak belum pasti'")
        assert len(calls)==before+1
        assert 'sebelum mengulang' in await page.locator('[data-pp-summary]').inner_text()
        assert not await page.locator('[name=printer_url]').evaluate('e=>e.readOnly')
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors;await b.close()

async def test_petunjuk_tanpa_javascript(klien,alamat_ui):
    await login(klien)
    async with async_playwright() as pw:
        b=await pw.chromium.launch();ctx=await b.new_context(viewport={'width':390,'height':950},java_script_enabled=False)
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()]);page=await ctx.new_page()
        await page.goto(alamat_ui+'/timbangan/pengaturan?bagian=printer')
        await page.locator('[data-pp-help-fallback]>summary').evaluate('e=>e.scrollIntoView({block:"center"})')
        await page.locator('[data-pp-help-fallback]>summary').click();assert await page.locator('[data-pp-help-content]').is_visible()
        assert 'Kode perangkat akun' in await page.locator('[data-pp-help-content]').text_content();await b.close()

async def test_kembali_dari_printer_diperiksa_otomatis_tanpa_membuang_ketikan(klien,alamat_ui):
    await login(klien)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await page.goto(alamat_ui+'/timbangan/printer')
        await page.locator('[data-pos-printer][data-pp-ready]').wait_for()
        await page.locator('#pembuka').wait_for(state='hidden')
        calls=[]
        async def status(r):
            calls.append(r.request.post_data)
            assert not any(k in r.request.post_data for k in ('<text','<feed','<cut'))
            await r.fulfill(content_type='text/xml',body='<response success="true"/>')
        await page.route('https://printer.invalid/**',status)
        await page.locator('[name=printer_url]').fill('https://printer.invalid')
        await page.locator('[data-simpan-printer]').click()
        await page.evaluate("window.dispatchEvent(new Event('online'))")
        await page.wait_for_function("document.querySelector('[data-pp-status]').textContent==='Sambungan berhasil'")
        assert len(calls)==1
        await page.evaluate("Object.defineProperty(document,'visibilityState',{value:'hidden',configurable:true});document.dispatchEvent(new Event('visibilitychange'));Object.defineProperty(document,'visibilityState',{value:'visible',configurable:true});document.dispatchEvent(new Event('visibilitychange'))")
        await page.wait_for_timeout(400)
        assert len(calls)==2
        await page.locator('[name=printer_url]').fill('https://alamat-baru.invalid')
        await page.evaluate("window.dispatchEvent(new Event('online'))")
        await page.wait_for_timeout(400)
        assert len(calls)==2
        assert await page.locator('[name=printer_url]').input_value()=='https://alamat-baru.invalid'
        assert await page.evaluate("localStorage.getItem('timbangan-printer')")=='https://printer.invalid'
        await b.close()

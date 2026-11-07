"""Buka/unduh desktop dan berbagi ponsel memakai PDF langsung tanpa pekerjaan cetak."""
import os
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_supplier import tiket
from test_cetak_pratinjau import siapkan
from test_pdf_digital import keadaan

@pytest.mark.parametrize('width,theme',[(1440,'light'),(390,'dark'),(320,'light')])
async def test_pdf_tanpa_alasan_setelah_cetak_dan_saat_pending(klien,alamat_ui,width,theme):
    tid=await tiket();await login(klien,'wahid');j,_=await siapkan(klien,tid)
    base=f'/timbangan/transaksi/{tid}/cetak'
    await klien.post(base+'/pekerjaan/'+j['kunci']+'/kirim',json={})
    await klien.post(base+'/pekerjaan/'+j['kunci']+'/hasil',json={'hasil':'printer_berhasil'})
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,theme)
        errors=[];posts=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        for pending in (False,True):
            if pending:await siapkan(klien,tid,alasan='Salinan fisik tertunda')
            before=await keadaan(tid)
            await buka(page,alamat_ui+base)
            assert await page.locator('[name=alasan]').input_value()==('Salinan fisik tertunda' if pending else '')
            links=page.locator('[data-pdf-digital-link]');assert await links.count()==2
            for i,fmt in enumerate(('80mm','ncr')):
                link=links.nth(i)
                assert await link.is_enabled()
                if width==1440:
                    async with ctx.expect_event('response', predicate=lambda r:r.url.endswith('/cetak/'+fmt)) as response:
                        await link.click()
                    r=await response.value
                    assert r.status==200 and r.headers['content-type']=='application/pdf'
                    for extra in ctx.pages:
                        if extra!=page:await extra.close()
                else:
                    await page.evaluate("() => {Object.defineProperty(navigator,'userAgent',{value:'iPhone',configurable:true});navigator.canShare=()=>true;navigator.share=async d=>{window.__dibagikan=d.files[0].type};window.__dibagikan=null;}")
                    async with page.expect_response(lambda r:r.url.endswith('/cetak/'+fmt)) as resp:await link.click()
                    assert (await resp.value).status==200
                    await page.wait_for_function("window.__dibagikan==='application/pdf'")
            assert await keadaan(tid)==before and not posts
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            if not pending:
                assert not await page.locator('[data-cetak-fisik]').evaluate('e=>e.open')
                await page.locator('[data-cetak-fisik]>summary').click()
                await page.locator('[data-cp-jalankan]').click()
                assert 'Isi alasan' in await page.locator('[data-cp-status]').text_content()
            if not pending:
                await page.locator('[data-cetak-fisik]>summary').click()
                assert await page.locator('.cp-preview').is_hidden()
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            out=Path(os.environ['UJI_PDF_OUT']);out.mkdir(parents=True,exist_ok=True)
            await page.screenshot(path=str(out/f'pdf-{width}-{pending}.png'),full_page=True)
        assert not errors
        await b.close()

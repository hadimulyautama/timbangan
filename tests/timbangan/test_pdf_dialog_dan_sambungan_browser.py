"""Kasus gagal, PDF banyak halaman, zoom dan hasil sambungan tanpa panduan."""
import io,os
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from reportlab.pdfgen import canvas
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_supplier import tiket
from test_pdf_digital import keadaan

@pytest.mark.parametrize('width',[1440,390,320])
async def test_pdf_gagal_retry_semua_halaman_zoom_dan_tutup(klien,alamat_ui,width):
    tid=await tiket();await login(klien,'wahid');before=await keadaan(tid)
    raw=io.BytesIO();doc=canvas.Canvas(raw,pagesize=(80*72/25.4,150*72/25.4))
    for i in range(1,4):doc.drawString(12,350,f'Isi lengkap halaman {i}');doc.showPage()
    doc.save();mode={'gagal':True}
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,'dark' if width==390 else 'light');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}');lokasi=page.url
        async def berkas(route):
            await route.fulfill(status=200,content_type='text/html' if mode['gagal'] else 'application/pdf',body='Sesi habis' if mode['gagal'] else raw.getvalue())
        await page.route('**/cetak/80mm*',berkas)
        await page.get_by_role('button',name='Lihat',exact=True).click()
        await page.get_by_role('button',name='Coba lagi',exact=True).wait_for(state='visible')
        assert page.url==lokasi and len(ctx.pages)==1
        mode['gagal']=False;await page.get_by_role('button',name='Coba lagi',exact=True).click()
        await page.wait_for_function("document.querySelector('[data-pdf-status]').textContent==='3 halaman'",timeout=15000)
        assert await page.locator('[data-pdf-selesai]').count()==3
        for i in range(1,4):assert f'Isi lengkap halaman {i}' in await page.locator('.tf-pdf-dialog').text_content()
        awal=await page.locator('.tf-pdf-page canvas').first.evaluate('e=>e.getBoundingClientRect().width')
        await page.get_by_role('button',name='Perbesar PDF').click()
        await page.wait_for_function("document.querySelector('[data-pdf-status]').textContent==='3 halaman'")
        assert await page.locator('.tf-pdf-page canvas').first.evaluate('e=>e.getBoundingClientRect().width')>awal
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        out=Path(os.environ['UJI_PDF_OUT']);out.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(out/f'pdf-dialog-{width}.png'),full_page=True)
        await page.keyboard.press('Escape')
        assert not await page.locator('.tf-pdf-dialog').evaluate('e=>e.open')
        assert await page.locator('.tf-pdf-page').count()==0
        assert await page.get_by_role('button',name='Lihat',exact=True).evaluate('e=>e===document.activeElement')
        assert await keadaan(tid)==before and page.url==lokasi and not errors
        await b.close()

@pytest.mark.parametrize('width',[1440,390])
async def test_periksa_langsung_tanpa_panduan(klien,alamat_ui,width):
    await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+'/timbangan/printer');await page.locator('[data-pos-printer][data-pp-ready]').wait_for()
        lokasi=page.url;mode={'gagal':True};calls=[]
        async def printer(route):
            calls.append(route.request.post_data or '')
            if mode['gagal']:return await route.abort()
            await route.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
        await page.route('https://printer.invalid/**',printer)
        await page.locator('[data-pp-edit]').click()
        await page.locator('[name=printer_url]').fill('https://printer.invalid');await page.locator('[data-simpan-printer]').click()
        await page.get_by_role('button',name='Periksa sambungan',exact=True).click()
        await page.wait_for_function("document.querySelector('[data-pp-summary]').textContent==='Printer belum dapat dihubungi.'")
        assert await page.locator('[data-pp-next]').is_visible()
        assert await page.locator('[data-pp-buka-alamat]').is_visible()
        assert await page.get_by_role('button',name='Buka Petunjuk',exact=True).count()==0
        assert not await page.locator('#pp-petunjuk').evaluate('e=>e.open')
        assert page.url==lokasi and len(ctx.pages)==1
        mode['gagal']=False;await page.get_by_role('button',name='Periksa sambungan',exact=True).click()
        await page.wait_for_function("document.querySelector('[data-pp-status]').textContent==='Sambungan berhasil'")
        assert not await page.locator('[data-pp-next]').is_visible()
        assert all('<text' not in c and '<feed' not in c and '<cut' not in c for c in calls)
        assert page.url==lokasi and len(ctx.pages)==1 and not errors
        await b.close()

"""Browser nyata, server lokal, dan database sintetis milik fixture test_web."""
import asyncio
from profil_browser import mesin, konteks
import os
import socket
from pathlib import Path
import pytest
import uvicorn
from playwright.async_api import async_playwright
from test_web import app_uji, klien, login  # noqa: F401

JALUR=['/timbang/'+k for k in ['GABAH_BASAH','GABAH_KERING','BERAS_PK','BERAS_MASUK','BROKEN_MASUK','PENGIRIMAN','TRANSFER','RETUR_PELANGGAN','RETUR_SUPPLIER','BEBAS']]+['/jasa/GABAH_KERING']

@pytest.fixture
async def lokal(app_uji,klien):
    await login(klien)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen()
    url=f'http://127.0.0.1:{sock.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(app_uji,log_level='error',lifespan='off'))
    task=asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(100):
        if server.started:break
        await asyncio.sleep(.02)
    assert server.started
    try:yield url,klien
    finally:
        server.should_exit=True
        await task

async def halaman(browser,url,klien,width=1440,js=True,pw=None):
    options=konteks(pw,width,1000) if pw else {'viewport':{'width':width,'height':1000}}
    context=await browser.new_context(**options,locale='id-ID',timezone_id='Asia/Jakarta',java_script_enabled=js,service_workers='block')
    await context.add_cookies([{'name':k,'value':v,'url':url} for k,v in klien.cookies.items()])
    await context.route('https://fonts.googleapis.com/**',lambda r:r.abort())
    await context.route('https://fonts.gstatic.com/**',lambda r:r.abort())
    page=await context.new_page()
    return context,page

async def test_desktop_ponsel_semua_jenis_dan_panduan(lokal):
    url,klien=lokal;errors=[]
    async with async_playwright() as pw:
        browser=await mesin(pw).launch()
        for width in [1440,390,320]:
            context,page=await halaman(browser,url,klien,width,pw=pw)
            page.on('pageerror',lambda e:errors.append(str(e)))
            for jalur in JALUR:
                await page.goto(url+'/timbangan'+jalur)
                await page.locator('[data-tp-guide]').wait_for(state='visible')
                assert await page.locator('.fw-form').count()==1
                assert not await page.locator('[data-tp-time]').evaluate('e=>e.open')
                before=await page.locator('.fw-form').evaluate('e=>Array.from(new FormData(e).entries())')
                await page.locator('[data-tp-guide]').click()
                guide=page.locator('#tp-panduan')
                assert await guide.evaluate('e=>e.open')
                assert 'Kapasitas jembatan' in await guide.inner_text()
                assert await guide.locator('[name]').count()==0
                assert before==await page.locator('.fw-form').evaluate('e=>Array.from(new FormData(e).entries())')
                await page.keyboard.press('Escape')
                assert await page.locator('[data-tp-guide]').evaluate('e=>e===document.activeElement')
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,jalur)
                assert await page.locator('.fw-form details:not([open]) [required]').count()==0
                if jalur=='/jasa/GABAH_KERING':assert 'titipan pelanggan' in await page.locator('.tp-context').inner_text()
                if jalur=='/timbang/GABAH_BASAH':
                    await page.locator('[data-tp-time] summary').click()
                    await page.locator('[name=waktu]').fill('2026-11-07T10:45')
                    assert '07/11/2026 10:45' in await page.locator('[data-tp-time-label]').inner_text()
                    await page.locator('[data-tp-time] summary').click()
                    await page.locator('[data-fw-opsional] summary').click()
                    await page.locator('[name=nomor_acuan]').fill('NOTA-DESAIN')
                    await page.locator('[data-fw-opsional] summary').click()
                    await page.locator('[name=berat_kg]').fill('15000')
                    await page.wait_for_timeout(800)
                    await page.reload();await page.wait_for_timeout(800)
                    assert await page.locator('[name=nomor_acuan]').input_value()=='NOTA-DESAIN'
                    assert await page.locator('[name=waktu]').input_value()=='2026-11-07T10:45'
                    assert '07/11/2026 10:45' in await page.locator('[data-tp-time-label]').inner_text()
                    out=os.environ.get('UJI_TP_OUT')
                    if out:
                        Path(out).mkdir(parents=True,exist_ok=True)
                        await page.screenshot(path=str(Path(out)/f'timbang-pertama-{width}.png'),full_page=True)
                    if width==390:
                        await page.locator('.pd-theme').click()
                        await page.locator('[data-tp-guide]').click()
                        if out:await page.screenshot(path=str(Path(out)/'panduan-gelap-390.png'),full_page=True)
                        await page.locator('[data-tp-guide-close]').click()
            await context.close()
        assert not errors,errors
        await browser.close()

async def test_simpan_dan_lanjut_timbang_kedua(lokal):
    url,klien=lokal
    async with async_playwright() as pw:
        browser=await mesin(pw).launch()
        context,page=await halaman(browser,url,klien,390,pw=pw)
        await page.goto(url+'/timbangan/timbang/GABAH_BASAH')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.locator('[name=berat_kg]').fill('15000')
        await page.locator('[name=supplier_id]').select_option('1')
        await page.locator('[name=nomor_polisi]').fill('W 1234 HM')
        await page.locator('[name=nama_sopir]').fill('Sopir Uji Desain')
        await page.locator('.fw-form button[type=submit]').click()
        await page.wait_for_url('**/timbangan/transaksi/*')
        assert 'Timbang pertama tersimpan.' in await page.locator('body').inner_text()
        await page.locator('a[href$="/tiket/1"]').first.click()
        await page.locator('.fw-form[data-fw-stage=second]').wait_for(state='visible')
        await context.close()
        await browser.close()

async def test_tanpa_js_semua_isian_dan_panduan_tetap_tersedia(lokal):
    url,klien=lokal
    async with async_playwright() as pw:
        browser=await mesin(pw).launch()
        context,page=await halaman(browser,url,klien,390,False,pw=pw)
        response=await page.goto(url+'/timbangan/timbang/GABAH_BASAH')
        assert await page.locator('.tp-page').count()==1,(response.status,page.url,await page.locator('body').inner_text())
        await page.locator('[data-tp-guide-fallback] summary').click()
        assert await page.locator('[data-tp-guide-content]').is_visible()
        await page.locator('[data-tp-time] summary').click()
        assert await page.locator('[name=waktu]').is_visible()
        assert await page.locator('.fw-form').get_attribute('data-simpan-luring') is not None
        assert await page.locator('.fw-form [name=kunci]').count()==1
        assert await page.locator('[data-tp-guide]').is_hidden()
        await context.close();await browser.close()

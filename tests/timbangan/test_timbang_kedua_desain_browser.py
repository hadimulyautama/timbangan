"""Desain kedua memakai form dan server asli dengan database fixture sintetis."""
from profil_browser import mesin, konteks
import os
from datetime import timedelta
from pathlib import Path
from playwright.async_api import async_playwright
from test_web import app_uji,klien  # noqa: F401
from test_timbang_pertama_desain_browser import lokal,halaman  # noqa: F401
from test_formulir import tiket_uji as tiket_awal,pasang_muatan
from app import database
from app.timbangan.models import TimbanganTransaksi

ALUR=[('MASUK','GABAH_BASAH'),('MASUK','GABAH_KERING'),('MASUK','BERAS_PK'),('KELUAR','PENGIRIMAN'),('TRANSFER','TRANSFER'),('RETUR_MASUK','RETUR_PELANGGAN'),('RETUR_KELUAR','RETUR_SUPPLIER'),('BEBAS','BEBAS')]

async def tiket_uji(arah,kode):
    tid=await tiket_awal(arah,kode)
    # Truk sudah selesai bongkar; jangan jadikan fixture detik ini lebih
    # baru dari input datetime-local yang memang hanya berpresisi menit.
    async with database.SessionLocal() as db:
        trx=await db.get(TimbanganTransaksi,tid)
        trx.timbang1_waktu-=timedelta(minutes=5)
        await db.commit()
    return tid

async def test_kedua_desktop_ponsel_seluruh_alur(lokal,monkeypatch):
    url,klien=lokal;await pasang_muatan(monkeypatch)
    tickets=[(arah,kode,await tiket_uji(arah,kode)) for arah,kode in ALUR]
    errors=[]
    async with async_playwright() as pw:
        browser=await mesin(pw).launch()
        for width in [1440,390,320]:
            context,page=await halaman(browser,url,klien,width,pw=pw)
            page.on('pageerror',lambda e:errors.append(str(e)))
            for arah,kode,tid in tickets:
                await page.goto(f'{url}/timbangan/tiket/{tid}')
                await page.locator('[data-tk-guide]').wait_for(state='visible')
                form=page.locator('.fw-form')
                assert await form.count()==1
                assert await page.locator('form').count()==3
                assert await page.locator('form form').count()==0
                before=await form.evaluate('e=>Array.from(new FormData(e).entries())')
                await page.locator('[data-tk-guide]').click()
                assert 'Tanggal transaksi' in await page.locator('#tk-panduan').inner_text()
                assert await page.locator('#tk-panduan [name]').count()==0
                assert before==await form.evaluate('e=>Array.from(new FormData(e).entries())')
                await page.keyboard.press('Escape')
                assert await page.locator('[data-tk-guide]').evaluate('e=>e===document.activeElement')
                assert not await page.locator('[data-tk-time]').evaluate('e=>e.open')
                if arah=='KELUAR':
                    assert 'UJI-KR' in await page.locator('.fw-main').inner_text()
                else:
                    await page.locator('[name=jumlah_karung]').fill('200')
                await page.locator('[name=berat_kg]').fill('12100' if arah=='KELUAR' else ('15000' if arah=='RETUR_KELUAR' else '5000'))
                await page.wait_for_function('document.querySelector("[data-fw-hasil] .fw-preview-row--total")')
                assert await page.locator('[data-fw-hasil] h2').inner_text()=='Hasil penimbangan'
                assert await page.locator('[data-fw-hasil]').evaluate('e=>e.querySelector("h2").nextElementSibling.classList.contains("fw-preview-row--total")')
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,kode)
                await page.locator('.tk-actions>summary').click()
                assert await page.get_by_role('link',name='Koreksi data tiket',exact=True).is_visible()
                assert await page.locator('.tk-actions form textarea[required]').count()==2
                assert await page.locator('.tk-actions form input[type=checkbox][required]').count()==1
                await page.locator('.tk-actions>summary').click()
                if kode=='GABAH_BASAH':
                    await page.locator('[data-tk-time]>summary').click()
                    await page.locator('[name=waktu]').fill('2026-11-07T11:25')
                    await page.locator('[data-tk-time]>summary').click()
                    await page.locator('[data-tk-document]>summary').click()
                    await page.locator('[name=nomor_acuan]').fill('NOTA-KEDUA-UJI')
                    await page.locator('[data-tk-document]>summary').click()
                    assert await page.locator('[data-tk-document-number]').inner_text()=='NOTA-KEDUA-UJI'
                    await page.wait_for_timeout(800);await page.reload();await page.wait_for_timeout(800)
                    assert await page.locator('[name=nomor_acuan]').input_value()=='NOTA-KEDUA-UJI'
                    assert await page.locator('[name=waktu]').input_value()=='2026-11-07T11:25'
                    assert '07/11/2026 11:25' in await page.locator('[data-tk-time-label]').inner_text()
                    await context.set_offline(True)
                    await page.wait_for_function('document.querySelector("[data-fw-hasil]").textContent.includes("jaringan")')
                    assert await page.locator('[name=berat_kg]').input_value()=='5000'
                    await context.set_offline(False)
                    await page.wait_for_function('document.querySelector("[data-fw-hasil] .fw-preview-row--total")')
                    out=os.environ.get('UJI_TK_OUT')
                    if out:
                        Path(out).mkdir(parents=True,exist_ok=True)
                        await page.screenshot(path=str(Path(out)/f'kedua-{width}.png'),full_page=True)
                    if width==390:
                        await page.locator('.pd-theme').click();await page.locator('[data-tk-guide]').click()
                        if out:await page.screenshot(path=str(Path(out)/'panduan-gelap.png'),full_page=True)
                        await page.locator('[data-tk-guide-close]').click()
            await context.close()
        assert not errors,errors
        await browser.close()

async def test_simpan_sementara_lalu_selesai(lokal):
    url,klien=lokal;tid=await tiket_uji('MASUK','GABAH_BASAH')
    async with async_playwright() as pw:
        browser=await mesin(pw).launch();context,page=await halaman(browser,url,klien,390,pw=pw)
        await page.goto(f'{url}/timbangan/tiket/{tid}')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.locator('[name=berat_kg]').fill('5000')
        await page.locator('button[value=sementara]').click()
        await page.wait_for_function('location.search.includes("ok=")')
        await page.locator('.pesan--ok').wait_for(state='visible')
        async with database.SessionLocal() as db:
            trx=await db.get(TimbanganTransaksi,tid)
            assert trx.status_tiket=='TERBUKA' and float(trx.timbang2_kg)==5000
        await page.goto(f'{url}/timbangan/tiket/{tid}')
        await page.locator('[name=jumlah_karung]').fill('200')
        await page.locator('button[value=selesai]').click()
        await page.wait_for_url('**/transaksi/*')
        async with database.SessionLocal() as db:
            assert (await db.get(TimbanganTransaksi,tid)).status_tiket=='SELESAI'
        await context.close();await browser.close()

async def test_cache_rilis_dan_kedua_formulir_luring(lokal):
    url,klien=lokal;tid=await tiket_uji('MASUK','GABAH_BASAH')
    async with async_playwright() as pw:
        browser=await mesin(pw).launch()
        context=await browser.new_context(**konteks(pw,390,900))
        await context.add_cookies([{'name':k,'value':v,'url':url} for k,v in klien.cookies.items()])
        await context.route('https://fonts.googleapis.com/**',lambda r:r.abort())
        await context.route('https://fonts.gstatic.com/**',lambda r:r.abort())
        page=await context.new_page()
        await page.goto(url+'/timbangan/timbang/GABAH_BASAH')
        await page.evaluate('navigator.serviceWorker.ready')
        await page.wait_for_function('navigator.serviceWorker.controller')
        await page.reload()
        await page.goto(f'{url}/timbangan/tiket/{tid}')
        cached=await page.evaluate('async()=>Array.from(await (await caches.open("timbangan-v"+document.documentElement.dataset.versi)).keys()).map(r=>new URL(r.url).pathname)')
        for name in ['panduan.css','timbang-pertama-desain.css','timbang-pertama-desain.js','timbang-kedua-desain.css','timbang-kedua-desain.js']:
            assert '/timbangan/static/'+name in cached
        await context.set_offline(True)
        await page.reload()
        await page.locator('[data-tk-guide]').click()
        assert await page.locator('#tk-panduan').evaluate('e=>e.open')
        await page.locator('[data-tk-guide-close]').click()
        await page.goto(url+'/timbangan/timbang/GABAH_BASAH')
        await page.locator('[data-tp-guide]').click()
        assert await page.locator('#tp-panduan').evaluate('e=>e.open')
        await context.close();await browser.close()

async def test_tanpa_js_dan_pesan_integrasi_tetap(lokal,monkeypatch):
    url,klien=lokal;await pasang_muatan(monkeypatch,gagal=True)
    tid=await tiket_uji('KELUAR','PENGIRIMAN')
    async with async_playwright() as pw:
        browser=await mesin(pw).launch();context,page=await halaman(browser,url,klien,390,False,pw=pw)
        await page.goto(f'{url}/timbangan/tiket/{tid}')
        assert 'Gangguan sintetis Produksi' in await page.locator('.fw-main').inner_text()
        await page.locator('[data-tk-guide-fallback]>summary').click()
        assert await page.locator('[data-tk-guide-content]').is_visible()
        await page.locator('.tk-actions>summary').click()
        await page.locator('.tk-actions details').last.locator('summary').click()
        assert await page.locator('[name=tanpa_timbang_keluar]').is_visible()
        assert await page.locator('[name=tanpa_timbang_keluar]').get_attribute('required') is not None
        await context.close();await browser.close()

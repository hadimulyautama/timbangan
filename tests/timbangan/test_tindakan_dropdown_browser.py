"""Dropdown bersama, formulir asli dan izin; SQLite sintetis, tanpa data produksi."""
import os
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_retur import tautkan
from test_koreksi_antarmuka import tiket as dasar
from hmu_identitas import peran as P
from app import database
from app.timbangan.models import TimbanganTransaksi

async def buat(jenis):
    if jenis=='keluar':
        from test_rincian_keluar import buat_tiket
        return await buat_tiket()
    if jenis=='transfer':
        from test_rincian_transfer import master,tiket
        await master();return await tiket()
    if jenis=='retur':
        from test_rincian_retur import tiket
        return await tiket()
    if jenis=='supplier':
        from test_rincian_supplier import tiket
        return await tiket()
    return await dasar(kode='BEBAS',arah='BEBAS') if jenis=='bebas' else await dasar()

@pytest.mark.parametrize('jenis',['masuk','keluar','transfer','retur','supplier','bebas'])
@pytest.mark.parametrize('width',[1440,390,320])
async def test_dropdown_semua_detail_dan_form_asli(klien,alamat_ui,jenis,width):
    tid=await buat(jenis);await tautkan('wahid',P.SUPERADMIN);await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,'dark' if width==390 else 'light');errors=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}?kembali=/timbangan/transaksi%3Fhal=2');lokasi=page.url
        source=await klien.get(f'/timbangan/transaksi/{tid}');assert source.status_code==200
        dropdown=page.locator('[data-tindakan-dropdown]');await dropdown.wait_for(state='visible')
        guide=page.locator('[data-rd-guide]')
        if await guide.count():assert await guide.evaluate('e=>e.nextElementSibling.matches("[data-tindakan-dropdown]")')
        await dropdown.locator('[data-tindakan-trigger]').click()
        menu=page.locator('[data-tindakan-menu]');await menu.get_by_role('button',name='Batalkan transaksi',exact=True).wait_for(state='visible')
        assert await menu.get_by_role('link',name='Koreksi',exact=True).count()==1
        assert await menu.get_by_role('button',name='Hapus permanen',exact=True).count()==1
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        out=Path(os.environ['UJI_TINDAKAN_OUT']);out.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(out/f'dropdown-{jenis}-{width}.png'),full_page=True)
        await menu.get_by_role('button',name='Batalkan transaksi',exact=True).click()
        dialog=page.locator('.tf-actions-dialog');await dialog.wait_for(state='visible')
        assert page.url==lokasi
        form=dialog.locator('form[action$="/batal"]');assert await form.is_visible()
        assert not await dialog.locator('form[action$="/hapus"]').is_visible()
        assert await form.locator('[name=alasan]').get_attribute('required') is not None
        await form.locator('[name=alasan]').fill('Alasan tetap setelah kegagalan')
        async def gagal(route):
            if route.request.method=='POST':posts.append(route.request.post_data);return await route.abort()
            return await route.continue_()
        await page.route('**/batal',gagal)
        await form.locator('button[type=submit]').click()
        await form.locator('[role=alert]').wait_for(state='visible')
        assert len(posts)==1 and await form.locator('[name=alasan]').input_value()=='Alasan tetap setelah kegagalan'
        assert page.url==lokasi
        await page.get_by_role('button',name='Tutup tindakan').click()
        assert await dropdown.locator('[data-tindakan-trigger]').evaluate('e=>e===document.activeElement')
        await dropdown.locator('[data-tindakan-trigger]').click();await menu.get_by_role('button',name='Hapus permanen',exact=True).click()
        hapus=dialog.locator('form[action$="/hapus"]');assert await hapus.is_visible()
        assert await hapus.locator('[name=ketik_kode]').get_attribute('required') is not None
        assert await hapus.locator('[name=alasan]').get_attribute('required') is not None
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        out=Path(os.environ['UJI_TINDAKAN_OUT']);out.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(out/f'tindakan-{jenis}-{width}.png'),full_page=True)
        await page.keyboard.press('Escape')
        await dropdown.locator('[data-tindakan-trigger]').click();await page.keyboard.press('Escape')
        assert not await dropdown.evaluate("e=>e.dataset.terbuka==='true'") and not errors
        async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).status_transaksi=='AKTIF'
        await b.close()

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN])
async def test_hak_akses_dan_pembatalan_asli(klien,alamat_ui,role):
    tid=await dasar();await tautkan('miftah',role);await login(klien,'miftah')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}');dropdown=page.locator('[data-tindakan-dropdown]');await dropdown.wait_for(state='visible')
        await dropdown.locator('[data-tindakan-trigger]').click();menu=page.locator('[data-tindakan-menu]')
        assert await menu.get_by_role('button',name='Hapus permanen',exact=True).count()==0
        if await menu.get_by_role('button',name='Batalkan transaksi',exact=True).count():
            await menu.get_by_role('button',name='Batalkan transaksi',exact=True).click()
            await page.locator('.tf-actions-dialog form[action$="/batal"] [name=alasan]').fill('Pembatalan uji dropdown')
            await page.locator('.tf-actions-dialog form[action$="/batal"] button[type=submit]').click()
            await page.wait_for_url(lambda u:'ok=' in str(u))
            async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).status_transaksi=='VOID'
        await b.close()

async def test_hapus_tetap_memerlukan_kode_dan_berhasil_setelah_konfirmasi(klien,alamat_ui):
    tid=await dasar(kode='BEBAS',arah='BEBAS');await tautkan('wahid',P.SUPERADMIN);await login(klien,'wahid')
    async with database.SessionLocal() as db:kode=(await db.get(TimbanganTransaksi,tid)).kode
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
        await page.locator('[data-tindakan-trigger]').click()
        await page.locator('[data-tindakan-menu]').get_by_role('button',name='Hapus permanen',exact=True).click()
        form=page.locator('.tf-actions-dialog form[action$="/hapus"]')
        await form.locator('[name=alasan]').fill('Penghapusan data uji sementara')
        await form.locator('[name=ketik_kode]').fill('KODE SALAH');await form.locator('button[type=submit]').click()
        await form.locator('[role=alert]').wait_for(state='visible')
        async with database.SessionLocal() as db:assert await db.get(TimbanganTransaksi,tid) is not None
        await form.locator('[name=ketik_kode]').fill(kode);await form.locator('button[type=submit]').click()
        await page.wait_for_url('**/transaksi?ok=**')
        async with database.SessionLocal() as db:assert await db.get(TimbanganTransaksi,tid) is None
        await b.close()

async def test_tindakan_fallback_tanpa_js(klien,alamat_ui):
    tid=await dasar();await login(klien,'wahid')
    async with async_playwright() as pw:
        b=await pw.chromium.launch();ctx=await b.new_context(viewport={'width':320,'height':900},java_script_enabled=False)
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()]);page=await ctx.new_page()
        await page.goto(alamat_ui+f'/timbangan/transaksi/{tid}')
        assert not await page.locator('[data-tindakan-dropdown]').is_visible()
        await page.locator('[data-rd-actions-fallback]>summary').click()
        assert await page.locator('[data-tindakan-sumber]').get_by_role('link',name='Koreksi',exact=True).is_visible()
        await b.close()

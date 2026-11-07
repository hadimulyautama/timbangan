"""Audit seluruh dropdown pada data sintetis, desktop dan perangkat sentuh."""
import os,asyncio,json
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_koreksi_antarmuka import tiket as dasar
from test_rincian_retur import tautkan
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganTransaksi,TimbanganAkun,TimbanganAudit
from hmu_identitas import peran as P
JENIS=['gabah_basah','gabah_kering','pk','beras','broken','jasa','sekali','partai','keluar','transfer','retur_pelanggan','retur_supplier','bebas']
async def buat(jenis):
    if jenis=='keluar':
        from test_rincian_keluar import buat_tiket
        return await buat_tiket()
    if jenis=='transfer':
        from test_rincian_transfer import master,tiket
        await master();return await tiket()
    if jenis=='retur_pelanggan':
        from test_rincian_retur import tiket
        return await tiket()
    if jenis=='retur_supplier':
        from test_rincian_supplier import tiket
        return await tiket()
    if jenis=='bebas':return await dasar(arah='BEBAS',kode='BEBAS')
    if jenis=='jasa':return await dasar(jasa=True,kode='GABAH_KERING')
    if jenis=='sekali':return await dasar(cara='SEKALI')
    if jenis=='partai':
        tid=await dasar(cara='PARTAI')
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid);a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
            await service.selesaikan_partai(db,akun=a,kode=t.kode,jumlah_karung=3)
        return tid
    return await dasar(kode={'gabah_basah':'GABAH_BASAH','gabah_kering':'GABAH_KERING','pk':'BERAS_PK','beras':'BERAS_MASUK','broken':'BROKEN_MASUK'}[jenis])


@pytest.mark.parametrize('width',[1440,390])
async def test_menu_bisa_ditutup_semua_cara(klien,alamat_ui,width):
    tid=await buat('gabah_basah');await login(klien,'wahid')
    async with async_playwright() as pw:
        if width==390:
            b=await pw.chromium.launch();ctx=await b.new_context(viewport={'width':390,'height':920},is_mobile=True,has_touch=True,service_workers='block')
            await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()]);page=await ctx.new_page()
            async def lokal(route):
                url=urlsplit(route.request.url)
                if url.hostname!='127.0.0.1':return await route.abort()
                if url.path.endswith('/aliran'):return await route.fulfill(status=204,body='')
                return await route.continue_()
            await page.route('**/*',lokal)
        else:b,ctx,page=await browser_uji(pw,klien,alamat_ui,width)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}');lokasi=page.url
        menu=page.locator('[data-tindakan-dropdown]');trigger=menu.locator('summary')
        tekan=trigger.tap if width==390 else trigger.click
        for _ in range(3):
            await tekan();assert await menu.evaluate('e=>e.open')
            await tekan();assert not await menu.evaluate('e=>e.open')
        await trigger.click();await page.locator('h1').first.click();assert not await menu.evaluate('e=>e.open')
        await trigger.click();await page.evaluate('document.activeElement.blur()');await page.keyboard.press('Escape');assert not await menu.evaluate('e=>e.open')
        # Klik pada komponen yang menghentikan bubbling tetap harus menutup.
        await page.evaluate("() => {let e=document.createElement('button');e.id='uji-luar';e.textContent='Komponen luar';e.style='position:fixed;bottom:150px;right:15px;z-index:9999';e.addEventListener('click',x=>x.stopPropagation());document.body.append(e)}")
        await trigger.click();await page.locator('#uji-luar').click();assert not await menu.evaluate('e=>e.open')
        if width==390:
            await page.evaluate("document.querySelector('[data-tindakan-dropdown]>summary').dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}))")
            assert await menu.evaluate('e=>e.open')
            await page.locator('#uji-luar').dispatch_event('pointerdown',{'pointerType':'touch','bubbles':True})
            assert not await menu.evaluate('e=>e.open')
        assert page.url==lokasi
        await b.close()

@pytest.mark.parametrize('jenis',JENIS)
@pytest.mark.parametrize('width',[1440,390])
@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_seluruh_pilihan_dan_hak_akses(klien,alamat_ui,jenis,width,role):
    tid=await buat(jenis);siapa='budi' if role==P.OPERATOR else 'wahid'
    await tautkan(siapa,role);await login(klien,siapa)
    async with database.SessionLocal() as db:
        trx=await db.get(TimbanganTransaksi,tid);kode=trx.kode;berat=trx.berat_barang_kg
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,'dark' if width==390 else 'light');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
        dropdown=page.locator('[data-tindakan-dropdown]');await dropdown.wait_for(state='visible');await dropdown.locator('summary').click()
        menu=page.locator('[data-tindakan-menu]')
        assert await menu.get_by_role('link',name='Koreksi',exact=True).count()==1
        assert await menu.get_by_role('button',name='Batalkan transaksi',exact=True).count()==int(role!=P.OPERATOR)
        assert await menu.get_by_role('button',name='Hapus permanen',exact=True).count()==int(role==P.SUPERADMIN)
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        # Semua hak dicek pula pada endpoint, termasuk bila URL diminta langsung.
        if role!=P.SUPERADMIN:
            r=await klien.post(f'/timbangan/transaksi/{tid}/hapus',data={'alasan':'Dilarang untuk peran ini','ketik_kode':kode})
            async with database.SessionLocal() as db:assert await db.get(TimbanganTransaksi,tid) is not None
            assert 'dihapus permanen.' not in r.url.params.get('ok','')
        if role==P.OPERATOR:
            await klien.post(f'/timbangan/transaksi/{tid}/batal',data={'alasan':'Pembatalan riwayat oleh petugas harus ditolak'})
            async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).status_transaksi=='AKTIF'
        # Koreksi dipilih dari dropdown dan benar-benar disimpan melalui UI asli.
        await menu.get_by_role('link',name='Koreksi',exact=True).click()
        await page.locator('[data-correction-form]').wait_for(state='visible')
        await page.locator('[name=nama_sopir]').fill('Sopir Hasil Audit')
        await page.locator('[data-correction-form] [name=alasan]').fill('Uji pilihan Koreksi dari dropdown')
        await page.wait_for_function("document.querySelector('[data-cf-hasil]').textContent.includes('Sopir Hasil Audit')")
        await page.locator('[data-correction-form] button[type=submit]').click()
        await page.wait_for_url('**/transaksi/*?ok=**')
        async with database.SessionLocal() as db:
            trx=await db.get(TimbanganTransaksi,tid);assert trx.nama_sopir=='Sopir Hasil Audit' and trx.berat_barang_kg==berat
        # Admin membatalkan; Super Admin menjalankan penghapusan dengan kode wajib.
        await page.locator('[data-tindakan-dropdown]>summary').click()
        if role==P.ADMIN:
            await page.locator('[data-tindakan-menu]').get_by_role('button',name='Batalkan transaksi',exact=True).click()
            form=page.locator('.tf-actions-dialog form[action$="/batal"]')
            await form.locator('[name=alasan]').fill('Pembatalan data audit sementara')
            await form.locator('button[type=submit]').click();await page.wait_for_url('**?ok=**')
            await page.wait_for_function("!document.querySelector('.tf-actions-dialog')?.open")
            async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).status_transaksi=='VOID'
        elif role==P.SUPERADMIN:
            await page.locator('[data-tindakan-menu]').get_by_role('button',name='Hapus permanen',exact=True).click()
            form=page.locator('.tf-actions-dialog form[action$="/hapus"]')
            await form.locator('[name=alasan]').fill('Penghapusan data audit sementara')
            await form.locator('[name=ketik_kode]').fill(kode)
            await form.locator('button[type=submit]').click();await page.wait_for_url('**/transaksi?ok=**')
            async with database.SessionLocal() as db:assert await db.get(TimbanganTransaksi,tid) is None
        else:
            await page.keyboard.press('Escape');assert not await page.locator('[data-tindakan-dropdown]').evaluate('e=>e.open')
        assert not errors,errors
        out=Path(os.environ['UJI_AUDIT_OUT']);out.mkdir(parents=True,exist_ok=True)
        (out/f'{jenis}-{width}-{role}.json').write_text(json.dumps(dict(jenis=jenis,width=width,role=role,koreksi=True,pembatalan_diizinkan=role!=P.OPERATOR,hapus_diizinkan=role==P.SUPERADMIN,galat=errors),indent=2))
        await b.close()

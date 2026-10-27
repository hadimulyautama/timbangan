"""Alasan sebelum printer, balasan gagal, dan penguncian sampai audit selesai."""
import asyncio
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer import master,tiket
from test_rincian_retur import tautkan
from test_rincian_transfer_browser import browser_uji,buka
from app import database
from app.timbangan.models import TimbanganCetak,TimbanganTransaksi
from hmu_identitas import peran as P

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_alasan_sebelum_kertas_dan_audit_setelah_printer(klien,alamat_ui,role):
    await master();tid=await tiket();who='miftah' if role==P.OPERATOR else 'wahid'
    await tautkan(who,role);await login(klien,who)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}/cetak')
        await page.evaluate("localStorage.setItem('timbangan-printer','http://127.0.0.1:9999')")
        jobs=[];status={'gagal':False}
        async def printer(r):
            jobs.append(r.request.post_data)
            await asyncio.sleep(.1)
            return await r.fulfill(status=200,content_type='text/xml',body='<response success="false" code="EPTR_COVER_OPEN"/>' if status['gagal'] else '<response success="true"/>')
        await page.route('**/cgi-bin/epos/**',printer)
        await page.locator('[data-cp-jalankan]').evaluate('(a)=>{a.click();a.click()}')
        await page.wait_for_function("document.querySelector('.cp-history').textContent.includes('Cetak ke-1')");assert len(jobs)==1
        # Tanpa alasan/sekadar spasi tidak boleh mengirim permintaan printer.
        alasan=page.locator('[name=alasan]')
        for nilai in ['', '   ']:
            await alasan.fill(nilai);await page.locator('[data-cp-jalankan]').click()
            assert await page.evaluate("document.activeElement?.name==='alasan'")
            await asyncio.sleep(.15)
            assert len(jobs)==1,'Kertas dapat terkirim sebelum alasan diperiksa'
        await alasan.fill('Uji cetak ulang beralasan')
        status['gagal']=True;await page.locator('[data-cp-jalankan]').click()
        await page.wait_for_function("document.querySelector('[data-cp-status]').textContent.includes('Penutup printer terbuka')")
        assert await alasan.input_value()=='Uji cetak ulang beralasan'
        assert not await alasan.get_attribute('readonly')
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==1
        status['gagal']=False
        async with page.expect_navigation(wait_until='domcontentloaded'):
            await page.locator('[data-cp-jalankan]').evaluate('(a)=>{a.click();a.click()}')
        assert len(jobs)==3
        async with database.SessionLocal() as db:
            rows=(await db.scalars(select(TimbanganCetak).order_by(TimbanganCetak.urutan))).all()
            assert len(rows)==2 and rows[1].alasan=='Uji cetak ulang beralasan'
            assert (await db.get(TimbanganTransaksi,tid)).berat_barang_kg==3989.42
        await b.close()

async def test_tombol_tetap_terkunci_sampai_pencatatan_cetak_selesai(klien,alamat_ui):
    await master();tid=await tiket();await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}/cetak')
        await page.evaluate("localStorage.setItem('timbangan-printer','http://127.0.0.1:9999')")
        jobs=[];audit=[]
        async def printer(r):jobs.append(1);await r.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
        async def catat(r):
            if r.request.method=='POST':
                audit.append(1);await asyncio.sleep(.6)
            await r.continue_()
        await page.route('**/cgi-bin/epos/**',printer);await page.route(f'**/transaksi/{tid}/cetak/pekerjaan/*/hasil',catat)
        # Pemeriksaan berjalan di halaman lama selama respons POST audit
        # ditunda. Locator Playwright akan menunggu navigasi selesai.
        await page.evaluate("""() => {
            const timer=setInterval(() => {
                const a=document.querySelector('[data-cp-jalankan]');
                if (!document.querySelector('[data-cp-status]').textContent.includes('Menyimpan riwayat')) return;
                clearInterval(timer);
                sessionStorage.setItem('uji-kunci-audit',a.disabled ? '1' : '');
                a.click();a.click();
            },20);
        }""")
        await page.locator('[data-cp-jalankan]').click()
        await page.wait_for_function("document.querySelector('.cp-history').textContent.includes('Cetak ke-1')")
        assert await page.evaluate("sessionStorage.getItem('uji-kunci-audit')")=='1'
        assert len(jobs)==len(audit)==1
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==1
        await b.close()

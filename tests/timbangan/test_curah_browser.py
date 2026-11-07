"""Operator menyelesaikan curah dari ponsel, termasuk antrean saat offline."""
import os,asyncio
from copy import deepcopy
import pytest
from playwright.async_api import async_playwright
from test_web import app_uji,klien,login
from test_formulir import tiket_uji
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_retur import tautkan
from test_integrasi_curah import curah
from app import database
from app.timbangan import klien_produksi
from app.timbangan.models import TimbanganTransaksi
from hmu_identitas import peran as P

@pytest.mark.parametrize('browser',['chromium','webkit'])
async def test_operator_menyimpan_curah_offline_tanpa_karung_rekaan(klien,alamat_ui,monkeypatch,browser):
    tid=await tiket_uji('KELUAR','PENGIRIMAN')
    await tautkan('miftah',P.OPERATOR);await login(klien,'miftah')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);p=curah();p['nomor_polisi']=t.nomor_polisi
    calls=[]
    async def baca(*a,**k):return deepcopy(p)
    async def selesai(*a,**k):calls.append(a);return {'selesai':True,'kode_perintah':'OUT-UJI'}
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',baca)
    monkeypatch.setattr(klien_produksi,'selesaikan_pengiriman',selesai)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,320,'dark',browser=browser)
        await buka(page,alamat_ui+f'/timbangan/tiket/{tid}')
        await page.wait_for_function('window.timbanganLuring?.siap()')
        assert await page.locator('[name=jumlah_karung]').count()==0
        assert await page.locator('[name=waktu]').evaluate('e=>e.value && e.checkValidity()')
        await page.locator('[name=berat_kg]').fill('9000')
        await page.wait_for_function("document.querySelector('[data-fw-hasil]').textContent.includes('4.000')")
        await ctx.set_offline(True)
        await page.locator('[name=aksi][value=selesai]').click()
        for _ in range(100):
            rows=await page.evaluate('window.timbanganLuring.antrean()')
            if len(rows)==1:break
            await asyncio.sleep(.1)
        assert len(rows)==1 and await page.locator('[name=berat_kg]').input_value()=='9000'
        await ctx.set_offline(False);await page.evaluate('window.timbanganLuring.sinkronkan()')
        for _ in range(150):
            rows=await page.evaluate('window.timbanganLuring.antrean()')
            if rows[0]['status']=='terkirim':break
            await asyncio.sleep(.1)
        assert rows[0]['status']=='terkirim',rows
        await page.evaluate('window.timbanganLuring.sinkronkan()')
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid)
            assert t.selesai and t.jumlah_karung==0 and float(t.berat_barang_kg)==4000
        assert len(calls)==1
        await b.close()

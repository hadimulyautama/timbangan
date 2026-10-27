"""Panel referensi memakai UI asli, data sintetis, dan pembaca PF simulasi."""
from pathlib import Path
import os
import pytest
from playwright.async_api import async_playwright
from test_web import app_uji, klien, login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_supplier import tiket,sumber
from test_rincian_retur import tautkan
from hmu_identitas import peran as P

OUT=Path(os.environ.get('UJI_BUKTI_RS','/private/tmp/tf-retur-supplier-bukti'))

@pytest.mark.parametrize('width,theme,role',[(320,'light',P.OPERATOR),(390,'dark',P.ADMIN),(1440,'light',P.SUPERADMIN)])
async def test_referensi_responsif_keyboard_tanpa_mutasi(klien,alamat_ui,monkeypatch,width,theme,role):
    tid=await tiket();await tautkan('miftah',role);d,calls=await sumber(monkeypatch,tid)
    p=d['pengajuan'];p['supplier']='Supplier sintetis '+('Nama panjang '*12)
    p['items'][0]['nama']='PRODUK'+('PANJANG'*30)
    p['items'][0]['kunci_sumber']='pk:'+('12345'*30)
    p['catatan']='<script>alert("uji")</script> Catatan aman'
    await login(klien,'miftah');OUT.mkdir(exist_ok=True,parents=True)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,theme)
        writes=[];errors=[]
        page.on('request',lambda r:writes.append(r.url) if r.method!='GET' else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}?kembali=/timbangan/transaksi%3Fhal=2')
        panel=page.locator('[data-retur-supplier]');assert await panel.count()==1
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        item=panel.locator('details').first
        await item.locator('summary').focus();await page.keyboard.press('Enter')
        assert await item.get_attribute('open') is None
        await page.keyboard.press('Enter');assert await item.get_attribute('open') is not None
        assert await panel.locator('a[href$="/retur-supplier/99"]').count()==1
        assert await panel.locator('a[href$="/barang-masuk/800"]').count()==1
        assert '<script>alert' in await panel.inner_text()
        await page.screenshot(path=str(OUT/f'panel-{width}-{theme}-{role}.png'),full_page=True)
        await page.reload();assert await panel.count()==1
        await page.get_by_role('link',name='Cetak bukti timbang').click()
        assert '/cetak' in page.url and not writes and not errors
        await b.close()

async def test_ganti_akun_tidak_membawa_rincian_akun_lain(klien,alamat_ui,monkeypatch):
    tid=await tiket();await tautkan('wahid');d,calls=await sumber(monkeypatch,tid);await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
        assert 'RS-UJI-99' in await page.locator('[data-retur-supplier]').inner_text()
        # Akun lama tanpa relasi tidak boleh menerima salinan hasil akun admin.
        await login(klien,'budi');await ctx.clear_cookies()
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()])
        await page.reload()
        assert 'RS-UJI-99' not in await page.locator('[data-retur-supplier]').inner_text()
        assert 'dibatasi oleh izin akun' in await page.locator('[data-retur-supplier]').inner_text()
        assert len(calls)==1
        await b.close()

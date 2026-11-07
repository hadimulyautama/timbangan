"""Menu tertutup benar-benar hilang; tanpa native details pada kontrol utama."""
import os
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_rincian_retur import tautkan
from test_tindakan_dropdown_browser import buat
from hmu_identitas import peran as P

@pytest.mark.parametrize('width',[1440,393,320])
@pytest.mark.parametrize('jenis',['masuk','keluar','transfer','retur','supplier','bebas'])
async def test_menu_tidak_terlihat_setelah_ditutup(klien,alamat_ui,width,jenis):
    tid=await buat(jenis);await tautkan('wahid',P.SUPERADMIN);await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,'light');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
        group=page.locator('[data-tindakan-dropdown]');trigger=group.locator('[data-tindakan-trigger]');menu=group.locator('[data-tindakan-menu]')
        assert await group.evaluate("e=>e.tagName==='DIV'")
        for cara in ['tombol','luar','escape']:
            await trigger.click();assert await menu.is_visible()
            posisi=await page.evaluate("() => {const t=document.querySelector('[data-tindakan-trigger]').getBoundingClientRect(),m=document.querySelector('[data-tindakan-menu]').getBoundingClientRect();return {jarak:m.top-t.bottom,kiri:m.left,kanan:m.right}}")
            assert 0<=posisi['jarak']<=10 and posisi['kiri']>=0 and posisi['kanan']<=width
            if cara=='tombol':await trigger.click()
            elif cara=='luar':await page.mouse.click(2,200)
            else:await page.keyboard.press('Escape')
            await page.wait_for_function("document.querySelector('[data-tindakan-trigger]').getAttribute('aria-expanded')==='false'")
            assert not await menu.is_visible()
            assert await menu.evaluate("e=>e.hidden&&e.style.display==='none'&&getComputedStyle(e).display==='none'&&e.getClientRects().length===0")
            assert await page.get_by_role('button',name='Hapus permanen',exact=True).count()==0
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        out=Path(os.environ['UJI_MENU_OUT']);out.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(out/f'tertutup-{jenis}-{width}.png'),full_page=True)
        assert not errors
        await b.close()

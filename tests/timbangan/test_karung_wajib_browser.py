"""Validasi jumlah karung pada formulir asli, termasuk tanpa jaringan."""
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright,expect
from test_web import app_uji,klien,login  # noqa: F401
from test_formulir import tiket_uji

OUT=Path(__file__).parents[3]/'output/jumlah-karung-wajib-20261025'

@pytest.mark.parametrize('width',[390,1440])
async def test_wajib_kedua_pesan_bilangan_bulat_dan_mode_sekali(klien,width):
    tid=await tiket_uji('TRANSFER','TRANSFER');await login(klien)
    OUT.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context(viewport={'width':width,'height':950},service_workers='block',reduced_motion='reduce')
        page=await context.new_page();errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
        async def layani(route):
            req=route.request;u=urlsplit(req.url)
            if u.hostname!='uji':return await route.abort()
            r=await klien.request(req.method,u.path+('?' +u.query if u.query else ''),content=req.post_data_buffer,headers={k:v for k,v in req.headers.items() if k.lower() in ['content-type','x-timbangan-kiriman','x-timbangan-akun','x-timbangan-waktu','x-timbangan-luring']})
            await route.fulfill(status=r.status_code,headers={'content-type':r.headers.get('content-type','text/html')},body=r.content)
        await page.route('**/*',layani)
        await page.goto(f'http://uji/timbangan/tiket/{tid}')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.locator('#pembuka').wait_for(state='detached')
        karung=page.locator('[name="jumlah_karung"]')
        await expect(karung).to_have_attribute('required','')
        await context.set_offline(True)
        await page.locator('[name="berat_kg"]').fill('5000')
        for nilai in ['', '0','-1','1,5','abc','100001']:
            await karung.fill(nilai)
            assert not await karung.evaluate('e=>e.checkValidity()'),nilai
        await expect(page.get_by_role('button',name='Simpan sementara',exact=True)).to_have_attribute('formnovalidate','')
        await karung.fill('123')
        assert await karung.evaluate('e=>e.checkValidity()')
        await page.screenshot(path=str(OUT/f'wajib-karung-{width}.png'),full_page=True)
        await context.set_offline(False)
        await page.goto('http://uji/timbangan/timbang/BEBAS')
        karung=page.locator('[name="jumlah_karung"]')
        assert not await karung.evaluate('e=>e.required')
        await page.locator('[name="cara_timbang"][value="SEKALI"]').check()
        assert await karung.evaluate('e=>e.required')
        assert not await karung.evaluate('e=>e.checkValidity()')
        await karung.fill('2');assert await karung.evaluate('e=>e.checkValidity()')
        assert not errors
        await browser.close()

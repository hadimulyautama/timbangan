"""Perilaku layar/keyboard tetap sama sesudah pengurangan pembacaan."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import pytest
from test_web import app_uji, klien, login, _jadi_super
from test_rekap_baca import isi_lembar

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('UJI_BROWSER_CARI')!='1', reason='Browser fixture eksplisit')]

@pytest.mark.parametrize('role', ['admin', 'superadmin', 'operator'])
@pytest.mark.parametrize('width', [1440, 390, 320])
async def test_rekap_semantik_layar_keyboard(klien, app_uji, role, width):
    from playwright.async_api import async_playwright, expect
    await isi_lembar(50)
    if role == 'superadmin':
        await _jadi_super(app_uji)
    await login(klien, 'budi' if role == 'operator' else 'wahid')
    errors = []
    requests = []
    steps = ['buka-rekap']
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        # Sesuai catatan app.css: transisi lintas dokumen headless dapat
        # terlewati. Gunakan preferensi aksesibilitas asli, bukan sembunyikan galat.
        page = await browser.new_page(viewport={'width':width,'height':950}, service_workers='block', reduced_motion='reduce')
        await page.context.add_cookies([dict(name=k.name,value=k.value,url='http://uji') for k in klien.cookies.jar])
        await page.add_init_script('window.print=()=>{throw Error("Physical print forbidden")};window.EventSource=undefined;')
        page.on('pageerror', lambda e: errors.append(str(e)))
        async def route(r):
            u = urlsplit(r.request.url)
            if u.netloc != 'uji' or r.request.method != 'GET' or r.request.resource_type == 'eventsource':
                return await r.abort()
            if u.path == '/timbangan/keadaan':
                return await r.fulfill(status=200,content_type='application/json',body='{"n":"fixture-stable"}')
            res = await klien.get(u.path+('?' +u.query if u.query else ''))
            if u.path == '/timbangan/laporan':
                requests.append(dict(query=u.query,status=res.status_code,bytes=len(res.content)))
            await r.fulfill(status=res.status_code,body=res.content,headers={k:v for k,v in res.headers.items() if k.lower() not in ('content-length','content-encoding')})
        await page.route('**/*',route)
        try:
            r = await page.goto('http://uji/timbangan/laporan')
            if role == 'operator':
                assert r.status == 403
                await expect(page.locator('[data-ringkasan]')).to_have_count(0)
            else:
                await expect(page.locator('b[aria-label="54 terbuka"]')).to_have_text('54')
                await expect(page.locator('[data-ringkasan="jumlah"] strong')).to_have_text('13')
                await expect(page.locator('[data-ringkasan="masuk"] strong')).to_contain_text('1,25')
                await expect(page.locator('[data-ringkasan="keluar"] strong')).to_contain_text('0,8')
                assert await page.locator('[data-laporan-id]').count() == 4
                link = page.locator('.lp-tabs a').filter(has_text='Pemeriksaan')
                await link.focus(); await page.keyboard.press('Enter')
                steps.append('keyboard-buka-pemeriksaan')
                await expect(page.locator('[data-laporan-id]')).to_have_count(54)
                assert 'tab=pemeriksaan' in page.url
                link = page.locator('.lp-tabs a').filter(has_text='Rekap')
                await link.focus(); await page.keyboard.press('Enter')
                steps.append('keyboard-kembali-rekap')
                await expect(page.locator('[data-ringkasan="jumlah"] strong')).to_have_text('13')
                if not await page.locator('input[name=dari]').is_visible():
                    await page.locator('[data-lr-period] summary').focus()
                    await page.keyboard.press('Enter')
                    steps.append('keyboard-buka-filter-periode')
                await page.locator('input[name=dari]').fill('1999-01-01')
                await page.locator('input[name=sampai]').fill('1999-01-02')
                steps.append('isi-dua-tanggal')
                button = page.get_by_role('button', name='Terapkan periode')
                await button.focus(); await page.keyboard.press('Enter')
                steps.append('keyboard-terapkan-periode')
                await expect(page.locator('[data-ringkasan="jumlah"] strong')).to_have_text('0')
                await expect(page.locator('b[aria-label="54 terbuka"]')).to_have_text('54')
                csv = page.locator('[data-unduh]').first
                q = parse_qs(urlsplit(await csv.get_attribute('href')).query)
                assert q == {'dari':['1999-01-01'],'sampai':['1999-01-02']}
                await csv.focus(); await expect(csv).to_be_focused()
                assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth'), 'Overflow'
            assert not errors
            result = dict(role=role,width=width,requests=requests,errors=errors,steps=steps,status='passed')
            out = Path(os.environ['BUKTI_CARI'])
            label='baseline' if os.getenv('BASELINE_CARI')=='1' else 'candidate'
            (out/f'{label}-browser-rekap-{role}-{width}.json').write_text(json.dumps(result,indent=2)+'\n')
            await page.screenshot(path=str(out/f'{label}-browser-rekap-{role}-{width}.png'))
        finally:
            await page.unroute_all(behavior='ignoreErrors')
            await browser.close()

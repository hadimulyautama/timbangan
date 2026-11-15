"""Uji operator asli melalui browser, seluruh HTTP masuk fixture ASGI."""
import json,os
from contextvars import ContextVar
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from test_web import app_uji,klien,login
from data_cari_lama import arsip
from app.timbangan.db import hari_ini
from app.timbangan.web import PREFIX
from test_riwayat import ids

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_CARI')!='1',reason='Browser lokal opsional')]


@pytest.mark.parametrize('width',[1440,390,320])
@pytest.mark.parametrize('peran',['operator','admin','superadmin'])
async def test_langkah_mencari_arsip_dan_kembali(klien,width,peran):
    from playwright.async_api import async_playwright, expect
    await arsip(peran);await login(klien,'fixture-'+peran)
    baseline=os.getenv('BASELINE_CARI')=='1'
    out=Path(os.environ['BUKTI_CARI']);requests=[];errors=[]
    active=ContextVar('request_sql',default=None)
    def sql(*args):
        current=active.get()
        if current is not None:current.append(1)
    event.listen(Engine,'before_cursor_execute',sql)
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            page=await browser.new_page(viewport=dict(width=width,height=950),service_workers='block',reduced_motion='reduce')
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.context.add_cookies([dict(name=k.name,value=k.value,url='http://uji') for k in klien.cookies.jar])
            async def route(r):
                req=r.request;u=urlsplit(req.url)
                if u.netloc!='uji' or req.method!='GET' or req.resource_type=='eventsource':return await r.abort()
                queries=[];token=active.set(queries)
                try:response=await klien.get(u.path+('?' +u.query if u.query else ''))
                finally:active.reset(token)
                if u.path==PREFIX+'/transaksi':requests.append(dict(url=req.url,status=response.status_code,queries=len(queries),rendered=len(ids(response.text)),bytes=len(response.content)))
                await r.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding')})
            await page.route('**/*',route)
            try:
                await page.goto('http://uji'+PREFIX+'/transaksi')
                await page.get_by_role('searchbox',name='Cari tiket').fill('ARSIP')
                await page.get_by_role('button',name='Cari',exact=True).click()
                await expect(page.locator('.tf-empty')).to_contain_text('Tidak ada transaksi yang cocok')
                assert not await page.locator('#rh-filters').evaluate('e=>e.open')
                steps=[]
                if baseline:
                    assert await page.locator('[data-rh-cari-lama]').count()==0
                    await page.locator('[data-rh-filter]').click();steps.append('Buka Filter')
                    await page.get_by_label('Dari',exact=True).fill(str(hari_ini()-timedelta(days=378)));steps.append('Isi Dari lebih lama')
                    await page.get_by_role('button',name='Terapkan filter',exact=True).click();steps.append('Terapkan filter')
                else:
                    assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    await page.screenshot(path=str(out/f'after-empty-{peran}-{width}.png'))
                    link=page.locator('[data-rh-cari-lama]')
                    await expect(link).to_have_text('Cari 1 tahun sebelumnya')
                    await link.focus();await page.keyboard.press('Enter');steps.append('Enter pada Cari 1 tahun sebelumnya')
                await expect(page.locator('.rh-item')).to_have_count(50)
                await expect(page.locator('.tf-section-title h2')).to_contain_text('80 transaksi')
                assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
                saved=page.url
                if not baseline:
                    await page.go_back()
                    await expect(page.locator('.tf-empty')).to_contain_text('Tidak ada transaksi yang cocok')
                    assert parse_qs(urlsplit(page.url).query)['dari']==[str(hari_ini()-timedelta(days=13))]
                    await page.go_forward()
                    await expect(page.locator('.rh-item')).to_have_count(50)
                await page.locator('.rh-open').first.click()
                await page.locator('.dk-kembali').wait_for()
                back=await page.locator('.dk-kembali').get_attribute('href')
                assert {k:v for k,v in parse_qs(urlsplit(back).query).items() if k!='hal'}=={k:v for k,v in parse_qs(urlsplit(saved).query).items() if k!='hal'}
                await page.locator('.dk-kembali').click()
                await expect(page).to_have_url('http://uji'+back)
                saved=page.url
                await page.locator('a[rel="next"]').click()
                await expect(page.locator('.rh-item')).to_have_count(30)
                await page.go_back()
                await expect(page.locator('.rh-item')).to_have_count(50)
                assert page.url==saved
                await page.screenshot(path=str(out/f'{"baseline" if baseline else "after"}-arsip-{peran}-{width}.png'))
                assert not errors,errors
                (out/f'{"baseline" if baseline else "after"}-browser-{peran}-{width}.json').write_text(json.dumps(dict(width=width,steps_after_empty=steps,requests=requests,errors=errors),indent=2)+'\n')
            finally:await browser.close()
    finally:event.remove(Engine,'before_cursor_execute',sql)

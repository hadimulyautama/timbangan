"""Kembali dari detail tiket mandiri: filter/halaman dan posisi yang sama."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from contextvars import ContextVar
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from test_web import app_uji,klien,login
from data_tiket_mandiri import isi

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_CARI')!='1',reason='Browser fixture opsional')]

@pytest.mark.parametrize('width',[1440,390,320])
@pytest.mark.parametrize('peran',['operator','admin','superadmin'])
async def test_kembali_detail_ke_tiket_asal(klien,width,peran):
    from playwright.async_api import async_playwright,expect
    await isi(peran);await login(klien,'fixture-'+peran)
    baseline=os.getenv('BASELINE_CARI')=='1';out=Path(os.environ['BUKTI_CARI']);requests=[];errors=[]
    current=ContextVar('sql_request',default=None)
    def sql(*a):
        q=current.get()
        if q is not None:q.append(1)
    event.listen(Engine,'before_cursor_execute',sql)
    try:
      async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        page=await browser.new_page(viewport=dict(width=width,height=950),service_workers='block',reduced_motion='reduce')
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.context.add_cookies([dict(name=k.name,value=k.value,url='http://uji') for k in klien.cookies.jar])
        await page.add_init_script('window.print=()=>{throw Error("Physical print forbidden in fixture")};window.EventSource=undefined;')
        async def route(r):
            req=r.request;u=urlsplit(req.url)
            if u.netloc!='uji' or req.method!='GET' or req.resource_type=='eventsource':return await r.abort()
            if u.path=='/timbangan/keadaan':return await r.fulfill(status=200,content_type='application/json',body='{"n":"fixture-stable"}')
            queries=[];token=current.set(queries)
            try:res=await klien.get(u.path+('?' +u.query if u.query else ''))
            finally:current.reset(token)
            if u.path.startswith('/timbangan/transaksi'):requests.append(dict(path=u.path,query=u.query,status=res.status_code,queries=len(queries),bytes=len(res.content)))
            await r.fulfill(status=res.status_code,body=res.content,headers={k:v for k,v in res.headers.items() if k.lower() not in ('content-length','content-encoding')})
        await page.route('**/*',route)
        try:
            await page.goto('http://uji/timbangan/transaksi?cari=UJB&arah=BEBAS')
            await page.locator('a[rel=next]').click()
            await expect(page.locator('.rh-item')).to_have_count(50)
            await page.wait_for_function('new URLSearchParams(location.search).get("hal")==="2"')
            origin=page.url;await expect(page.locator('[data-riwayat-id="35"]')).to_have_count(1);target=page.locator('[data-riwayat-id="35"] .rh-open')
            await target.focus();await page.keyboard.press('Enter')
            back=page.locator('.dk-kembali');await back.wait_for(state='visible')
            await back.focus();await page.keyboard.press('Enter')
            await expect(page.locator('.rh-item')).to_have_count(50)
            returned=page.url;await page.wait_for_timeout(100)
            (out/f'debug-{peran}-{width}.json').write_text(json.dumps(dict(origin=origin,returned=returned,rows=await page.locator('.rh-item').evaluate_all('es=>es.map(e=>e.dataset.riwayatId)'),requests=requests),indent=2)+'\n')
            rect=await target.bounding_box(timeout=1000);in_view=bool(rect and 60<=rect['y']<900)
            focused=await target.evaluate('e=>document.activeElement===e');recovery=0
            if baseline:
                await page.mouse.move(width//2,500)
                while not in_view and recovery<30:
                    await page.mouse.wheel(0,700);await page.wait_for_timeout(60);recovery+=1
                    box=await target.bounding_box();in_view=bool(box and 60<=box['y']<900)
            result=dict(width=width,peran=peran,origin=origin,returned=returned,position_on_return=rect,focused_on_return=focused,recovery_scrolls_700px=recovery,requests=requests,errors=errors)
            (out/f'{"before" if baseline else "after"}-kembali-{peran}-{width}.json').write_text(json.dumps(result,indent=2)+'\n')
            assert parse_qs(urlsplit(origin).query)==parse_qs(urlsplit(returned).query)
            assert not baseline or (rect and 60<=rect['y']<900),result
            await expect(target).to_be_focused();await expect(target).to_be_in_viewport()
            saved=page.url;await page.go_back();await expect(page.locator('.dk-kembali')).to_be_visible()
            await page.go_forward();await expect(page).to_have_url(saved);await expect(target).to_be_in_viewport()
            await page.reload();await expect(target).to_be_focused();await expect(page).to_have_url(saved)
            await page.screenshot(path=str(out/f'after-kembali-{peran}-{width}.png'))
            assert not errors,errors
        finally:
            await page.unroute_all(behavior='ignoreErrors');await browser.close()
    finally:event.remove(Engine,'before_cursor_execute',sql)

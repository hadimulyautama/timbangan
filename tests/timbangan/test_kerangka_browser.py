"""Umpan balik lokal muncul selama dokumen native masih ditahan jaringan."""
import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright,expect
from test_web import app_uji,klien,login

BASE='http://127.0.0.1:59995'

@pytest.mark.parametrize('width',[390,1440])
async def test_kerangka_tampil_sebelum_data(klien,width):
    await asyncio.wait_for(jalankan(klien,width),45)

async def jalankan(klien,width):
    await login(klien,'wahid')
    gate=asyncio.Event();started=asyncio.Event();writes=[]
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        ctx=await browser.new_context(viewport={'width':width,'height':840},service_workers='block')
        await ctx.add_init_script("sessionStorage.setItem('pembuka','1')")
        await ctx.add_cookies([{'name':x.name,'value':x.value,'url':BASE} for x in klien.cookies.jar])
        async def app(route):
            req=route.request;u=urlsplit(req.url)
            if not req.url.startswith(BASE+'/'):await route.abort();return
            if req.method!='GET':writes.append(u.path);await route.abort();return
            # Kanal penanda memakai SQL PostgreSQL; fixture halaman ini SQLite.
            # Hanya denyut latar yang ditahan, halaman tetap dirender aplikasi.
            if u.path=='/timbangan/keadaan':await route.fulfill(json={'n':'uji','versi':'100'});return
            if u.path=='/timbangan/aliran':await route.fulfill(status=204,body='');return
            if u.path=='/timbangan/transaksi':started.set();await asyncio.wait_for(gate.wait(),12)
            response=await klien.get(u.path+('?' + u.query if u.query else ''))
            await route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','transfer-encoding')},body=response.content)
        await ctx.route('**/*',app)
        page=await ctx.new_page();errors=[];states=[]
        page.on('console',lambda m:states.append(json.loads(m.text[12:])) if m.text.startswith('KERANGKA_UI:') else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(BASE+'/timbangan/')
        await page.evaluate("""() => {document.addEventListener('click',()=>{window.clickAt=performance.now()},true);new MutationObserver(()=>{if(document.querySelector('.tf-kerangka') && !window.shellMs)requestAnimationFrame(()=>{window.shellMs=performance.now()-window.clickAt;console.debug('KERANGKA_UI:'+JSON.stringify({ms:window.shellMs,shell:!!document.querySelector('.tf-kerangka'),mainHidden:getComputedStyle(document.querySelector('main.isi')).display==='none'}))})}).observe(document.body,{childList:true,subtree:true});}""")
        if width<900:await page.locator('.pd-menu').click()
        cdp=await ctx.new_cdp_session(page)
        await page.locator('#menu-timbang a[href="/timbangan/transaksi"]').click(no_wait_after=True)
        await asyncio.wait_for(started.wait(),5)
        # Locator Playwright menunggu navigasi native selesai. CDP membaca
        # dokumen yang masih terlihat saat respons tujuan sengaja ditahan.
        await asyncio.sleep(2)
        assert states, 'Kerangka belum sempat digambar sebelum navigasi'
        state=states[-1];assert state['shell'] and state['mainHidden'],state
        elapsed=state.get('ms');assert elapsed is not None and elapsed<500,state
        out=Path(os.environ.get('UJI_KERANGKA_OUT','output/kerangka'));out.mkdir(parents=True,exist_ok=True)
        shot=await asyncio.wait_for(cdp.send('Page.captureScreenshot',{'format':'png'}),5)
        (out/('teraflow-'+str(width)+'.png')).write_bytes(base64.b64decode(shot['data']))
        gate.set()
        await page.wait_for_url(BASE+'/timbangan/transaksi')
        await expect(page.locator('main.isi')).to_be_visible()
        assert not writes,writes
        assert not errors,errors
        (out/('teraflow-'+str(width)+'.json')).write_text(json.dumps({'shell_ms':elapsed,'held_response_ms':2000,'width':width,'native_navigation':True,'errors':errors,'writes':writes})+'\n')
        await page.go_back()
        await expect(page.locator('main.isi')).to_be_visible()
        await expect(page.locator('.tf-kerangka')).to_have_count(0)
        await ctx.close();await browser.close()

"""Sidebar dan detail pada browser sentuh, dengan respons tujuan diperlambat."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright,expect
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_keluar import buat_tiket
from app.timbangan.web import VERSI

@pytest.mark.parametrize('engine',os.environ.get('UJI_PONSEL_ENGINES','chromium').split(','))
@pytest.mark.parametrize('width',[320,390])
async def test_sidebar_detail_sekali_sentuh(klien,alamat_ui,engine,width):
    tid=await buat_tiket();await login(klien,'wahid')
    daftar='/timbangan/transaksi';detail=f'/timbangan/transaksi/{tid}'
    gates={p:asyncio.Event() for p in (daftar,detail)};started={p:asyncio.Event() for p in gates}
    async with async_playwright() as pw:
        browser=await getattr(pw,engine).launch()
        ctx=await browser.new_context(viewport={'width':width,'height':844},is_mobile=True,has_touch=True,device_scale_factor=2,service_workers='block',reduced_motion='reduce')
        await ctx.add_cookies([{'name':x.name,'value':x.value,'url':alamat_ui} for x in klien.cookies.jar])
        await ctx.add_init_script("""sessionStorage.setItem('pembuka','1');document.addEventListener('click',e=>{let a=e.target.closest('a[href]');if(a){window.lastTap=performance.now();console.debug('PONSEL_TAP:'+a.pathname)}},true);new MutationObserver(()=>{if(document.querySelector('.tf-kerangka')&&!window.measured){window.measured=true;requestAnimationFrame(()=>console.debug('PONSEL_FRAME:'+JSON.stringify({ms:performance.now()-window.lastTap,shown:getComputedStyle(document.querySelector('main.isi')).display==='none'})))}}).observe(document,{childList:true,subtree:true});""")
        writes=[];errors=[];frames=[];taps=[];refresh=[False]
        async def route_app(route):
            req=route.request;u=urlsplit(req.url)
            if not req.url.startswith(alamat_ui+'/'):return await route.abort()
            if req.method!='GET':writes.append(u.path);return await route.abort()
            if u.path.endswith('/aliran'):return await route.fulfill(status=204,body='')
            if u.path.endswith('/keadaan'):return await route.fulfill(json={'n':'uji','versi':VERSI,'jumlah_tiket':0})
            if refresh[0] and not req.is_navigation_request() and u.path==daftar:
                response=await route.fetch();started[daftar].set()
                try:await asyncio.wait_for(gates[daftar].wait(),15)
                except TimeoutError:return await route.abort()
                body=(await response.body()).replace(b'</main>',b'<p data-uji-pembaruan>Data terbaru uji</p></main>')
                return await route.fulfill(response=response,body=body)
            if req.is_navigation_request() and u.path in gates:
                started[u.path].set()
                try:await asyncio.wait_for(gates[u.path].wait(),15)
                except TimeoutError:return await route.abort()
            await route.continue_()
        await ctx.route('**/*',route_app)
        page=await ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        def console(m):
            if m.text.startswith('PONSEL_TAP:'):taps.append(m.text[len('PONSEL_TAP:'):])
            if m.text.startswith('PONSEL_FRAME:'):frames.append(json.loads(m.text[len('PONSEL_FRAME:'):]))
        page.on('console',console)
        try:
            await page.goto(alamat_ui+'/timbangan/')
            await page.locator('.pd-menu').tap()
            await page.locator('#menu-timbang a[href="'+daftar+'"]').tap(no_wait_after=True)
            await asyncio.wait_for(started[daftar].wait(),5)
            await asyncio.sleep(2)
            assert frames and frames[-1]['shown'] and frames[-1]['ms']<500,frames
            gates[daftar].set();await page.wait_for_url(alamat_ui+daftar)
            # Menu harus tetap dapat dibuka dan ditutup sekali setelah data tiba.
            await page.locator('.pd-menu').tap()
            await expect(page.locator('#menu-timbang')).to_be_in_viewport(ratio=.5)
            await page.locator('.pd-close').tap()
            # Pembaruan otomatis tidak boleh membuang filter yang mulai diketik
            # setelah permintaan dikirim, atau memindahkan posisi baca.
            await page.wait_for_function('!window.timbanganLuring || !timbanganLuring.adaTertunda()')
            gates[daftar].clear();started[daftar].clear();refresh[0]=True
            await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            await asyncio.wait_for(started[daftar].wait(),5)
            field=page.locator('main input[type=search]').first
            await field.fill('ketikan belum dikirim')
            await field.evaluate('(el)=>window.inputAsli=el')
            top=await page.locator('main').evaluate('(el)=>{el.scrollTop=40;return el.scrollTop}')
            await asyncio.sleep(2);gates[daftar].set();await asyncio.sleep(.4)
            await expect(field).to_have_value('ketikan belum dikirim')
            assert await page.evaluate('window.inputAsli.isConnected')
            assert await page.locator('main').evaluate('(el)=>el.scrollTop')==top
            await field.fill('');await field.evaluate('(el)=>el.blur()')
            link=page.locator('main a[href^="'+detail+'"]').first
            href=await link.get_attribute('href')
            await link.tap(no_wait_after=True)
            await asyncio.wait_for(started[detail].wait(),5)
            await asyncio.sleep(2)
            assert len(frames)==2 and frames[-1]['shown'] and frames[-1]['ms']<500,frames
            gates[detail].set();await page.wait_for_url(alamat_ui+href)
            navigasi_taps=list(taps)
            await page.locator('[data-dk-tab="perhitungan"]').tap()
            await expect(page.locator('#dk-perhitungan')).to_be_visible()
            assert navigasi_taps.count(daftar)==navigasi_taps.count(detail)==1,navigasi_taps
            assert not errors,errors
            assert not writes,writes
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            out=Path(os.environ.get('UJI_PONSEL_OUT','output/ponsel'));out.mkdir(parents=True,exist_ok=True)
            name=f'teraflow-{engine}-{width}'
            await page.screenshot(path=str(out/(name+'.png')))
            (out/(name+'.json')).write_text(json.dumps({'engine':engine,'width':width,'touch':True,'sidebar_taps':navigasi_taps.count(daftar),'detail_taps':navigasi_taps.count(detail),'data_delay_ms':2000,'input_preserved':True,'scroll_preserved':True,'shell_frames':frames,'errors':errors,'writes':writes})+'\n')
            await page.go_back();await expect(page).to_have_url(alamat_ui+daftar)
            await expect(page.locator('main.isi')).to_be_visible()
        finally:
            for gate in gates.values():gate.set()
            await ctx.close();await browser.close()

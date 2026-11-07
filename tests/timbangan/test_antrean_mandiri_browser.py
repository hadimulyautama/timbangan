import asyncio
import os
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('mesin',['chromium','webkit'])
@pytest.mark.parametrize('a,b,terkirim',[
    ('/timbang/GABAH_KERING','/timbang/GABAH_KERING',1),
    ('/tiket/1/timbang2','/tiket/1/timbang2',0),
    ('/tiket/1/timbang2','/tiket/2/timbang2',1),
    ('/partai/1/tambah','/partai/1/tutup',0),
    ('/partai/1/tambah','/partai/2/tambah',1),
])
async def test_antrean_mandiri_tetapi_urutan_tiket_sama_dipertahankan(mesin,a,b,terkirim):
    async with async_playwright() as p:
        opts={'executable_path':os.environ['UJI_WEBKIT_PATH']} if mesin=='webkit' and os.environ.get('UJI_WEBKIT_PATH') else {}
        browser=await getattr(p,mesin).launch(**opts);ctx=await browser.new_context(service_workers='block');page=await ctx.new_page();posts=[]
        async def route(r):
            if r.request.url.endswith('/kiriman/sesi'):return await r.fulfill(json={'akun_id':1})
            if r.request.method=='POST':
                posts.append(r.request.url)
                key=r.request.headers.get('x-timbangan-kiriman')
                return await r.fulfill(json={'tersimpan':True,'kunci':key,'tujuan':'/timbangan/transaksi/2'})
            await r.fulfill(content_type='text/html',body='<html><body data-akun-id="1"><main></main></body></html>')
        await page.route('**/*',route);await page.goto('https://audit.invalid/timbangan/')
        await page.add_script_tag(path=str(ROOT/'app/timbangan/static/luring.js'))
        await page.wait_for_function('window.timbanganLuring?.siap()');await page.wait_for_timeout(150)
        await page.evaluate('''async([a,b])=>{
          const db=await new Promise((ok,no)=>{const r=indexedDB.open('timbangan-luring-v2');r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});
          await new Promise((ok,no)=>{const tx=db.transaction('kiriman','readwrite');const s=tx.objectStore('kiriman');
            s.put({kunci:crypto.randomUUID(),akun:'1',jalur:'/timbangan'+a,status:'periksa',created:1,label:'Truk A — perlu koreksi',data:[],lease:0});
            const key=crypto.randomUUID();s.put({kunci:key,akun:'1',jalur:'/timbangan'+b,status:'menunggu',created:2,label:'Truk B — lengkap',waktu:new Date().toISOString(),data:[['kunci',key],['berat_kg','15000']],lease:0});
            tx.oncomplete=ok;tx.onerror=()=>no(tx.error)});db.close();await window.timbanganLuring.sinkronkan();
        }''',[a,b])
        rows=await page.evaluate('window.timbanganLuring.antrean()')
        await browser.close()
        assert len(posts)==terkirim, f'Urutan antrean salah: {[(x["label"],x["status"]) for x in rows]}'

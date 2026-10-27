"""Rincian sumber per pelanggan pada UI asli; browser hanya ke ASGI uji."""
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
import io
import asyncio
import socket
import uvicorn
import pytest_asyncio
import pytest
from playwright.async_api import async_playwright
from pypdf import PdfReader
from sqlalchemy import select
from test_web import app_uji,klien,login
from test_pengiriman_gabungan import payload
from app import database
from app.timbangan import service,klien_produksi,pdf,epos,logic,pengiriman
from app.timbangan.models import TimbanganAkun

OUT=Path(__file__).resolve().parents[3]/'output/teraflow-kiriman-gabungan-20261026'

@pytest_asyncio.fixture
async def alamat_ui(app_uji):
    # HTTP nyata agar browser mengikuti redirect fetch, termasuk POST koreksi.
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0)); sock.listen(128); sock.setblocking(False)
    server = uvicorn.Server(uvicorn.Config(app_uji, log_level='error', lifespan='off'))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(.01)
    try:
        yield f'http://127.0.0.1:{sock.getsockname()[1]}'
    finally:
        server.should_exit = True
        await task
        sock.close()

@pytest.mark.parametrize('width,theme',[(320,'light'),(390,'dark'),(1440,'light')])
async def test_ui_kelompok_cetak_dan_koreksi(klien,monkeypatch,width,theme,alamat_ui):
    OUT.mkdir(parents=True,exist_ok=True)
    p=payload()
    async def baca(tid):return p
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',baca)
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(kunci=str(uuid4()),arah='KELUAR',jenis_kode='PENGIRIMAN',berat_kg=5000,nomor_polisi='B 1234 UJ',nama_sopir='Sopir Sintetis'))
        tid=t.id
    await login(klien)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx=await browser.new_context(viewport={'width':width,'height':920},service_workers='block',reduced_motion='reduce',color_scheme=theme)
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()])
        await ctx.add_init_script("localStorage.setItem('pd.tema.timbang', '"+theme+"')")
        await ctx.add_init_script("""window.__cfFetch=[];const asliFetch=window.fetch;window.fetch=async function(...args){try{let r=await asliFetch.apply(this,args);if(String(args[0]).includes('/koreksi'))window.__cfFetch.push({url:r.url,status:r.status});return r}catch(e){window.__cfFetch.push({gagal:String(e),url:String(args[0])});throw e}}""")
        page=await ctx.new_page();errors=[];konsol=[];gagal_req=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:konsol.append(m.text));page.on('requestfailed',lambda r:gagal_req.append({'url':r.url,'gagal':r.failure}))
        async def layani(route):
            req=route.request;u=urlsplit(req.url)
            if u.hostname!='127.0.0.1':return await route.abort()
            if u.path.endswith('/aliran'):
                return await route.fulfill(status=204,body='')
            if u.path.endswith('/keadaan'):
                return await route.fulfill(json={'n':'uji-stabil','versi':'81','jumlah_tiket':0})
            return await route.continue_()
        await page.route('**/*',layani)
        for label,path in [('timbang2',f'/tiket/{tid}')]:
            await page.goto(alamat_ui+'/timbangan'+path)
            await page.locator('#pembuka').wait_for(state='hidden')
            await page.evaluate('(t)=>document.documentElement.dataset.tema=t',theme)
            assert await page.locator('.kg-penerima').count()==2
            assert await page.locator('.kg-barang').count()==4
            assert '4.000' in await page.locator('.kg-kiriman').inner_text()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(OUT/f'{label}-{width}-{theme}.png'),full_page=True)
        # Penyelesaian lewat service asli, tidak menjanjikan callback simulasi.
        async with database.SessionLocal() as db:
            a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
            t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=9018.5,pengiriman_snapshot=p)
            aturan=await service.aturan_untuk(db,'PENGIRIMAN')
            umum=dict(trx=t,aturan=aturan,pihak=pengiriman.ringkasan(t.pengiriman_snapshot),petugas='Petugas Sintetis',muatan=t.muatan,perusahaan='Perusahaan Uji',alamat='Alamat Uji',telepon='Nomor Uji',arah_masuk=False)
            for label,data in [('ncr',pdf.bukti_ncr(**umum)),('80mm',pdf.bukti_thermal(**umum,tampilkan_selisih=False))]:
                reader=PdfReader(io.BytesIO(data));txt='\n'.join(p.extract_text() for p in reader.pages)
                assert 'Penerima Uji 0' in txt and 'Penerima Uji 1' in txt
                assert 'Total acuan' not in txt and 'Subtotal muat' not in txt
                (OUT/f'{label}-{width}.pdf').write_bytes(data)
            xml=epos.struk_timbang(**umum,tampilkan_selisih=False)
            assert 'Penerima Uji 0' in xml and 'Penerima Uji 1' in xml and 'Total acuan' not in xml
        for label,path in [('detail',f'/transaksi/{tid}'),('koreksi',f'/transaksi/{tid}/koreksi'),('riwayat','/transaksi')]:
            await page.goto(alamat_ui+'/timbangan'+path)
            await page.locator('#pembuka').wait_for(state='hidden')
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if label=='koreksi':
                assert await page.locator('[name=jumlah_karung]').count()==0
                assert await page.locator('[name=perbarui_muatan]').count()==1
            assert '2 pelanggan' in await page.locator('body').inner_text()
            await page.screenshot(path=str(OUT/f'{label}-{width}-{theme}.png'),full_page=True)
            if label=='koreksi' and width==390:
                p['sidik_sumber']='c'*64;p['muatan'][0]['berat_kg']=600
                await page.locator('[name=perbarui_muatan]').check()
                await page.wait_for_function('document.querySelector("[data-cf-hasil]").textContent.includes("4.100")')
                async with database.SessionLocal() as db:
                    from app.timbangan.models import TimbanganTransaksi
                    sebelum=await db.get(TimbanganTransaksi,tid)
                    assert sebelum.pengiriman_snapshot['muatan'][0]['berat_kg']=='500'
                await page.screenshot(path=str(OUT/'koreksi-sumber-390-dark.png'),full_page=True)
                await page.locator('[name=alasan]').fill('Muatan sumber diperbaiki melalui PadiFlow')
                await page.get_by_role('button',name='Simpan koreksi',exact=True).click()
                try:
                    await page.wait_for_url(lambda u:urlsplit(u).path=='/timbangan/transaksi/'+str(tid) and 'ok=' in str(u),wait_until='domcontentloaded',timeout=5000)
                except Exception:
                    import json
                    diagnostik={'url':page.url,'error':await page.locator('[data-cf-error]').text_content(),
                        'fetch':await page.evaluate('window.__cfFetch'),'console':konsol,'requestfailed':gagal_req,'invalid':await page.locator(':invalid').evaluate_all('(es)=>es.map(e=>({name:e.name,value:e.value,message:e.validationMessage}))')}
                    (OUT/'diagnostik-koreksi.json').write_text(json.dumps(diagnostik,indent=2))
                    raise AssertionError(diagnostik)
                async with database.SessionLocal() as db:
                    sesudah=await db.get(TimbanganTransaksi,tid)
                    assert sesudah.pengiriman_snapshot['muatan'][0]['berat_kg']=='600'
                    assert float(sesudah.timbang1_kg)==5000 and float(sesudah.timbang2_kg)==9018.5
                    assert float(sesudah.berat_acuan_kg)==4100 and float(sesudah.berat_barang_kg)==4000
        assert not errors
        await page.unroute_all(behavior='wait')
        await browser.close()

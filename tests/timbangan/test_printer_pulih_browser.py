"""Transport browser asli, printer tiruan; tidak ada koneksi printer atau DB."""
from profil_browser import konteks
import os
from pathlib import Path
import pytest
from playwright.async_api import async_playwright

AKAR = Path(__file__).resolve().parents[2]
JS = Path(os.environ.get('UJI_PRINTER_JS', AKAR / 'app/timbangan/static/app.js')).read_text()
STRUK = '<epos-print><text>UJI</text><cut/></epos-print>'

async def halaman(pw, mesin):
    opts = {'executable_path': os.environ['UJI_WEBKIT_PATH']} if mesin == 'webkit' and os.environ.get('UJI_WEBKIT_PATH') else {}
    b = await getattr(pw, mesin).launch(**opts)
    ctx = await b.new_context(**konteks(pw),service_workers='block')
    page = await ctx.new_page()
    await page.route('**/*', lambda r: r.fulfill(status=200, content_type='text/html', body='<html><body data-printer="https://printer.invalid"><div data-acuan></div></body></html>'))
    await page.goto('https://app.invalid/')
    await page.add_script_tag(content=JS)
    return b, page

async def kirim(page):
    return await page.evaluate('''async xml => {
      try {return {ok:await TeraFlowPrinter.kirim(null,xml)}}
      catch(e){return {ok:false,pesan:e.message,belumPasti:!!e.belumPasti,penyiapan:!!e.penyiapan}}
    }''', STRUK)

@pytest.mark.parametrize('mesin', ['chromium', 'webkit'])
@pytest.mark.parametrize('kasus', ['pulih', 'putus', 'kertas', 'ack-hilang', 'xml-rusak', 'tidur', 'izin'])
async def test_pulih_sebelum_struk_tanpa_cetak_ganda(mesin, kasus):
    async with async_playwright() as pw:
        b, page = await halaman(pw, mesin)
        status, struk = [], []
        async def printer(route):
            isi = route.request.post_data
            nyata = '<text>' in isi
            (struk if nyata else status).append(isi)
            if not nyata:
                assert '<feed' not in isi and '<cut' not in isi
                if kasus == 'putus' or kasus == 'pulih' and len(status) == 1 or kasus == 'tidur' and len(status) == 2:
                    return await route.abort()
                if kasus == 'kertas':
                    return await route.fulfill(content_type='text/xml', body='<response success="false" code="EPTR_REC_EMPTY"/>')
            if nyata and kasus == 'ack-hilang':
                return await route.abort()
            body = '<response success="true"/>'
            if nyata and kasus == 'xml-rusak':
                body = '<html>success="true"</html>'
            await route.fulfill(content_type='text/xml', body=body)
        await page.route('https://printer.invalid/**', printer)
        if kasus == 'izin':
            await page.evaluate("Object.defineProperty(navigator,'permissions',{value:{query:async()=>({state:'denied'})}})")
        hasil = await kirim(page)
        if kasus in ('pulih', 'tidur'):
            assert hasil['ok'], hasil
            if kasus == 'tidur':
                await page.evaluate("window.dispatchEvent(new Event('pageshow'));window.dispatchEvent(new Event('online'))")
                assert (await kirim(page))['ok']
            assert len(status) == (3 if kasus == 'tidur' else 2)
            assert len(struk) == (2 if kasus == 'tidur' else 1)
        elif kasus in ('putus', 'kertas', 'izin'):
            assert not hasil['ok'] and not hasil['belumPasti'], hasil
            assert not struk
            assert len(status) == {'putus':2, 'kertas':1, 'izin':0}[kasus]
            assert ('Wi-Fi' in hasil['pesan']) if kasus != 'kertas' else 'Kertas habis' in hasil['pesan']
        else:
            assert not hasil['ok'] and hasil['belumPasti'], hasil
            assert len(status) == len(struk) == 1
        await b.close()

@pytest.mark.parametrize('mesin', ['chromium', 'webkit'])
async def test_tenggat_membatalkan_pemeriksaan_yang_menggantung(mesin):
    async with async_playwright() as pw:
        b, page = await halaman(pw, mesin)
        await page.evaluate('''() => {
          const timer=window.setTimeout;
          window.setTimeout=(fn,ms,...args)=>timer(fn,ms===6000?20:ms===500?1:ms,...args);
          window.ujiStatus=0;window.ujiAbort=0;window.ujiStruk=0;
          window.fetch=(url,opts)=>{
            if(opts.body.includes('<text>')){window.ujiStruk++;return Promise.resolve(new Response('<response success="true"/>'));}
            window.ujiStatus++;
            return new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>{window.ujiAbort++;reject(new DOMException('Aborted','AbortError'));}));
          };
        }''')
        hasil = await kirim(page)
        assert not hasil['ok'] and not hasil['belumPasti'], hasil
        assert await page.evaluate('[ujiStatus,ujiAbort,ujiStruk]') == [2,2,0]
        await b.close()

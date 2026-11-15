"""Kontrak identitas pilihan setelah penyegaran, seluruh HTTP di fixture."""
import json, os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from test_web import app_uji, klien, login
from data_cari_lama import arsip
from app import database
from app.timbangan.models import TimbanganTransaksi
from app.timbangan.db import sekarang

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('UJI_BROWSER_CARI') != '1', reason='Browser lokal opsional')]


@pytest.mark.parametrize('width', [1440, 390, 320])
@pytest.mark.parametrize('peran', ['operator', 'admin', 'superadmin'])
async def test_identitas_baris_sesudah_dorongan(klien, width, peran):
    from playwright.async_api import async_playwright, expect
    await arsip(peran)
    await login(klien, 'fixture-'+peran)
    out = Path(os.environ['BUKTI_CARI'])
    baseline = os.getenv('BASELINE_CARI') == '1'
    requests, errors = [], []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport=dict(width=width, height=950), service_workers='block', reduced_motion='reduce')
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.context.add_cookies([dict(name=k.name, value=k.value, url='http://uji') for k in klien.cookies.jar])
        await page.add_init_script("""window.fixtureStreams=[];
          window.EventSource=class {constructor(url){this.url=url;fixtureStreams.push(this)}close(){this.closed=true}};
          window.fixturePush=n=>fixtureStreams.at(-1).onmessage({data:JSON.stringify({n})});
          window.fixtureRefresh=0;window.addEventListener('teraflow:data',()=>fixtureRefresh++);
        """)
        async def route(r):
            req=r.request; u=urlsplit(req.url)
            if u.netloc!='uji' or req.method!='GET': return await r.abort()
            if u.path=='/timbangan/keadaan': return await r.fulfill(status=200,content_type='application/json',body='{"n":"awal"}')
            response=await klien.get(u.path+('?' +u.query if u.query else ''))
            if u.path=='/timbangan/transaksi': requests.append(dict(status=response.status_code, bytes=len(response.content)))
            await r.fulfill(status=response.status_code, body=response.content, headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding')})
        await page.route('**/*',route)
        try:
            await page.goto('http://uji/timbangan/transaksi')
            await page.wait_for_function('typeof fixtureStreams.at(-1)?.onmessage==="function"')
            await page.evaluate("fixturePush('awal')")
            await page.get_by_role('searchbox',name='Cari tiket').fill('Draf belum dicari')
            await page.get_by_role('searchbox',name='Cari tiket').blur()
            before=await page.locator('[data-baris-pilih]').evaluate_all("es=>es.map(e=>({row:e.closest('tr').dataset.riwayatId,value:e.value}))")
            async with database.SessionLocal() as db:
                kini=sekarang()
                t=TimbanganTransaksi(kode='SESUDAH-DORONGAN', tanggal=kini.date(), arah='BEBAS', jenis_kode='BEBAS', timbang1_kg=1000, timbang1_waktu=kini)
                db.add(t);await db.commit()
            await page.evaluate("fixturePush('baru')")
            await page.wait_for_function('fixtureRefresh===1')
            await expect(page.locator('.rh-item').first).to_contain_text('SESUDAH-DORONGAN')
            after=await page.locator('[data-baris-pilih]').evaluate_all("es=>es.map(e=>({row:e.closest('tr').dataset.riwayatId,value:e.value}))")
            evidence=dict(peran=peran,width=width,before=before,after=after,requests=requests,errors=errors,refreshes=await page.evaluate('fixtureRefresh'))
            (out/f'{"baseline" if baseline else "after"}-segar-{peran}-{width}.json').write_text(json.dumps(evidence,indent=2)+'\n')
            assert all(x['row']==x['value'] for x in after),after
            assert len({x['value'] for x in after})==len(after)
            await expect(page.get_by_role('searchbox',name='Cari tiket')).to_have_value('Draf belum dicari')
            # Sambung ulang tetap memakai aliran yang sama dan tidak mengubah ID.
            await page.evaluate('fixtureStreams.at(-1).onerror()')
            await page.wait_for_function('fixtureStreams.length===2')
            await page.evaluate("fixturePush('sambung')")
            await page.wait_for_function('fixtureStreams[0].closed===true')
            if peran=='superadmin':
                pilihan=page.locator('[data-baris-pilih]').nth(2)
                target=await pilihan.get_attribute('value')
                await pilihan.focus();await page.keyboard.press('Space')
                assert await page.evaluate("Array.from(new FormData(document.querySelector('[data-baris-pilih]').form).getAll('transaksi_id'))")==[target]
            await page.screenshot(path=str(out/f'after-segar-{peran}-{width}.png'))
            assert not errors,errors
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        finally: await browser.close()


async def test_pilihan_berulang_radio_dan_draf_tetap_terikat():
    """Baris dapat pindah/hilang; nilai baru dari server bukan draf lama."""
    from playwright.async_api import async_playwright
    source=Path(__file__).resolve().parents[2]/'app/timbangan/static/keadaan-baca.js'
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        page=await browser.new_page()
        try:
            await page.set_content('''<main id="root"><form><input name="baris" type="checkbox" value="1" checked>
              <input name="baris" type="checkbox" value="2"><input name="arah" type="radio" value="a">
              <input name="arah" type="radio" value="b" checked><input id="tetap" type="checkbox" value="lama" checked>
              <input name="cari" value="draf"><textarea name="catatan">belum dikirim</textarea>
              <select name="jenis" multiple><option selected value="a">A</option><option value="b">B</option></select>
              <input type="hidden" name="token" value="lama"></form></main>''')
            await page.add_script_tag(path=str(source))
            result=await page.evaluate('''()=>{
              var root=document.getElementById('root'),s=KEADAAN_BACA.ambil(root),fresh=root.cloneNode(true);
              fresh.innerHTML=`<form><input name="baris" type="checkbox" value="3"><input name="baris" type="checkbox" value="2">
                <input name="baris" type="checkbox" value="1"><input name="arah" type="radio" value="c">
                <input name="arah" type="radio" value="b"><input id="tetap" type="checkbox" value="baru">
                <input name="cari" value="server"><textarea name="catatan">server</textarea>
                <select name="jenis" multiple><option value="a">A</option><option selected value="b">B</option></select>
                <input type="hidden" name="token" value="baru"></form>`;
              KEADAAN_BACA.tukar(root,fresh);KEADAAN_BACA.pulihkan(root,s);
              return {pilihan:Array.from(root.querySelectorAll('input[type=checkbox],input[type=radio]')).map(e=>[e.value,e.checked]),
                cari:root.querySelector('[name=cari]').value,catatan:root.querySelector('textarea').value,
                jenis:Array.from(root.querySelector('select').selectedOptions).map(e=>e.value),token:root.querySelector('[name=token]').value};
            }''')
            assert result==dict(pilihan=[['3',False],['2',False],['1',True],['c',False],['b',True],['baru',False]],cari='draf',catatan='belum dikirim',jenis=['a'],token='baru')
        finally: await browser.close()

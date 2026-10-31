"""Balasan penolakan yang sah menggantikan pesan jaringan lama.

Endpoint dipalsukan pada browser; IndexedDB, event online dan luring.js tetap
nyata. Integrasi/konkurensi database diperiksa oleh suite PG dan PWA terpisah.
"""
from pathlib import Path
import json
import pytest

pw=pytest.importorskip('playwright.sync_api')
ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('status',[409,422])
def test_penolakan_server_tidak_meninggalkan_pesan_tanpa_jaringan(status):
    js=(ROOT/'app/timbangan/static/luring.js').read_text()
    html='''<!doctype html><meta charset="utf-8"><body data-akun-id="1"><main><form action="/timbangan/tiket/1" method="post" data-simpan-luring>
    <input name="kunci" value="11111111-1111-4111-8111-111111111111"><input name="berat_kg" value="5000"><button type="submit" name="aksi" value="selesai">Selesai</button></form></main><script>'''+js+'</script></body>'
    posts=[]
    with pw.sync_playwright() as p:
        browser=p.chromium.launch();ctx=browser.new_context();page=ctx.new_page()
        def route(r):
            if r.request.method=='POST':
                posts.append(r.request.post_data)
                r.fulfill(status=status,content_type='application/json',body=json.dumps({'tersimpan':False,'pesan':'Tiket sudah selesai atau isian perlu diperiksa.'}))
            elif r.request.url.endswith('/kiriman/sesi'):
                r.fulfill(content_type='application/json',body='{"akun_id":"1"}')
            else:r.fulfill(content_type='text/html',body=html)
        page.route('http://127.0.0.1:8765/**',route)
        try:
            page.goto('http://127.0.0.1:8765/timbangan/tiket/1')
            page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
            ctx.set_offline(True);page.locator('button[type=submit]').click()
            page.get_by_text('Tanpa jaringan.',exact=False).wait_for()
            pending=page.evaluate('window.timbanganLuring.antrean()')[0]
            ctx.set_offline(False);page.evaluate('window.timbanganLuring.sinkronkan()')
            for _ in range(100):
                rows=page.evaluate('window.timbanganLuring.antrean()')
                if rows[0]['status']=='periksa' and 'Tiket sudah selesai' in page.locator('[data-luring-panel]').inner_text():break
                page.wait_for_timeout(50)
            assert rows[0]['status']=='periksa'
            assert rows[0]['data']==pending['data']
            assert page.locator('[name=berat_kg]').input_value()=='5000'
            assert 'Tanpa jaringan.' not in page.locator('[data-luring-panel]').inner_text()
            assert 'Mengirim kiriman' not in page.locator('[data-luring-panel]').inner_text()
            page.evaluate('window.timbanganLuring.sinkronkan()')
            assert len(posts)==1
        finally:ctx.close();browser.close()

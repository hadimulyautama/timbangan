"""Alur asli pada SQLite sintetis dan HTTP loopback, tanpa data operasional."""
import os
from copy import deepcopy
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login  # noqa: F401
from test_timbang_pertama_desain_browser import lokal,halaman as halaman_asli  # noqa: F401
from test_koreksi_antarmuka import tiket,payload
from test_rincian_retur import tautkan
from app import database
from app.timbangan import klien_produksi
from app.timbangan.models import TimbanganTransaksi,TimbanganAudit,TimbanganCetak,TimbanganPemeriksaan

async def halaman(*args,**kwargs):
    ctx,page=await halaman_asli(*args,**kwargs)
    # Hindari galat native Chromium "Transition was skipped" dari transisi
    # antar dokumen saat pengujian memicu navigasi beruntun.
    await page.emulate_media(reduced_motion='reduce')
    return ctx,page

async def source(monkeypatch,tid,status='tercatat'):
    async with database.SessionLocal() as db:t=await db.get(TimbanganTransaksi,tid)
    result=dict(tiket_id=tid,kode_tiket=t.kode,jenis_kode=t.jenis_kode,jasa=bool(t.jasa),status=status,
      cakupan='Gudang 1 dan 2',pesanan=None,berat_diterima_kg='9980.84',keterangan_berat='Belum final',catatan=[
      dict(id=1,model='gabah',kode='TERIMA-UJI-1',pemilik='Milik pabrik',jasa_id=None,jasa_kode=None,berat_kg='6000.5',status='diproses',sementara=False,waktu='2026-11-07T03:00:00+00:00',petugas='Petugas Penerimaan',lokasi=['Gudang 1'],qc=[dict(status='Berjalan',putaran=[dict(nomor=1,waktu='2026-11-07T03:05:00+00:00',petugas='Pemeriksa Uji',hasil=[['Kadar air','14%']])])]),
      dict(id=2,model='gabah',kode='TERIMA-UJI-2',pemilik='Pelanggan pemilik lain',jasa_id=3,jasa_kode='JAS-UJI-3',berat_kg='3980.34',status='baru',sementara=True,waktu=None,petugas=None,lokasi=[],qc=[])])
    async def read(*a,**kw):return deepcopy(result)
    monkeypatch.setattr(klien_produksi,'detail_masuk',read)

@pytest.mark.parametrize('finished',[False,True])
@pytest.mark.parametrize('width',[320,390,1440])
async def test_koreksi_ukuran_payload_simpan_dan_gagal(lokal,finished,width):
    url,client=lokal;tid=await tiket(selesai=finished)
    await login(client,'wahid')
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx,page=await halaman(browser,url,client,width)
        if width==390 and finished:await ctx.add_init_script("localStorage.setItem('pd.tema.timbang','dark')")
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(f'{url}/timbangan/transaksi/{tid}/koreksi')
        await page.locator('[data-kc-guide]').wait_for(state='visible')
        assert await page.locator('.kc-page').get_attribute('data-kc-open')==str(not finished).lower()
        assert await page.locator('[name=timbang2_kg]').count()==int(finished)
        before=await page.locator('[data-correction-form]').evaluate('e=>Array.from(new FormData(e).entries())')
        await page.locator('[data-kc-guide]').click();assert await page.locator('#kc-panduan').evaluate('e=>e.open')
        assert before==await page.locator('[data-correction-form]').evaluate('e=>Array.from(new FormData(e).entries())')
        await page.keyboard.press('Escape')
        if finished:
            sizes=await page.locator('.kc-weights').evaluate('e=>[...e.querySelectorAll("input")].map(x=>({height:x.getBoundingClientRect().height,font:getComputedStyle(x).fontSize,width:x.getBoundingClientRect().width}))')
            assert sizes[0]['font']==sizes[1]['font']=='28px',sizes
            assert sizes[0]['height']==sizes[1]['height'],sizes
            assert abs(sizes[0]['width']-sizes[1]['width'])<=1,sizes
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.locator('[name=nama_sopir]').fill('Sopir Baru Desain')
        await page.locator('[data-correction-form] [name=alasan]').fill('Perbaikan nama sopir')
        await page.wait_for_function('document.querySelector("[data-cf-hasil]").textContent.includes("Sopir Baru Desain")')
        if finished:assert await page.locator('.kc-result-pair').count()==1
        else:assert await page.locator('.kc-calculation').count()==1
        await page.locator('[data-cf-cancel]').click();assert await page.locator('[data-cf-discard]').evaluate('e=>e.open');await page.locator('[data-cf-keep]').click()
        out=os.environ.get('UJI_KD_OUT')
        if out:
            Path(out).mkdir(parents=True,exist_ok=True);await page.screenshot(path=str(Path(out)/f'koreksi-{finished}-{width}.png'),full_page=True)
        # Putuskan endpoint simpan saja; draf tidak boleh menghilang atau
        # dianggap sudah tersimpan. Sesudah dilepas, alur asli harus berhasil.
        await page.route(f'**/transaksi/{tid}/koreksi',lambda r:r.abort() if r.request.method=='POST' else r.continue_())
        await page.locator('[data-correction-form] button[type=submit]').click()
        await page.locator('[data-cf-error]').wait_for(state='visible')
        assert await page.locator('[name=nama_sopir]').input_value()=='Sopir Baru Desain'
        await page.unroute(f'**/transaksi/{tid}/koreksi')
        await page.locator('[data-correction-form] button[type=submit]').click()
        await page.wait_for_url('**/transaksi/*?ok=**')
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid);assert t.nama_sopir=='Sopir Baru Desain';assert t.status_tiket==('SELESAI' if finished else 'TERBUKA');assert float(t.muatan[0].tara_per_karung_kg)==.0858
        assert not errors,errors
        await ctx.close();await browser.close()

@pytest.mark.parametrize('width',[320,390,1440])
async def test_detail_ringkas_data_penerimaan_dan_pemeriksaan(lokal,monkeypatch,width):
    url,client=lokal;tid=await tiket();await tautkan('wahid');await source(monkeypatch,tid);await login(client,'wahid')
    async with database.SessionLocal() as db:
        # Tiket normal juga dapat memiliki pemeriksaan lama yang belum ditutup.
        db.add(TimbanganPemeriksaan(transaksi_id=tid));await db.commit()
        before=await db.scalar(select(func.count()).select_from(TimbanganAudit))
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx,page=await halaman(browser,url,client,width);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(f'{url}/timbangan/transaksi/{tid}?kembali=/timbangan/transaksi%3Fhal=2')
        await page.locator('[data-rd-guide]').wait_for(state='visible')
        assert await page.locator('.dk-kembali').get_attribute('href')=='/timbangan/transaksi?hal=2'
        assert await page.locator('.rd-controls').get_by_text('Timbang berikutnya').count()==0
        assert await page.locator('.rd-controls').get_by_text('Tiket Aktif').count()==0
        assert await page.locator('#rd-perhitungan').evaluate('e=>!e.open')
        await page.locator('#rd-perhitungan>summary').click();assert '0,0858' in await page.locator('#rd-perhitungan').inner_text()
        await page.locator('#rd-penerimaan>summary').click();assert 'Pelanggan pemilik lain' in await page.locator('#rd-penerimaan').inner_text();assert 'Bobot sementara' in await page.locator('#rd-penerimaan').inner_text();assert 'JAS-UJI-3' in await page.locator('#rd-penerimaan').inner_text()
        await page.locator('#rd-penerimaan summary').filter(has_text='Mutu penerimaan').click();assert '14%' in await page.locator('#rd-penerimaan').inner_text()
        await page.locator('[data-rd-guide]').click();await page.keyboard.press('Escape')
        await page.locator('[data-rd-exam-open]').click()
        assert await page.locator('#rd-exam').evaluate('e=>e.open')
        await page.get_by_label('Kategori hasil',exact=True).select_option('LAIN');await page.get_by_label('Catatan resolusi',exact=True).fill('Temuan uji dipertahankan')
        await page.route('**/periksa',lambda r:r.abort())
        await page.get_by_role('button',name='Tutup pemeriksaan',exact=True).click();await page.locator('[data-hasil-pemeriksaan]').wait_for(state='visible')
        assert await page.get_by_label('Catatan resolusi',exact=True).input_value()=='Temuan uji dipertahankan'
        await page.locator('#rd-exam [data-rd-close]').click();await page.locator('[data-rd-exam-open]').click();assert await page.get_by_label('Catatan resolusi',exact=True).input_value()=='Temuan uji dipertahankan'
        await page.locator('#rd-exam [data-rd-close]').click()
        await page.locator('[data-tindakan-trigger]').click();assert await page.locator('[data-tindakan-menu]').get_by_role('link',name='Koreksi',exact=True).is_visible()
        await page.keyboard.press('Escape')
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        for selector in ['#rd-perhitungan>summary','#rd-penerimaan>summary']:
            if await page.locator(selector).evaluate('e=>e.parentElement.open'):await page.locator(selector).click()
        out=os.environ.get('UJI_KD_OUT')
        if out:await page.screenshot(path=str(Path(out)/f'detail-{width}.png'),full_page=True)
        assert not errors,errors;await ctx.close();await browser.close()
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganAudit))==before

async def test_tanpa_js_dan_url_lama(lokal,monkeypatch):
    url,client=lokal;tid=await tiket();await source(monkeypatch,tid)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx,page=await halaman(browser,url,client,390,False)
        await page.goto(f'{url}/timbangan/transaksi/{tid}')
        await page.locator('[data-rd-guide-fallback]>summary').evaluate('e=>e.scrollIntoView({block:"center"})');await page.locator('[data-rd-guide-fallback]>summary').click();assert await page.locator('[data-rd-guide-content]').is_visible()
        await page.locator('[data-rd-actions-fallback]>summary').click();assert await page.locator('[data-rd-actions-content]').get_by_role('link',name='Koreksi',exact=True).is_visible()
        await ctx.close()
        ctx,page=await halaman(browser,url,client,390)
        await page.goto(f'{url}/timbangan/transaksi/{tid}?tab=perhitungan');assert await page.locator('#rd-perhitungan').evaluate('e=>e.open')
        await ctx.close();await browser.close()

async def test_koreksi_tanpa_perubahan_tidak_dianggap_kotor(lokal):
    url,client=lokal;tid=await tiket(selesai=False)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx,page=await halaman(browser,url,client,390)
        await page.goto(f'{url}/timbangan/transaksi/{tid}/koreksi')
        await page.locator('[data-kc-guide]').wait_for(state='visible')
        await page.locator('[data-cf-cancel]').click()
        await page.wait_for_url(f'{url}/timbangan/transaksi/{tid}')
        await ctx.close();await browser.close()

@pytest.mark.parametrize('width',[320,390,1440])
async def test_kontrol_riwayat_filter_get_dan_panduan(lokal,width):
    url,client=lokal;await tiket();await login(client,'wahid')
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx,page=await halaman(browser,url,client,width)
        await page.goto(f'{url}/timbangan/transaksi')
        form=page.locator('form[aria-label="Filter riwayat timbang"]')
        before=await form.evaluate('e=>Array.from(new FormData(e).entries())')
        await page.locator('[data-rh-guide]').click();assert await page.locator('#rh-panduan').evaluate('e=>e.open')
        await page.keyboard.press('Escape');assert before==await form.evaluate('e=>Array.from(new FormData(e).entries())')
        await page.locator('[data-rh-filter]').click();assert await form.locator('[name=dari]').is_visible()
        assert await page.locator('.rh-filter-panel').evaluate('e=>e.getBoundingClientRect().width')>width*.5 if width<650 else True
        await form.locator('[name=arah]').select_option('MASUK');await form.locator('[name=cari]').fill('W 123 UJ')
        await form.get_by_role('button',name='Terapkan filter').click();await page.wait_for_url('**/transaksi?**')
        assert 'arah=MASUK' in page.url and 'cari=W+123+UJ' in page.url
        assert await page.locator('.rh-more').evaluate('e=>e.open')
        assert await page.locator('.rh-item').count()==1
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        if width==1440:
            boxes=await page.locator('.rh-form').first.evaluate('e=>[e.querySelector("[name=cari]"),e.querySelector("[data-rh-filter]")].map(x=>x.getBoundingClientRect().bottom)')
            assert abs(boxes[0]-boxes[1])<2,boxes
        out=os.environ.get('UJI_KD_OUT')
        if out:await page.screenshot(path=str(Path(out)/f'riwayat-kontrol-{width}.png'),full_page=True)
        await ctx.close();await browser.close()

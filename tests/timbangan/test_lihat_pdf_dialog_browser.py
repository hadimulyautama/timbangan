"""Matriks dialog PDF seluruh jenis/cara timbang pada aplikasi v109; printer dan share disimulasikan."""
import io,asyncio,os,json
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from pypdf import PdfReader
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_koreksi_antarmuka import tiket as dasar
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganCetak,TimbanganPekerjaanCetak as Job,TimbanganAkun,TimbanganTransaksi

JENIS=['gabah_basah','gabah_kering','pk','beras','broken','jasa','sekali','partai','keluar','transfer','retur_pelanggan','retur_supplier','bebas']
async def buat(jenis):
    if jenis=='keluar':
        from test_rincian_keluar import buat_tiket
        return await buat_tiket()
    if jenis=='transfer':
        from test_rincian_transfer import master,tiket
        await master();return await tiket()
    if jenis=='retur_pelanggan':
        from test_rincian_retur import tiket
        return await tiket()
    if jenis=='retur_supplier':
        from test_rincian_supplier import tiket
        return await tiket()
    if jenis=='bebas':return await dasar(arah='BEBAS',kode='BEBAS')
    if jenis=='jasa':return await dasar(jasa=True,kode='GABAH_KERING')
    if jenis=='sekali':return await dasar(cara='SEKALI')
    if jenis=='partai':
        tid=await dasar(cara='PARTAI')
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid);a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
            await service.selesaikan_partai(db,akun=a,kode=t.kode,jumlah_karung=3)
        return tid
    return await dasar(kode={'gabah_basah':'GABAH_BASAH','gabah_kering':'GABAH_KERING','pk':'BERAS_PK','beras':'BERAS_MASUK','broken':'BROKEN_MASUK'}[jenis])

async def jumlah(model):
    async with database.SessionLocal() as db:return await db.scalar(select(func.count()).select_from(model))

@pytest.mark.parametrize('jenis',JENIS)
@pytest.mark.parametrize('width',[1440,390])
async def test_cetak_lihat_bagikan_tanpa_navigasi(klien,alamat_ui,jenis,width):
    tid=await buat(jenis);await login(klien,'wahid')
    async with async_playwright() as pw:
        browser,ctx,page=await browser_uji(pw,klien,alamat_ui,width,'dark' if width==390 else 'light')
        errors=[];navigasi=[];printer=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}?kembali=/timbangan/transaksi%3Fhal=2')
        lokasi=page.url
        page.on('framenavigated',lambda frame:navigasi.append(frame.url) if frame==page.main_frame else None)
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' and urlsplit(r.url).hostname=='127.0.0.1' and '/pekerjaan' in r.url else None)
        kontrol=page.locator('.tf-detail-controls__actions')
        for label in ('Cetak','Lihat','Bagikan'):
            link=kontrol.get_by_role('button' if label=='Lihat' else 'link',name=label,exact=True)
            assert await link.count()==1 and await link.is_visible()
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        # PDF benar-benar dirender di dialog, tanpa tab atau navigasi baru.
        assert len(ctx.pages)==1
        await kontrol.get_by_role('button',name='Lihat',exact=True).click()
        await page.wait_for_function("document.querySelector('.tf-pdf-dialog [data-pdf-status]').textContent.endsWith('halaman')",timeout=15000)
        assert await page.locator('.tf-pdf-dialog').evaluate('e=>e.open')
        assert await page.locator('.tf-pdf-dialog [data-pdf-selesai]').count()>=1
        assert 'BERAT BARANG' in await page.locator('.tf-pdf-dialog').text_content()
        assert len(ctx.pages)==1 and page.url==lokasi and not navigasi
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.get_by_role('button',name='Tutup PDF',exact=True).click()
        assert await kontrol.get_by_role('button',name='Lihat',exact=True).evaluate('e=>e===document.activeElement')
        raw=(await klien.get(f'/timbangan/transaksi/{tid}/cetak/80mm')).content
        reader=PdfReader(io.BytesIO(raw));assert float(reader.pages[0].mediabox.width)==pytest.approx(80*72/25.4,abs=.01)
        assert 'BERAT BARANG' in '\n'.join(p.extract_text() for p in reader.pages)
        assert await jumlah(TimbanganCetak)==0 and await jumlah(Job)==0 and not posts
        assert page.url==lokasi and not navigasi
        # Native share diganti perekam agar tidak mengirim berkas kepada siapa pun.
        await page.evaluate("() => {navigator.canShare=()=>true;navigator.share=async d=>{window.__share={type:d.files[0].type,size:d.files[0].size,name:d.files[0].name}};}")
        await kontrol.get_by_role('link',name='Bagikan',exact=True).click()
        await page.wait_for_function("window.__share?.type==='application/pdf'")
        assert (await page.evaluate('window.__share')).get('size',0)>100
        assert await jumlah(TimbanganCetak)==0 and await jumlah(Job)==0 and not posts
        assert page.url==lokasi and not navigasi
        # Cetak pertama otomatis sesudah satu klik, termasuk penekanan ganda.
        async def alat(route):
            if '<text' not in (route.request.post_data or ''):
                return await route.fulfill(content_type='text/xml',body='<response success="true"/>')
            printer.append(route.request.post_data);await asyncio.sleep(.05)
            await route.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
        await page.route('**/cgi-bin/epos/**',alat)
        await page.evaluate("localStorage.setItem('timbangan-printer','http://127.0.0.1:9999')")
        await kontrol.get_by_role('link',name='Cetak',exact=True).evaluate('(e)=>{e.click();e.click()}')
        await page.wait_for_function("document.querySelector('[data-cetak-langsung-hasil]').textContent.includes('berhasil')",timeout=10000)
        assert len(printer)==1 and await jumlah(TimbanganCetak)==1
        assert page.url==lokasi and not navigasi
        # Cetak ulang meminta alasan pada dialog, tanpa navigasi.
        await kontrol.get_by_role('link',name='Cetak',exact=True).click()
        alasan=page.locator('.tf-cetak-dialog [name=alasan]');await alasan.wait_for(state='visible')
        await alasan.fill('Salinan uji semua jenis')
        await page.locator('.tf-cetak-dialog [data-cp-jalankan]').click()
        await page.locator('.tf-cetak-dialog').wait_for(state='hidden')
        assert len(printer)==2 and await jumlah(TimbanganCetak)==2
        assert await jumlah(Job)==2 and page.url==lokasi and not navigasi and not errors
        async with database.SessionLocal() as db:
            rows=list(await db.scalars(select(TimbanganCetak).order_by(TimbanganCetak.urutan)))
            assert [r.format for r in rows]==['80MM','80MM'] and rows[-1].alasan=='Salinan uji semua jenis'
        out=Path(os.environ['UJI_MATRIKS_OUT']);out.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(out/f'{jenis}-{width}.png'),full_page=True)
        (out/f'{jenis}-{width}.json').write_text(json.dumps(dict(jenis=jenis,width=width,cetak=2,lihat=True,bagikan=True,navigasi_detail=len(navigasi),galat=errors),indent=2))
        await browser.close()

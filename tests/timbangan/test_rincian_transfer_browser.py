"""UI transfer dengan basis data SQLite sementara; tidak menuju host operasional."""
from pathlib import Path
from urllib.parse import urlsplit
from datetime import timedelta
import os
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
import io
from pypdf import PdfReader
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer import master,tiket
from test_rincian_retur import tautkan
from app import database
from app.timbangan import service
from app.timbangan.db import sekarang
from app.timbangan.models import TimbanganTransaksi,TimbanganAkun,TimbanganAudit,TimbanganCetak
from hmu_identitas import peran as P
OUT=Path(__file__).absolute().parents[3]/'output/detail-tiket-transfer-20261027'

async def browser_uji(pw,klien,alamat,width=390,theme='light',browser='chromium'):
    opts={'executable_path':os.environ['UJI_WEBKIT_PATH']} if browser=='webkit' and os.environ.get('UJI_WEBKIT_PATH') else {}
    b=await getattr(pw,browser).launch(**opts);ctx=await b.new_context(viewport={'width':width,'height':920},service_workers='block',reduced_motion='reduce',color_scheme=theme)
    await ctx.add_cookies([{'name':k,'value':v,'url':alamat} for k,v in klien.cookies.items()])
    await ctx.add_init_script("localStorage.setItem('pd.tema.timbang', '"+theme+"')")
    page=await ctx.new_page()
    async def route(r):
        u=urlsplit(r.request.url)
        if u.hostname!='127.0.0.1':return await r.abort()
        if u.path.endswith('/aliran'):return await r.fulfill(status=204,body='')
        if u.path.endswith('/keadaan'):return await r.fulfill(json={'n':'uji-stabil','versi':'86','jumlah_tiket':0})
        return await r.continue_()
    await page.route('**/*',route)
    return b,ctx,page

async def buka(page,url):
    await page.goto(url);await page.locator('#pembuka').wait_for(state='hidden')

@pytest.mark.parametrize('width,theme,role',[(320,'light',P.OPERATOR),(390,'dark',P.SUPERADMIN),(768,'light',P.ADMIN),(1440,'light',P.ADMIN),(1440,'dark',P.OPERATOR)])
async def test_tiga_tab_layar_keyboard_konteks(klien,alamat_ui,width,theme,role):
    OUT.mkdir(parents=True,exist_ok=True);await master();tid=await tiket(nopol='B 9123 UJ')
    who='miftah' if role==P.OPERATOR else 'wahid';await tautkan(who,role);await login(klien,who)
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'));t=await db.get(TimbanganTransaksi,tid)
        await service.buka_pemeriksaan(db,trx=t,akun=a);await db.commit()
        before=await db.scalar(select(func.count()).select_from(TimbanganAudit))
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,theme);errors=[];writes=[]
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}?kembali=/timbangan/transaksi%3Fhal=2')
        assert await page.locator('.dk-kembali').get_attribute('href')=='/timbangan/transaksi?hal=2'
        for tab in ('ringkasan','perhitungan','jejak'):
            await page.locator(f'[data-dk-tab={tab}]').click();assert await page.locator(f'#dk-{tab}').is_visible()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await page.screenshot(path=str(OUT/f'{tab}-{width}-{theme}-{role}.png'),full_page=True)
        await page.locator('[data-dk-tab=ringkasan]').click();await page.locator('[data-dk-tab=ringkasan]').press('ArrowRight')
        assert await page.locator('[data-dk-tab=perhitungan]').get_attribute('aria-selected')=='true'
        await page.reload();assert await page.locator('#dk-perhitungan').is_visible()
        assert not writes and not errors
        await b.close()
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganAudit))==before

@pytest.mark.parametrize('browser',['chromium','webkit'])
async def test_pilihan_baru_koreksi_dan_gagal_simpan(klien,alamat_ui,browser):
    await master();await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,320,browser=browser)
        await buka(page,alamat_ui+'/timbangan/timbang/TRANSFER')
        await page.locator('[name=berat_kg]').fill('10500');await page.locator('[name=nama_sopir]').fill('Sopir Uji')
        await page.locator('[name=transfer_asal]').select_option('101');await page.locator('[name=transfer_tujuan]').select_option('silo:104')
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path=str(OUT/f'pilihan-lokasi-320-{browser}.png'),full_page=True)
        await page.get_by_role('button',name='Simpan timbang pertama',exact=True).click()
        await page.wait_for_url('**/transaksi/**')
        async with database.SessionLocal() as db:
            t=await db.scalar(select(TimbanganTransaksi));tid=t.id;assert t.lintasan_transfer['tujuan']['silo_id']==104
        await page.locator('.dk-lanjutan>summary').click();await page.get_by_role('link',name='Koreksi',exact=True).click()
        await page.locator('[name=transfer_tujuan]').select_option('gudang:102')
        await page.locator('[data-correction-form] [name=alasan]').fill('Pilihan lokasi uji')
        await page.wait_for_function("document.querySelector('[data-cf-hasil]').textContent.includes('Tumpukan')")
        await page.route(f'**/transaksi/{tid}/koreksi',lambda r:r.abort())
        await page.get_by_role('button',name='Simpan koreksi',exact=True).click()
        await page.locator('[data-cf-error]').wait_for(state='visible')
        assert await page.locator('[name=transfer_tujuan]').input_value()=='gudang:102'
        assert await page.locator('[data-correction-form] [name=alasan]').input_value()=='Pilihan lokasi uji'
        async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).lintasan_transfer['tujuan']['silo_id']==104
        await page.unroute(f'**/transaksi/{tid}/koreksi')
        posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' and r.url.endswith('/koreksi') else None)
        await page.locator('[data-correction-form]').evaluate('(f)=>{f.requestSubmit();f.requestSubmit()}')
        await page.wait_for_url(lambda u:'ok=' in str(u));assert len(posts)==1
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid);assert t.lintasan_transfer['tujuan']['silo_id'] is None and t.status_tiket=='TERBUKA' and t.jumlah_revisi==1
        await b.close()

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_tindakan_dan_kunci_ui(klien,alamat_ui,role):
    await master();tid=await tiket();who='miftah' if role==P.OPERATOR else 'wahid'
    await tautkan(who,role);await login(klien,who)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);t.timbang2_waktu_sistem=sekarang()-timedelta(days=10);await db.commit()
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}');await page.locator('.dk-lanjutan>summary').click()
        assert await page.get_by_role('link',name='Koreksi',exact=True).count()==int(P.admin_keatas(role))
        form=page.locator('form[action$="/batal"]');assert await form.count()==int(P.admin_keatas(role))
        assert await page.locator('form[action$="/hapus"]').count()==int(role==P.SUPERADMIN)
        if P.admin_keatas(role):
            await form.locator('..').locator('summary').click();await form.locator('[name=alasan]').fill('Pembatalan uji terpisah')
            await form.locator('button').click();await page.wait_for_url(lambda u:'ok=' in str(u))
            async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).status_transaksi=='VOID'
        else:
            await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data={'alasan':'URL langsung','nama_sopir':'Tidak boleh'})
            async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).nama_sopir=='Sopir Uji'
        await b.close()

async def test_riwayat_teks_panjang_tanpa_kendaraan(klien,alamat_ui):
    await master();tid=await tiket(terstruktur=False,catatan='TRF-123 bukan relasi. '+('Keterangan panjang ' * 60))
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);t.jumlah_karung=0;t.pihak_nama='Teks historis tanpa pemisah '+('lokasi '*10);await db.commit()
    await login(klien)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,320)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
        assert await page.locator('.dk-hero h1').inner_text()==t.kode
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path=str(OUT/'historis-teks-panjang-320.png'),full_page=True)
        await b.close()

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_cetak_pdf_printer_sintetis_dan_audit(klien,alamat_ui,role):
    import io
    from pypdf import PdfReader
    OUT.mkdir(parents=True,exist_ok=True)
    await master();tid=await tiket();siapa='miftah' if role==P.OPERATOR else 'wahid'
    await tautkan(siapa,role);await login(klien,siapa)
    async with async_playwright() as pw:
        browser,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
        await page.get_by_role('link',name='Cetak bukti timbang',exact=True).click()
        await page.locator('[data-cetak]').wait_for(state='visible')
        assert await page.locator('[data-cetak]').count()==1
        for fmt in ('80mm','ncr'):
            async with page.expect_download() as event:
                await page.locator(f'a[data-unduh][href$="/{fmt}"]').click()
            d=await event.value;data=Path(await d.path()).read_bytes()
            assert data.startswith(b'%PDF')
            txt='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)
            assert 'selisih' not in txt.lower()
            (OUT/f'{fmt}-{role}.pdf').write_bytes(data)
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        await page.locator('a[href$="/printer"]').click()
        await page.locator('[name=printer_url]').wait_for(state='visible')
        assert await page.locator('[name=printer_url]').count()==1
        await page.go_back()
        await page.locator('[data-cetak]').wait_for(state='visible')
        await page.evaluate("localStorage.setItem('timbangan-printer','http://127.0.0.1:9999')")
        async def tolak(r):return await r.fulfill(status=200,content_type='text/xml',body='<response success="false" code="EPTR_COVER_OPEN"/>')
        await page.route('**/cgi-bin/epos/**',tolak)
        await page.locator('[data-cetak]').click()
        await page.wait_for_function("document.querySelector('[data-hasil-cetak]').textContent.includes('Penutup printer terbuka')")
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        await page.unroute('**/cgi-bin/epos/**')
        await page.route('**/cgi-bin/epos/**',lambda r:r.abort())
        await page.locator('[data-cetak]').click()
        await page.wait_for_function("document.querySelector('[data-hasil-cetak]').textContent.includes('belum bisa menghubungi')")
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        await page.unroute('**/cgi-bin/epos/**')
        dikirim=[]
        async def sukses(r):
            dikirim.append(r.request.post_data)
            return await r.fulfill(status=200,content_type='text/xml',body='<response success="true"/>')
        await page.route('**/cgi-bin/epos/**',sukses)
        await page.locator('[data-cetak]').evaluate('(a)=>{a.click();a.click()}')
        await page.wait_for_url(lambda u:'ok=' in str(u))
        assert len(dikirim)==1 and 'epos-print' in dikirim[0]
        async with database.SessionLocal() as db:
            row=await db.scalar(select(TimbanganCetak));assert row and row.urutan==1
            petugas=await db.get(TimbanganAkun,row.oleh_id);assert petugas.username==siapa
        await page.locator('[data-cetak]').click()
        await page.wait_for_function("document.activeElement?.name==='alasan'")
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==1
        await page.locator('form[data-catat-cetak] [name=alasan]').fill('Kertas uji rusak, cetak ulang sintetis')
        await page.locator('form[data-catat-cetak] button').click()
        await page.wait_for_url(lambda u:'ok=' in str(u))
        async with database.SessionLocal() as db:
            rows=(await db.scalars(select(TimbanganCetak).order_by(TimbanganCetak.urutan))).all()
            assert len(rows)==2 and rows[-1].alasan=='Kertas uji rusak, cetak ulang sintetis'
        await browser.close()

async def test_draf_formulir_lama_tidak_kehilangan_catatan_lintasan(klien,alamat_ui):
    await master();await login(klien)
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,320)
        await buka(page,alamat_ui+'/timbangan/timbang/TRANSFER')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.locator('[name=berat_kg]').fill('10500');await page.locator('[name=nama_sopir]').fill('Sopir Lama')
        await page.wait_for_function('window.timbanganLuring.draf().then(a=>a.length===1)')
        key=await page.locator('[name=kunci]').input_value()
        await page.evaluate('''async ()=>{
          const db=await new Promise((y,n)=>{const r=indexedDB.open('timbangan-luring-v2',1);r.onsuccess=()=>y(r.result);r.onerror=()=>n(r.error)});
          await new Promise((y,n)=>{const tx=db.transaction('draf','readwrite'),s=tx.objectStore('draf'),r=s.openCursor();r.onsuccess=()=>{let c=r.result;if(c){let d=c.value;d.data=d.data.filter(p=>!['transfer_asal','transfer_tujuan','lintasan_format','pihak_nama'].includes(p[0]));d.data.push(['pihak_nama','Lintasan lama tanpa format khusus']);c.update(d);c.continue()}};tx.oncomplete=y;tx.onerror=()=>n(tx.error)});db.close();
        }''')
        await page.reload();await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.locator('[name=nama_sopir]').fill('Sopir Diperbaiki')
        await page.wait_for_function('window.timbanganLuring.draf().then(a=>a.some(d=>d.data.some(p=>p[0]==="nama_sopir"&&p[1]==="Sopir Diperbaiki")))')
        drafts=await page.evaluate('window.timbanganLuring.draf()')
        assert ['pihak_nama','Lintasan lama tanpa format khusus'] in drafts[0]['data']
        assert await page.locator('[name=kunci]').input_value()==key
        assert await page.locator('[name=berat_kg]').input_value()=='10500'
        assert await page.locator('[data-lintasan-lama]').is_visible()
        assert await page.locator('input[type=text][name=pihak_nama],textarea[name=pihak_nama]:not([readonly])').count()==0
        await page.screenshot(path=str(OUT/'draf-lintasan-lama-320.png'),full_page=True)
        await b.close()

"""UI detail asli, HTTP loopback dan DB SQLite sementara; tanpa layanan operasional."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_keluar import buat_tiket
from app import database
from app.timbangan.models import TimbanganAkun,TimbanganAudit,TimbanganTransaksi
OUT=Path(__file__).resolve().parents[3]/'output/detail-tiket-keluar-20261027'

@pytest.mark.parametrize('width,theme,role,engine',[(320,'light','operator','chromium'),(390,'dark','admin','webkit'),(390,'dark','admin','chromium'),(768,'light','super','chromium'),(1440,'light','admin','chromium'),(1440,'dark','operator','chromium')])
async def test_tab_akses_pemeriksaan_dan_layout(klien,alamat_ui,width,theme,role,engine):
    OUT.mkdir(parents=True,exist_ok=True)
    tid=await buat_tiket(beda=1000)
    if role=='super':
        async with database.SessionLocal() as db:
            a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'));a.role='SUPERADMIN';await db.commit()
    await login(klien,'budi' if role=='operator' else 'wahid')
    async with database.SessionLocal() as db:
        before=await db.scalar(select(func.count()).select_from(TimbanganAudit))
    async with async_playwright() as pw:
        browser=await getattr(pw,engine).launch();ctx=await browser.new_context(viewport={'width':width,'height':920},service_workers='block',reduced_motion='reduce',color_scheme=theme)
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()])
        await ctx.add_init_script("localStorage.setItem('pd.tema.timbang', '"+theme+"')")
        page=await ctx.new_page();errors=[];writes=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def layani(route):
            req=route.request;u=urlsplit(req.url)
            if u.hostname!='127.0.0.1':return await route.abort()
            if req.method=='POST':writes.append(u.path)
            if u.path.endswith('/aliran'):return await route.fulfill(status=204,body='')
            if u.path.endswith('/keadaan'):return await route.fulfill(json={'n':'uji-stabil','versi':'82','jumlah_tiket':0})
            return await route.continue_()
        await page.route('**/*',layani)
        kembali='/timbangan/transaksi?q=uji&halaman=2'
        await page.goto(alamat_ui+f'/timbangan/transaksi/{tid}?kembali='+__import__('urllib.parse',fromlist=['quote']).quote(kembali,safe=''))
        await page.locator('#pembuka').wait_for(state='hidden')
        assert await page.locator('.dk-pelanggan').count()==2
        assert await page.locator('.dk-barang.kg-barang').count()==4
        barang=await page.locator('.dk-barang.kg-barang').first.bounding_box()
        judul=await page.locator('.dk-barang.kg-barang h3').first.bounding_box()
        assert judul['width']>=barang['width']*.9
        assert await page.locator('.dk-kembali').get_attribute('href')==kembali
        assert await page.locator('#dk-perhitungan').is_hidden()
        for tab in ('muatan','perhitungan','jejak'):
            await page.locator(f'[data-dk-tab={tab}]').click()
            assert await page.locator(f'#dk-{tab}').is_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(OUT/f'{tab}-{width}-{theme}-{role}-{engine}.png'),full_page=True)
        if width==1440:
            assert (await page.locator('.dk').bounding_box())['width']>850
        await page.locator('[data-dk-tab=muatan]').click()
        await page.locator('[data-dk-tab=muatan]').press('ArrowRight')
        assert await page.locator('[data-dk-tab=perhitungan]').get_attribute('aria-selected')=='true'
        await page.reload();await page.locator('#pembuka').wait_for(state='hidden')
        assert await page.locator('#dk-perhitungan').is_visible()
        await page.locator('[data-buka-jejak]').click()
        assert await page.locator('#dk-jejak').is_visible()
        assert await page.locator('[data-tutup-pemeriksaan]').count()==(0 if role=='operator' else 1)
        await page.locator('.dk-lanjutan>summary').click()
        assert await page.get_by_text('Hapus permanen',exact=True).count()==(2 if role=='super' else 0)
        if role!='operator':
            await page.get_by_label('Catatan resolusi',exact=True).fill('Isian sintetis harus tetap tersimpan di formulir')
            await page.get_by_label('Kategori hasil',exact=True).select_option('LAIN')
            await page.get_by_label('Timbang ulang',exact=True).fill('Uji baca ulang')
            await page.locator('[data-dk-tab=muatan]').click()
            await page.locator('[data-dk-tab=jejak]').click()
            assert await page.get_by_label('Catatan resolusi',exact=True).input_value()=='Isian sintetis harus tetap tersimpan di formulir'
            # Putus permintaan: server tidak menerima, formulir tetap utuh.
            await page.route('**/periksa',lambda r:r.abort())
            await page.get_by_role('button',name='Tutup pemeriksaan',exact=True).click()
            await page.locator('[data-hasil-pemeriksaan]').wait_for(state='visible')
            assert await page.get_by_label('Timbang ulang',exact=True).input_value()=='Uji baca ulang'
            assert not await page.get_by_role('button',name='Tutup pemeriksaan',exact=True).is_disabled()
            await page.screenshot(path=str(OUT/f'gagal-simpan-{width}-{engine}.png'),full_page=True)
        assert not writes
        async with database.SessionLocal() as db:
            assert await db.scalar(select(func.count()).select_from(TimbanganAudit))==before
            assert (await db.get(TimbanganTransaksi,tid)).berat_barang_kg==5000
        assert not errors
        (OUT/f'hasil-{width}-{theme}-{role}-{engine}.json').write_text(json.dumps(dict(width=width,theme=theme,role=role,engine=engine,js_errors=errors,post_terkirim=writes,overflow=False,isian_terjaga=role!='operator'),indent=2))
        await page.unroute_all(behavior='wait');await browser.close()

async def test_satu_pelanggan_banyak_barang_nama_panjang(klien,alamat_ui):
    from copy import deepcopy
    from test_pengiriman_gabungan import payload
    p=payload();p['penerima']=p['penerima'][:1];nama='Pelanggan uji dengan nama panjang untuk memeriksa susunan kartu pada layar kecil'
    p['penerima'][0]['pelanggan']=nama
    m=p['muatan'][0];p['muatan']=[]
    for i in range(12):
        x=deepcopy(m);x.update(outgoing_item_id=101+i,pelanggan=nama,nama='Beras mutu medium merek dan kemasan panjang '+('IDENTITAS'*10)+str(i),jumlah=1,jumlah_karung=1,berat_kg=20,tara_per_karung_kg='.1' if i%2 else '.25')
        p['muatan'].append(x)
    tid=await buat_tiket(data=p)
    await login(klien)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx=await browser.new_context(viewport={'width':320,'height':900},service_workers='block')
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()])
        page=await ctx.new_page()
        await page.goto(alamat_ui+f'/timbangan/transaksi/{tid}');await page.locator('#pembuka').wait_for(state='hidden')
        assert await page.locator('.dk-pelanggan').count()==1
        assert await page.locator('.kg-barang').count()==12
        assert '1 pelanggan · 12 baris barang' in await page.locator('.dk-hero').inner_text()
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path=str(OUT/'satu-pelanggan-12-barang-320.png'),full_page=True)
        await browser.close()

@pytest.mark.parametrize('role',['operator','admin','super'])
async def test_tindakan_lama_gagal_tetap_utuh_dan_kirim_ganda_ditahan(klien,alamat_ui,monkeypatch,role):
    from app.timbangan import klien_produksi
    async def putus(*args):raise klien_produksi.ProduksiTakTersedia('Muatan uji tidak tersedia')
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',putus)
    tid=await buat_tiket(selesai=role!='operator')
    async with database.SessionLocal() as db:
        kode=(await db.get(TimbanganTransaksi,tid)).kode
        if role=='super':
            a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'));a.role='SUPERADMIN';await db.commit()
    await login(klien,'budi' if role=='operator' else 'wahid')
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx=await browser.new_context(viewport={'width':390,'height':900},service_workers='block',reduced_motion='reduce')
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()])
        page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(alamat_ui+f'/timbangan/transaksi/{tid}');await page.locator('#pembuka').wait_for(state='hidden')
        await page.locator('.dk-lanjutan>summary').click()
        aksi='hapus' if role=='super' else 'batal'
        form=page.locator(f'.dk-lanjutan form[action$="/{aksi}"]')
        await form.locator('..').locator('summary').click()
        await form.locator('[name=alasan]').fill('Alasan sintetis untuk uji aman')
        if role=='super':await form.locator('[name=ketik_kode]').fill('SALAH-UJI')
        else:await form.locator('[name=alasan]').fill(' ')
        # Kegagalan validasi server, bukan simulasi sukses browser.
        await form.locator('button[type=submit]').click()
        await form.locator('[role=alert]').wait_for(state='visible')
        assert urlsplit(page.url).path==f'/timbangan/transaksi/{tid}'
        assert await form.locator('[name=alasan]').input_value()==('Alasan sintetis untuk uji aman' if role=='super' else ' ')
        async with database.SessionLocal() as db:
            assert (await db.get(TimbanganTransaksi,tid)).status_transaksi!='VOID'
        await form.locator('[name=alasan]').fill('Alasan sintetis untuk uji aman')
        if role=='super':await form.locator('[name=ketik_kode]').fill(kode)
        # Putus jaringan tetap mempertahankan isian dan belum mengubah tiket.
        await page.route(f'**/transaksi/{tid}/{aksi}',lambda r:r.abort())
        await form.locator('button[type=submit]').click()
        await page.wait_for_function("document.querySelector('.dk-lanjutan [role=alert]:not([hidden])')?.textContent.includes('belum terkonfirmasi')")
        assert await form.locator('[name=alasan]').input_value()=='Alasan sintetis untuk uji aman'
        await page.unroute(f'**/transaksi/{tid}/{aksi}')
        terkirim=[]
        page.on('request',lambda r:terkirim.append(r.url) if r.method=='POST' and r.url.endswith('/'+aksi) else None)
        await form.evaluate('(f)=>{f.requestSubmit();f.requestSubmit()}')
        await page.wait_for_url(lambda u:'ok=' in str(u))
        assert len(terkirim)==1
        async with database.SessionLocal() as db:
            trx=await db.get(TimbanganTransaksi,tid)
            assert trx is None if role=='super' else trx.status_transaksi=='VOID'
        assert not errors
        await browser.close()

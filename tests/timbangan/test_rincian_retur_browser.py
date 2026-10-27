"""Browser aplikasi asli pada HTTP loopback, data sintetis dan DB sementara."""
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_retur import tiket,tautkan,sumber
from hmu_identitas import peran as P
from app import database
from app.timbangan.models import TimbanganAudit,TimbanganTransaksi,TimbanganAkun
OUT=Path(__file__).resolve().parents[3]/'output/detail-tiket-retur-20261027'

@pytest.mark.parametrize('width,theme,role',[(320,'light',P.OPERATOR),(390,'light',P.ADMIN),(390,'dark',P.SUPERADMIN),(768,'light',P.ADMIN),(1440,'light',P.ADMIN),(1440,'dark',P.OPERATOR)])
async def test_tab_tampilan_akses_dan_gagal_simpan(klien,monkeypatch,alamat_ui,width,theme,role):
    OUT.mkdir(parents=True,exist_ok=True)
    tid=await tiket(acuan=50)
    siapa='budi' if role==P.OPERATOR else 'wahid'
    await tautkan(siapa,role);await sumber(monkeypatch,tid)
    if role==P.OPERATOR:
        from app.timbangan import klien_produksi
        async def ditolak(*a,**kw):raise klien_produksi.ProduksiDilarang('Uji izin')
        monkeypatch.setattr(klien_produksi,'detail_retur',ditolak)
    await login(klien,siapa)
    async with database.SessionLocal() as db:before=await db.scalar(select(func.count()).select_from(TimbanganAudit))
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        ctx=await browser.new_context(viewport={'width':width,'height':920},service_workers='block',reduced_motion='reduce',color_scheme=theme)
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()])
        await ctx.add_init_script("localStorage.setItem('pd.tema.timbang', '"+theme+"')")
        page=await ctx.new_page();errors=[];writes=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def route(r):
            u=urlsplit(r.request.url)
            if u.hostname!='127.0.0.1':return await r.abort()
            if r.request.method=='POST':writes.append(u.path)
            if u.path.endswith('/aliran'):return await r.fulfill(status=204,body='')
            if u.path.endswith('/keadaan'):return await r.fulfill(json={'n':'uji-stabil','versi':'82','jumlah_tiket':0})
            return await r.continue_()
        await page.route('**/*',route)
        await page.goto(alamat_ui+f'/timbangan/transaksi/{tid}?kembali=/timbangan/transaksi%3Fhal=2')
        await page.locator('#pembuka').wait_for(state='hidden')
        assert await page.locator('.dk-kembali').get_attribute('href')=='/timbangan/transaksi?hal=2'
        for tab in ('ringkasan','perhitungan','jejak'):
            await page.locator(f'[data-dk-tab={tab}]').click()
            assert await page.locator(f'#dk-{tab}').is_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(OUT/f'{tab}-{width}-{theme}-{role}.png'),full_page=True)
        await page.locator('[data-dk-tab=ringkasan]').click()
        await page.locator('[data-dk-tab=ringkasan]').press('ArrowRight')
        assert await page.locator('[data-dk-tab=perhitungan]').get_attribute('aria-selected')=='true'
        await page.reload();await page.locator('#pembuka').wait_for(state='hidden')
        assert await page.locator('#dk-perhitungan').is_visible()
        await page.locator('[data-buka-jejak]').click()
        assert await page.locator('#dk-jejak').is_visible()
        assert await page.locator('[data-tutup-pemeriksaan]').count()==int(P.admin_keatas(role))
        if P.admin_keatas(role):
            await page.get_by_label('Catatan resolusi',exact=True).fill('Isian uji dipertahankan saat jaringan putus')
            await page.get_by_label('Kategori hasil',exact=True).select_option('LAIN')
            await page.route('**/periksa',lambda r:r.abort())
            await page.get_by_role('button',name='Tutup pemeriksaan',exact=True).click()
            await page.locator('[data-hasil-pemeriksaan]').wait_for(state='visible')
            assert await page.get_by_label('Catatan resolusi',exact=True).input_value()=='Isian uji dipertahankan saat jaringan putus'
            assert not await page.get_by_role('button',name='Tutup pemeriksaan',exact=True).is_disabled()
        assert not writes and not errors
        await browser.close()
    async with database.SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit))==before
        assert (await db.get(TimbanganTransaksi,tid)).berat_barang_kg==70.1

@pytest.mark.parametrize('role',['operator','admin','super'])
async def test_tindakan_retur_gagal_dan_kirim_ganda_ditahan(klien,alamat_ui,monkeypatch,role):
    from app.timbangan import klien_produksi
    async def putus(*args,**kw):raise klien_produksi.ProduksiTakTersedia('Muatan uji tidak tersedia')
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',putus)
    tid=await tiket(selesai=role!='operator')
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

async def test_banyak_barang_nama_panjang_320(klien,monkeypatch,alamat_ui):
    from copy import deepcopy
    from app.timbangan import klien_produksi
    tid=await tiket();await tautkan();data=await sumber(monkeypatch,tid)
    data['muatan']=[dict(deepcopy(data['muatan'][i%2]),nama='Nama barang sangat panjang '+('Produk retur pelanggan '*6),outgoing_item_id=1000+i) for i in range(12)]
    async def baca(*a,**kw):return data
    monkeypatch.setattr(klien_produksi,'detail_retur',baca)
    await login(klien,'wahid')
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();ctx=await browser.new_context(viewport={'width':320,'height':900},service_workers='block',reduced_motion='reduce')
        await ctx.add_cookies([{'name':k,'value':v,'url':alamat_ui} for k,v in klien.cookies.items()])
        page=await ctx.new_page()
        await page.goto(alamat_ui+f'/timbangan/transaksi/{tid}');await page.locator('#pembuka').wait_for(state='hidden')
        assert await page.locator('#dk-ringkasan .dk-barang').count()==12
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path=str(OUT/'12-barang-nama-panjang-320.png'),full_page=True)
        await browser.close()

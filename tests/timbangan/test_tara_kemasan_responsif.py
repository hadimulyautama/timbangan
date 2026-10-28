"""Master kemasan pada UI/HTTP asli; SQLite baru per kasus, jaringan localhost saja."""
import os
from pathlib import Path
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import text, select, func
from test_web import app_uji, klien, login, _jadi_super, _master_tara_kemasan
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji as browser_desktop, buka
from test_pengaturan_kategori import produksi_terpisah
from app import database
from app.timbangan.models import TimbanganAudit

OUT=Path(os.environ.get('UJI_PENGATURAN_OUT','/tmp/pengaturan-final'))

async def browser_uji(pw,klien,alamat,width=390,theme='light',browser='chromium'):
    if not os.environ.get('UJI_IOS') or width>=900:
        return await browser_desktop(pw,klien,alamat,width,theme,browser=browser)
    b=await getattr(pw,browser).launch()
    ctx=await b.new_context(viewport={'width':width,'height':920},is_mobile=True,has_touch=True,
        user_agent=pw.devices['iPhone 13']['user_agent'],service_workers='block',color_scheme=theme,reduced_motion='reduce')
    await ctx.add_cookies([{'name':k,'value':v,'url':alamat} for k,v in klien.cookies.items()])
    await ctx.add_init_script("localStorage.setItem('pd.tema.timbang', '"+theme+"')")
    async def batasi(r):
        u=urlsplit(r.request.url)
        if u.hostname!='127.0.0.1':return await r.abort()
        if u.path.endswith('/aliran'):return await r.fulfill(status=204,body='')
        if u.path.endswith('/keadaan'):return await r.fulfill(json={'n':'uji','versi':'94','jumlah_tiket':0})
        return await r.continue_()
    await ctx.route('**/*',batasi)
    return b,ctx,await ctx.new_page()

async def master_banyak():
    await _master_tara_kemasan()
    async with database.SessionLocal() as db:
        await db.execute(text("UPDATE packaging_materials SET nama=:nama WHERE id=1"),{'nama':'Karung laminasi panjang untuk muatan uji dengan identitas yang tidak boleh terpotong'})
        # Beberapa ukuran nyata dari fixture; bukan tiga contoh hardcode pada UI.
        for i in range(2,7):
            await db.execute(text('INSERT INTO package_sizes (id,ukuran_kg,aktif) VALUES (:id,:ukuran,true)'),{'id':i,'ukuran':i*10})
            await db.execute(text('INSERT INTO kemasan_tara VALUES (:id,1,:id,:nilai,CURRENT_TIMESTAMP)'),{'id':i,'nilai':.07 if i==2 else .0858})
        await db.execute(text('UPDATE kemasan_tara SET tara_per_karung_kg=999.1234 WHERE id=1'))
        await db.commit()

async def rekam():
    async with database.SessionLocal() as db:
        return dict((await db.execute(text('SELECT id,tara_per_karung_kg FROM kemasan_tara ORDER BY id'))).all())

@pytest.mark.parametrize('width,theme',[(320,'light'),(390,'dark'),(430,'light'),(1440,'light')])
async def test_layout_gram_presisi_keyboard(klien,alamat_ui,width,theme):
    await master_banyak();await login(klien,'wahid');before=await rekam()
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,theme,browser=os.environ.get('UJI_BROWSER','chromium'))
        errors=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        await buka(page,alamat_ui+'/timbangan/pengaturan?bagian=aturan')
        assert await page.locator('.set-tara').count()==6
        assert await page.locator('#kemasan-1 input[name=tara_per_karung_kg]').input_value()=='999.1234'
        for f in await page.locator('.set-tara').all():
            input=f.locator('[name=tara_per_karung_kg]');button=f.locator('button')
            a=await input.bounding_box();c=await button.bounding_box();h=await f.locator('.set-tara__nama').bounding_box()
            assert abs(a['y']-c['y'])<1 and abs(a['height']-c['height'])<1
            assert h['y']+h['height']<=a['y']
            assert float(await input.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)'))>=16
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        inp=page.locator('#kemasan-2 [name=tara_per_karung_kg]');gram=page.locator('#gram-kemasan-2')
        for value,expected in [('0,05','50'),('0.07','70'),('0,0858','85,8'),('0.0001','0,1'),('0','0'),('1.000','1.000'),('7e-2','70'),('999.1234','999.123,4')]:
            await inp.fill(value)
            assert await gram.inner_text()==expected+' gram per karung'
            assert await inp.input_value()==value
        for value in ['abc','NaN','Infinity','1.2.3','']:
            await inp.fill(value);assert await gram.inner_text()=='Padanan gram belum tersedia.'
        await inp.fill('0,07');await inp.focus();await page.keyboard.press('Alt+Tab' if os.environ.get('UJI_BROWSER')=='webkit' else 'Tab')
        assert await page.locator('#kemasan-2 button').evaluate('(e)=>e===document.activeElement')
        assert await page.locator('#kemasan-2 button').evaluate('(e)=>getComputedStyle(e).outlineStyle')!='none'
        await page.locator('.set-tara__bantuan summary').press('Enter')
        assert await page.locator('.set-tara__bantuan').get_attribute('open') is not None
        await page.locator('#kemasan-6 button').scroll_into_view_if_needed()
        rect=await page.locator('#kemasan-6 button').bounding_box();nav=await page.locator('.bawah').bounding_box()
        if nav and width < 900: assert rect['y']+rect['height']<=nav['y']
        OUT.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(OUT/f'tara-{width}-{theme}-{os.environ.get("UJI_BROWSER","chromium")}.png'),full_page=True)
        assert not posts and not errors
        assert await rekam()==before
        await b.close()

async def test_simpan_per_record_gagal_dan_refresh(klien,alamat_ui):
    await master_banyak();await login(klien,'wahid');before=await rekam()
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,390,browser=os.environ.get('UJI_BROWSER','chromium'))
        await buka(page,alamat_ui+'/timbangan/pengaturan?bagian=aturan');posts=[]
        page.on('request',lambda r:posts.append(r.post_data) if r.method=='POST' else None)
        f=page.locator('#kemasan-2')
        await f.locator('input[name=tara_per_karung_kg]').fill('0,0858');await f.locator('button').click()
        await page.wait_for_url(lambda u:'ok=' in str(u))
        assert 'tara_id=2' in page.url
        assert 'tersimpan' in await f.locator('[role=status]').inner_text()
        assert await page.locator('.set-tara [role=status]').count()==1
        assert parse_qs(posts[0])=={'tara_id':['2'],'tara_per_karung_kg':['0,0858']}
        after=await rekam();assert after[2]==.0858 and {k:v for k,v in after.items() if k!=2}=={k:v for k,v in before.items() if k!=2}
        await page.reload();assert len(posts)==1
        await f.locator('input[name=tara_per_karung_kg]').fill('0.00001');await f.locator('button').click()
        await page.wait_for_url(lambda u:'err=' in str(u))
        assert 'empat angka desimal' in await f.locator('[role=alert]').inner_text()
        assert await page.locator('.set-tara [role=status]').count()==0 and await rekam()==after
        async with database.SessionLocal() as db:
            rows=(await db.scalars(select(TimbanganAudit).where(TimbanganAudit.aksi=='UBAH_TARA_KEMASAN'))).all()
            assert len(rows)==1 and rows[0].entitas_id=='2'
        await b.close()

@pytest.mark.parametrize('who,allowed',[('budi',False),('wahid',True),('miftah',True)])
async def test_akses_record_server(klien,app_uji,who,allowed):
    await master_banyak();await _jadi_super(app_uji,'miftah');await login(klien,who)
    r=await klien.get('/timbangan/pengaturan?bagian=aturan')
    assert ('data-set-tara' in r.text)==allowed
    r=await klien.post('/timbangan/pengaturan/tara-kemasan',data={'tara_id':'3','tara_per_karung_kg':'0'})
    assert r.status_code==(200 if allowed else 403)
    values=await rekam();assert values[3]==(0 if allowed else .0858)

@pytest.mark.parametrize('value,valid',[('0',True),('0,0858',True),('1000',True),('1.000',True),('7e-2',True),('0.0001',True),('0.00001',False),('-1',False),('1000.0001',False),('NaN',False),('Infinity',False),('1.2.3',False)])
async def test_parsing_batas_lama(klien,value,valid):
    await _master_tara_kemasan();await login(klien,'wahid')
    r=await klien.post('/timbangan/pengaturan/tara-kemasan',data={'tara_id':'1','tara_per_karung_kg':value})
    assert ('ok=' in str(r.url))==valid
    assert Decimal(str((await rekam())[1]))==(Decimal(value.replace(',','.')) if valid else Decimal('.08'))

async def test_peringatan_skema_bukan_untuk_operator(klien,monkeypatch):
    from app.timbangan.routes import master
    async def info():return dict(versi='uji',komit='uji',revisi='lama',head='skema-baru-uji',keadaan='tertinggal')
    monkeypatch.setattr(master._versi,'info',info)
    for who in ['budi','wahid']:
        await login(klien,who)
        r=await klien.get('/timbangan/pengaturan?bagian=sistem')
        assert 'Versi uji' in r.text
        assert ('(kode: skema-baru-uji)' in r.text)==(who=='wahid')

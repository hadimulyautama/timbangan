"""Draf dibuka dan dihapus lewat UI asli, data SQLite/IndexedDB uji saja."""
import os,asyncio,copy
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from test_formulir import tiket_uji
from app import database
from app.timbangan.models import TimbanganTransaksi

async def siap(page):
    await page.wait_for_function('window.timbanganLuring&&window.timbanganLuring.siap()')

async def tunggu_draf(page,teks):
    await page.wait_for_function("async teks=>(await window.timbanganLuring.draf()).some(x=>x.data.some(p=>p[1]===teks))",arg=teks)
    return await page.evaluate('window.timbanganLuring.draf()')

@pytest.mark.parametrize('width',[1440,393,320])
@pytest.mark.parametrize('jenis',['pertama','jasa','kedua'])
async def test_pulihkan_tab_lain_dan_hapus_terpilih(klien,alamat_ui,width,jenis):
    await login(klien,'wahid')
    if jenis=='kedua':tid=await tiket_uji('MASUK','GABAH_BASAH');path=f'/timbangan/tiket/{tid}'
    else:path='/timbangan/'+('jasa' if jenis=='jasa' else 'timbang')+'/GABAH_BASAH'
    async with database.SessionLocal() as db:before=await db.scalar(select(func.count()).select_from(TimbanganTransaksi))
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,width,'dark' if width==393 else 'light');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await buka(page,alamat_ui+path);await siap(page)
        await page.locator('[name=berat_kg]').fill('12.345,67')
        if jenis!='kedua':
            await page.locator('[name=nomor_polisi]').fill('B 9876 UJ')
            await page.locator('[name=nama_sopir]').fill('Sopir Draf Uji')
        await page.locator('[name=jumlah_karung]').evaluate('e=>{for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==="DETAILS")p.open=true}')
        await page.locator('[name=jumlah_karung]').fill('17')
        await page.locator('[name=tara_per_karung_kg]').fill('0,0858')
        drafts=await tunggu_draf(page,'0,0858');assert len(drafts)==1
        asli=drafts[0];data=await page.locator('form[data-simpan-luring]').evaluate('f=>Array.from(new FormData(f).entries())')
        await page.goto(alamat_ui+'/timbangan/tiket');await siap(page)
        row=page.locator('[data-draf-id]');await row.wait_for()
        link=row.get_by_role('link',name='Pulihkan draf',exact=False);hapus=row.get_by_role('button',name='Hapus draf',exact=True)
        posisi=await row.evaluate("e=>{const a=e.querySelector('a').getBoundingClientRect(),b=e.querySelector('button').getBoundingClientRect();return {link:a.right,hapus:b.left,jarak:Math.abs(a.top+a.height/2-b.top-b.height/2)}}")
        assert posisi['hapus']>=posisi['link'] and posisi['jarak']<=10
        out=Path(os.environ['UJI_DRAF_OUT']);out.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(out/f'draf-{jenis}-{width}.png'),full_page=True)
        href=await link.get_attribute('href')
        # Tab baru memakai sessionStorage/lease baru, tetapi tetap draf yang sama.
        p=await ctx.new_page();p.on('pageerror',lambda e:errors.append(str(e)))
        await p.route('https://fonts.googleapis.com/**',lambda r:r.abort());await p.route('https://fonts.gstatic.com/**',lambda r:r.abort())
        await p.goto(alamat_ui+href);await siap(p)
        restored=await p.locator('form[data-simpan-luring]').evaluate('f=>Array.from(new FormData(f).entries())')
        assert restored==data
        assert await p.locator('form[data-simpan-luring]').evaluate('f=>f._luringDrafId')==asli['id']
        if jenis=='jasa':assert '/jasa/' in p.url and 'JASA' in await p.locator('.tp-context').text_content()
        await p.locator('[name=jumlah_karung]').evaluate('e=>{for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==="DETAILS")p.open=true}')
        await p.locator('[name=jumlah_karung]').fill('19');drafts=await tunggu_draf(p,'19')
        assert len(drafts)==1 and drafts[0]['id']==asli['id']
        await p.goto(alamat_ui+'/timbangan/tiket');await siap(p)
        await p.locator('[data-hapus-draf]').click();await p.get_by_role('button',name='Batal',exact=True).click()
        assert len(await p.evaluate('window.timbanganLuring.draf()'))==1
        await p.locator('[data-hapus-draf]').click();await p.locator('[data-draf-ya]').click()
        await p.wait_for_function('async()=>(await window.timbanganLuring.draf()).length===0')
        assert await p.locator('[data-draf-id]').count()==0
        assert await p.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==before
        await b.close()

async def simpan_db(page,store,rows):
    await page.evaluate("""async ({store,rows}) => {const db=await new Promise((ok,no)=>{const r=indexedDB.open('timbangan-luring-v2',1);r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});await new Promise((ok,no)=>{const tx=db.transaction(store,'readwrite');rows.forEach(row=>tx.objectStore(store).put(row));tx.oncomplete=ok;tx.onerror=()=>no(tx.error)});db.close()}""",{'store':store,'rows':rows})

async def awal(page,alamat):
    await buka(page,alamat+'/timbangan/timbang/GABAH_BASAH');await siap(page)
    await page.locator('[name=berat_kg]').fill('9.876,54')
    return (await tunggu_draf(page,'9.876,54'))[0]

@pytest.mark.parametrize('kasus',['pilihan','berubah','kiriman','aktif','tab_lama'])
async def test_penghapusan_aman_dan_formulir_lama(klien,alamat_ui,kasus):
    await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui,393)
        asli=await awal(page,alamat_ui)
        if kasus=='tab_lama':
            p=await ctx.new_page();await p.goto(alamat_ui+'/timbangan/tiket');await siap(p)
            await p.locator('[data-hapus-draf]').click();await p.locator('[data-draf-ya]').click()
            await p.wait_for_function('async()=>(await window.timbanganLuring.draf()).length===0')
            # Tab yang masih memegang isian lama tidak boleh menghidupkan draf lagi.
            await page.locator('[name=berat_kg]').fill('8.000')
            await page.wait_for_function("document.querySelector('form[data-simpan-luring]').inert")
            assert await page.evaluate('window.timbanganLuring.draf()')==[]
            await page.locator('form[data-simpan-luring]').evaluate("f=>f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            assert await page.evaluate('window.timbanganLuring.antrean()')==[]
            await b.close();return
        if kasus=='pilihan':
            lain=copy.deepcopy(asli);lain.update(id=asli['id']+'-lain',kunci='11111111-1111-4111-8111-111111111111',label='Draf lain tetap utuh')
            asing=copy.deepcopy(asli);asing.update(id='akun-lain:draf',akun='akun-lain',label='Draf akun lain')
            await simpan_db(page,'draf',[lain,asing])
        if kasus!='aktif':await page.goto(alamat_ui+'/timbangan/tiket');await siap(page)
        row=page.locator('[data-draf-id]').filter(has_text=asli['label']);await row.locator('[data-hapus-draf]').click()
        if kasus=='berubah':
            baru=copy.deepcopy(asli);baru['data'].append(['uji_tab_lain','Berubah setelah konfirmasi dibuka']);await simpan_db(page,'draf',[baru])
        if kasus=='kiriman':
            q={'akun':asli['akun'],'kunci':asli['kunci'],'drafId':asli['id'],'jalur':asli['jalur'],'label':'Kiriman dilindungi','status':'periksa','data':asli['data']}
            await simpan_db(page,'kiriman',[q])
        await page.locator('[data-draf-ya]').click()
        if kasus in ('berubah','kiriman'):
            await page.locator('[data-draf-galat]').wait_for(state='visible')
            assert len(await page.evaluate('window.timbanganLuring.draf()'))==1
            if kasus=='kiriman':assert (await page.evaluate('window.timbanganLuring.antrean()'))[0]==q
        elif kasus=='aktif':
            await page.wait_for_url('**/timbang/GABAH_BASAH');await siap(page)
            await page.wait_for_function("document.querySelector('[name=berat_kg]').value===''")
            assert await page.evaluate('window.timbanganLuring.draf()')==[]
        else:
            await page.wait_for_function('async()=>(await window.timbanganLuring.draf()).length===2')
            assert sorted(await page.evaluate('window.timbanganLuring.draf()'),key=lambda x:x['id'])==sorted([lain,asing],key=lambda x:x['id'])
        await b.close()

async def test_pulihkan_draf_lain_pada_halaman_yang_sama(klien,alamat_ui):
    await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        asli=await awal(page,alamat_ui);lain=copy.deepcopy(asli)
        lain.update(id=asli['id']+'-pilihan',label='Draf kedua pada formulir sama',kunci='11111111-1111-4111-8111-111111111111')
        lain['data']=[[k,('7.654,32' if k=='berat_kg' else lain['kunci'] if k=='kunci' else v)] for k,v in lain['data']]
        await simpan_db(page,'draf',[lain]);await page.reload();await siap(page)
        await page.locator('[data-draf-id]').filter(has_text=lain['label']).get_by_role('link',name='Pulihkan draf',exact=False).click()
        await page.wait_for_function("document.querySelector('[name=berat_kg]')?.value==='7.654,32'")
        await siap(page)
        assert await page.locator('form[data-simpan-luring]').evaluate('f=>f._luringDrafId')==lain['id']
        assert len(await page.evaluate('window.timbanganLuring.draf()'))==2
        await b.close()

async def test_draf_partai_memulihkan_semua_baris_berat(klien,alamat_ui):
    await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+'/timbangan/partai/GABAH_BASAH/baru');await siap(page)
        await page.locator('[name=berat_kg]').fill('125,25');await page.locator('#tambah-berat').click()
        await page.locator('[name=berat_kg]').nth(1).fill('84,75');await page.locator('[name=jumlah_karung]').fill('5')
        draft=(await tunggu_draf(page,'84,75'))[0]
        data=await page.locator('form[data-simpan-luring]').evaluate('f=>Array.from(new FormData(f).entries())')
        p=await ctx.new_page();await p.route('https://fonts.googleapis.com/**',lambda r:r.abort());await p.route('https://fonts.gstatic.com/**',lambda r:r.abort())
        await p.goto(alamat_ui+draft['jalur']+'#draf='+__import__('urllib.parse',fromlist=['quote']).quote(draft['id'],safe=''));await siap(p)
        assert await p.locator('[name=berat_kg]').count()==2
        assert await p.locator('form[data-simpan-luring]').evaluate('f=>Array.from(new FormData(f).entries())')==data
        await b.close()

async def test_pulih_lalu_simpan_membersihkan_draf_asal(klien,alamat_ui):
    await login(klien,'wahid')
    async with async_playwright() as pw:
        b,ctx,page=await browser_uji(pw,klien,alamat_ui)
        await buka(page,alamat_ui+'/timbangan/timbang/GABAH_BASAH');await siap(page)
        await page.locator('[name=berat_kg]').fill('15000')
        await page.locator('[name=nomor_polisi]').fill('B 1234 UJ');await page.locator('[name=nama_sopir]').fill('Sopir Uji')
        await page.locator('select[name=supplier_id]').evaluate("e=>{e.value='1';e.dispatchEvent(new Event('change',{bubbles:true}))}")
        await page.locator('[name=nama_sopir]').fill('Sopir Draf Siap Simpan')
        draft=(await tunggu_draf(page,'Sopir Draf Siap Simpan'))[0]
        p=await ctx.new_page();await p.route('https://fonts.googleapis.com/**',lambda r:r.abort());await p.route('https://fonts.gstatic.com/**',lambda r:r.abort())
        await p.goto(alamat_ui+draft['jalur']+'#draf='+__import__('urllib.parse',fromlist=['quote']).quote(draft['id'],safe=''));await siap(p)
        await p.locator('form[data-simpan-luring] button[type=submit]').click()
        await p.wait_for_function("location.pathname.startsWith('/timbangan/transaksi/')",timeout=15000);await siap(p)
        assert await p.evaluate('window.timbanganLuring.draf()')==[]
        async with database.SessionLocal() as db:
            rows=list(await db.scalars(select(TimbanganTransaksi)))
            assert len(rows)==1 and rows[0].nama_sopir=='Sopir Draf Siap Simpan' and float(rows[0].timbang1_kg)==15000
        await b.close()

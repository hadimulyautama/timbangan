"""Formulir retur curah dapat disimpan tanpa karung fiktif di ponsel/desktop."""
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright,expect
from sqlalchemy import select
from app import database
from app.timbangan.models import TimbanganTransaksi
from test_web import app_uji,klien,login
from test_retur_curah_karung import tiket,tautan_kg

@pytest.mark.parametrize('width',[390,1440])
async def test_form_curah_pratinjau_simpan_dan_antrean_tidak_macet(klien,width):
    tid=await tiket(selesai=False)
    async with database.SessionLocal() as db:await tautan_kg(db,tid)
    await login(klien)
    async with async_playwright() as p:
        b=await p.chromium.launch()
        page=await b.new_page(viewport=dict(width=width,height=950),service_workers='block',reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        async def layani(route):
            req=route.request;u=urlsplit(req.url)
            if u.hostname!='uji':return await route.abort()
            r=await klien.request(req.method,u.path+('?' +u.query if u.query else ''),content=req.post_data_buffer,headers={k:v for k,v in req.headers.items() if k.lower() in ['content-type','x-timbangan-kiriman','x-timbangan-akun','x-timbangan-waktu','x-timbangan-luring']})
            await route.fulfill(status=r.status_code,headers={'content-type':r.headers.get('content-type','text/html')},body=r.content)
        await page.route('**/*',layani)
        await page.goto(f'http://uji/timbangan/tiket/{tid}')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.locator('#pembuka').wait_for(state='detached')
        await expect(page.locator('[name="jumlah_karung"]')).to_have_count(0)
        await page.locator('[name="berat_kg"]').fill('6570')
        await page.locator('[name="berat_kg"]').blur()
        await expect(page.locator('[data-fw-hasil]')).to_contain_text('70',timeout=10000)
        await page.get_by_role('button',name='Selesaikan penimbangan',exact=True).click()
        await page.wait_for_url(lambda u:'/transaksi/' in str(u),timeout=15000)
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid)
            assert t.status_tiket=='SELESAI' and t.berat_barang_kg==70 and t.jumlah_karung==0
        assert not errors
        await b.close()

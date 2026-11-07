"""Rekap asli melalui HTTP lokal dan SQLite sintetis, tanpa data operasional."""
from pathlib import Path
from datetime import timedelta
import csv,io
import pytest
from playwright.async_api import async_playwright
from sqlalchemy import select
from test_web import app_uji,klien,login  # noqa: F401
from test_timbang_pertama_desain_browser import lokal,halaman as halaman_asli  # noqa: F401
from test_laporan import seed
from app import database
from app.timbangan.db import hari_ini
from app.timbangan.models import TimbanganPemeriksaan
OUT=Path(__file__).resolve().parents[3]/'gambar'

async def halaman(*args,**kwargs):
    ctx,page=await halaman_asli(*args,**kwargs);await page.emulate_media(reduced_motion='reduce');return ctx,page

@pytest.mark.parametrize('width',[320,390,1440])
async def test_kontrol_angka_tautan_unduhan_dan_periode(lokal,width):
    url,client=lokal;await seed(client);day=str(hari_ini())
    async with async_playwright() as pw:
        b=await pw.chromium.launch();ctx,page=await halaman(b,url,client,width)
        if width==390:await ctx.add_init_script("localStorage.setItem('pd.tema.timbang','dark')")
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(f'{url}/timbangan/laporan?tab=rekap&dari={day}&sampai={day}')
        await page.locator('[data-lr-guide]').wait_for(state='visible')
        root=page.locator('[data-rekap-desain]');form=root.locator('form')
        assert await root.locator('[data-ringkasan]').count()==5
        assert await root.locator('[data-ringkasan=jumlah] strong').inner_text()=='13'
        assert await root.locator('[data-ringkasan=terbuka] strong').inner_text()=='6'
        assert await root.locator('[data-ringkasan=batas] strong').inner_text()=='4'
        assert await root.locator('[data-laporan-id]').count()==4
        assert '3 lembar' in await root.locator('.lp-urgent').inner_text()
        assert await root.get_by_role('link',name='Riwayat Timbang',exact=True).count()==0
        assert await root.locator('[data-lr-period]').evaluate('e=>e.open')==(width>650)
        before=await form.evaluate('e=>Array.from(new FormData(e).entries())')
        await root.locator('[data-lr-guide]').click();assert await root.locator('#lr-panduan').evaluate('e=>e.open');await page.keyboard.press('Escape')
        assert before==await form.evaluate('e=>Array.from(new FormData(e).entries())')
        async with page.expect_download() as download:
            await root.get_by_role('link',name='Unduh CSV',exact=True).click()
        rows=list(csv.reader(io.StringIO(Path(await (await download.value).path()).read_text(encoding='utf-8-sig'))))
        assert len(rows)==14  # 13 transaksi aktif dan satu header.
        assert 'tab=rekap' in page.url
        # Lembar dari tanggal lama tetap terlihat di tab Pemeriksaan.
        await root.locator('.lp-urgent a').click();await page.wait_for_url(lambda u:'tab=pemeriksaan' in str(u))
        assert await page.locator('[data-laporan-id]').count()==3
        await page.get_by_role('link',name='Rekap',exact=True).click();await page.wait_for_url(lambda u:'tab=rekap' in str(u))
        assert await root.locator('[data-laporan-id]').count()==4
        OUT.mkdir(parents=True,exist_ok=True);await page.screenshot(path=str(OUT/f'rekap-{width}.png'),full_page=True)
        if not await root.locator('[data-lr-period]').evaluate('e=>e.open'):await root.locator('[data-lr-period]>summary').click()
        tomorrow=str(hari_ini()+timedelta(days=1))
        await form.locator('[name=dari]').fill(tomorrow);await form.locator('[name=sampai]').fill(day)
        assert await form.locator('[name=sampai]').evaluate('e=>!e.checkValidity()')
        await form.locator('[name=sampai]').fill(tomorrow);await form.get_by_role('button',name='Terapkan periode').click()
        await page.wait_for_url(lambda u:'dari='+tomorrow in str(u))
        assert await root.locator('[data-ringkasan=jumlah] strong').inner_text()=='0'
        assert await root.locator('[data-laporan-id]').count()==0
        assert '3 lembar' in await root.locator('.lp-urgent').inner_text()
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        await ctx.close();await b.close()

async def test_tanpa_js_dan_pemeriksaan_selesai_tidak_menghapus_selisih(lokal):
    url,client=lokal;await seed(client)
    async with async_playwright() as pw:
        b=await pw.chromium.launch();ctx,page=await halaman(b,url,client,390,False)
        await page.goto(url+'/timbangan/laporan?tab=rekap')
        assert await page.locator('[data-lr-period]').evaluate('e=>e.open')
        await page.locator('[data-lr-guide-fallback]>summary').evaluate('e=>e.scrollIntoView({block:"center"})')
        await page.locator('[data-lr-guide-fallback]>summary').click();assert await page.locator('[data-lr-guide-content]').is_visible()
        await ctx.close();await b.close()
    async with database.SessionLocal() as db:
        for exam in (await db.scalars(select(TimbanganPemeriksaan))).all():
            exam.status='SELESAI';exam.kategori_hasil='LAIN';exam.catatan_resolusi='Catatan fixture selesai'
        await db.commit()
    response=await client.get('/timbangan/laporan?tab=rekap')
    assert response.status_code==200
    assert 'lp-urgent' not in response.text
    assert 'Semua pemeriksaan sudah ditutup.' in response.text
    assert response.text.count('data-laporan-id=')==4

"""Pilihan sopir menyaring nama utama dan tetap menerima nama baru."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect
from sqlalchemy import func, select

from app import database
from app.timbangan.models import TimbanganSopir, TimbanganSopirAlias, TimbanganTransaksi
from app.timbangan.sopir import nama_utama, daftar_pilihan
from test_web import app_uji, klien, login  # noqa: F401

OUT = Path(__file__).parents[3] / 'output/sopir-pilihan-20261025'


async def semai():
    async with database.SessionLocal() as db:
        for nama in ['Didik Pamungkas', 'Ari', 'Pak arif']:
            await nama_utama(db, nama)
        didik = await db.scalar(select(TimbanganSopir).where(TimbanganSopir.kunci_nama == 'didik pamungkas'))
        db.add(TimbanganSopirAlias(kunci_nama='didik', nama='DIDIK', sopir_id=didik.id))
        await db.commit()


async def test_pilihan_dari_master_bukan_tebakan_dari_riwayat(klien):
    await semai()
    async with database.SessionLocal() as db:
        # Menjaga daftar dari penanda historis yang mungkin pernah tersimpan.
        db.add(TimbanganSopir(nama='LAIN-LAIN', kunci_nama='lain-lain'))
        await db.commit()
        sebelum = await db.scalar(select(func.count()).select_from(TimbanganSopir))
        assert await daftar_pilihan(db) == [
            {'nama': 'Ari', 'alias': []},
            {'nama': 'Didik Pamungkas', 'alias': ['DIDIK']},
            {'nama': 'Pak arif', 'alias': []},
        ]
        assert await db.scalar(select(func.count()).select_from(TimbanganSopir)) == sebelum
    await login(klien)
    for path in ['/timbang/GABAH_BASAH', '/jasa/GABAH_KERING']:
        html = (await klien.get('/timbangan' + path)).text
        assert 'data-pilihan-sopir' in html and 'value="Didik Pamungkas" data-alias="DIDIK"' in html
        assert 'value="LAIN-LAIN"' not in html


@pytest.mark.parametrize('width', [390, 1440])
async def test_filter_pilih_keyboard_luring_dan_simpan_nama_baru(klien, width):
    await semai()
    await login(klien)
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width': width, 'height': 950},
                                             is_mobile=width < 600, has_touch=width < 600,
                                             reduced_motion='reduce',
                                             service_workers='block')
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))

        async def layani(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname != 'uji':
                return await route.abort()
            headers = {k: v for k, v in req.headers.items()
                       if k.lower() in ['content-type', 'x-timbangan-kiriman', 'x-timbangan-akun', 'x-timbangan-waktu', 'x-timbangan-luring']}
            r = await klien.request(req.method, url.path + ('?' + url.query if url.query else ''),
                                    content=req.post_data_buffer, headers=headers)
            await route.fulfill(status=r.status_code,
                                headers={'content-type': r.headers.get('content-type', 'text/html')}, body=r.content)

        await page.route('**/*', layani)
        await page.goto('http://uji/timbangan/timbang/GABAH_BASAH')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.locator('#pembuka').wait_for(state='detached')
        nama = page.locator('[name="nama_sopir"]')
        hasil = page.locator('#f-nama_sopir-hasil')
        await nama.click()
        await expect(hasil.get_by_role('option')).to_have_count(3)
        assert await nama.get_attribute('aria-expanded') == 'true'
        await nama.fill('  pAMUNGkas ')
        await expect(hasil.get_by_role('option')).to_have_count(1)
        await expect(hasil.get_by_role('option')).to_have_text('Didik Pamungkas')
        await page.screenshot(path=str(OUT / f'filter-{width}.png'), full_page=True)
        await hasil.get_by_role('option').click()
        assert await nama.input_value() == 'Didik Pamungkas'
        assert await nama.get_attribute('aria-expanded') == 'false'
        await nama.fill('ＤＩＤＩＫ')
        await nama.press('ArrowDown')
        assert await nama.get_attribute('aria-activedescendant')
        await nama.press('Enter')
        assert await nama.input_value() == 'Didik Pamungkas'
        # Enter tanpa memilih tidak mengubah nama parsial menjadi hasil pertama.
        await nama.fill('Did')
        await nama.press('Enter')
        assert await nama.input_value() == 'Did'
        async with database.SessionLocal() as db:
            assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi)) == 0
        await context.set_offline(True)
        await nama.fill('ari')
        await expect(hasil.get_by_role('option')).to_have_count(2)
        await nama.press('Escape')
        assert await nama.input_value() == 'ari' and await nama.get_attribute('aria-expanded') == 'false'
        await nama.fill('Rizal Pratama')
        await expect(hasil.get_by_role('option')).to_have_count(0)
        await expect(hasil).to_contain_text('Nama baru disimpan bersama tiket')
        # Ketikan belum membuat master baru.
        async with database.SessionLocal() as db:
            assert await db.scalar(select(func.count()).select_from(TimbanganSopir)) == 3
        await context.set_offline(False)
        await nama.press('Escape')
        await page.locator('[name="berat_kg"]').fill('15000')
        await page.locator('[name="supplier_id"]').select_option('1')
        await page.locator('[name="nomor_polisi"]').fill('AD 1234 UJ')
        await page.get_by_role('button', name='Simpan timbang pertama').click()
        await page.wait_for_url('**/transaksi/*')
        async with database.SessionLocal() as db:
            t = await db.scalar(select(TimbanganTransaksi))
            assert t.nama_sopir == 'Rizal Pratama'
            assert await db.scalar(select(func.count()).select_from(TimbanganSopir)) == 4
        await page.goto('http://uji/timbangan/timbang/GABAH_BASAH')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.locator('[name="nama_sopir"]').fill('Rizal')
        await expect(page.locator('#f-nama_sopir-hasil').get_by_role('option')).to_have_text('Rizal Pratama')
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.goto(f'http://uji/timbangan/transaksi/{t.id}/koreksi')
        koreksi = page.locator('[name="nama_sopir"]')
        assert await koreksi.input_value() == 'Rizal Pratama'
        await koreksi.fill('Pamungkas')
        await expect(page.locator('#f-nama_sopir-hasil').get_by_role('option')).to_have_text('Didik Pamungkas')
        await page.locator('#f-nama_sopir-hasil').get_by_role('option').click()
        assert await koreksi.input_value() == 'Didik Pamungkas'
        assert await page.locator('[name="asli_nama_sopir"]').input_value() == 'Rizal Pratama'
        async with database.SessionLocal() as db:
            assert (await db.get(TimbanganTransaksi, t.id)).nama_sopir == 'Rizal Pratama'
        assert not errors, errors
        await browser.close()

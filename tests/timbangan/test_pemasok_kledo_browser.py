"""Pencarian kontak sungguhan tidak mengirim teks bebas sebagai pilihan."""
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from app import database
from app.models import Supplier
from test_web import app_uji, klien, login  # noqa: F401


async def test_pencarian_wajib_memilih_hasil_kledo(klien):
    async with database.SessionLocal() as db:
        db.add_all([Supplier(nama_supplier=f"Pemasok Kledo {i:02d}", kledo_contact_id=800+i)
                    for i in range(14)])
        await db.commit()
    await login(klien)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(service_workers="block")
        page = await context.new_page()
        async def layani(route):
            url = urlsplit(route.request.url)
            if url.hostname != "uji":
                return await route.abort()
            r = await klien.get(url.path + ("?" + url.query if url.query else ""))
            await route.fulfill(status=r.status_code,
                                headers={"content-type": r.headers.get("content-type", "text/html")},
                                body=r.content)
        await page.route("**/*", layani)
        await page.goto("http://uji/timbangan/timbang/GABAH_BASAH")
        cari = page.locator(".cari input").first
        await cari.fill("Nama Yang Tidak Terdaftar")
        assert await page.locator('[name="supplier_id"]').input_value() == ""
        assert await cari.evaluate("e => e.checkValidity()") is False
        await cari.fill("Pemasok Kledo 00")
        await page.locator(".cari__hasil button").filter(has_text="Pemasok Kledo 00").click()
        assert await page.locator('[name="supplier_id"]').input_value() != ""
        assert await cari.evaluate("e => e.checkValidity()") is True
        await cari.fill("Nama Lain")
        assert await page.locator('[name="supplier_id"]').input_value() == ""
        assert await cari.evaluate("e => e.checkValidity()") is False
        assert await page.locator('[name="pihak_nama"]').count() == 0
        await browser.close()

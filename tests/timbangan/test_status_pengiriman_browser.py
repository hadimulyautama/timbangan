from pathlib import Path
import pytest
from playwright.async_api import async_playwright,expect
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_keluar import buat_tiket,tabel_produksi
from test_rincian_transfer_browser import browser_uji,buka
from app import database
from app.timbangan.models import TimbanganAudit

@pytest.mark.parametrize('width',[1440,390])
@pytest.mark.parametrize('statuses,verification',[(('dimuat','dimuat'),'Verifikasi PadiFlow belum selesai'),(('selesai','selesai'),'Terverifikasi di PadiFlow')])
async def test_detail_menampilkan_dua_status_tanpa_verifikasi_saat_dibuka(klien,alamat_ui,width,statuses,verification):
 tid=await buat_tiket();await login(klien,'wahid')
 async with database.SessionLocal() as db:
  await tabel_produksi(db,tid,statuses);before=await db.scalar(select(func.count()).select_from(TimbanganAudit))
 async with async_playwright() as pw:
  b,context,page=await browser_uji(pw,klien,alamat_ui,width)
  try:
   await buka(page,f'{alamat_ui}/timbangan/transaksi/{tid}')
   panel=page.locator('[data-status-timbang-pengiriman]')
   await expect(panel).to_contain_text('Selesai timbang');await expect(panel).to_contain_text(verification)
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   await page.screenshot(path=str(Path('..')/f'tera-pengiriman-{width}-{statuses[0]}.png'),full_page=True)
  finally:await b.close()
 async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganAudit))==before

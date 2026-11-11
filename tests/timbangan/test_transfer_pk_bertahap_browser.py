"""Perjalanan yang sama terbaca pada formulir 1, 2 dan detail semua layar."""
import pytest
from playwright.async_api import async_playwright
from test_web import app_uji,klien
from test_transfer_pk_bertahap import plan,first
from test_pengiriman_gabungan_browser import alamat_ui
from test_rincian_transfer_browser import browser_uji,buka
from app.timbangan import klien_produksi as rpc

@pytest.mark.parametrize('width',[320,390,768,1440])
async def test_ringkasan_dan_kontrol_tiket_tertaut(klien,plan,alamat_ui,monkeypatch,width):
 async with async_playwright() as pw:
  browser,ctx,page=await browser_uji(pw,klien,alamat_ui,width)
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  await buka(page,alamat_ui+'/timbangan/timbang/TRANSFER?pengiriman_pk_id=51')
  assert await page.locator('[name=pengiriman_pk_id]').input_value()=='51'
  assert await page.locator('[name=nomor_polisi]').input_value()=='K 9773 J'
  assert await page.get_by_text('LOT-01 · 2000 kg',exact=True).is_visible()
  assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  tid,_=await first(klien)
  await buka(page,alamat_ui+f'/timbangan/tiket/{tid}')
  assert await page.get_by_role('heading',name='Perjalanan PK #51').is_visible()
  assert await page.get_by_text('LOT-01 · 2000 kg',exact=True).is_visible()
  assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  monkeypatch.setattr(rpc,'terkonfigurasi',lambda:True)
  async def result(*a,**kw):return dict(ok=True,status='menunggu_admin')
  monkeypatch.setattr(rpc,'_minta',result)
  r=await klien.post(f'/timbangan/tiket/{tid}',data={'berat_kg':'6510'})
  assert r.status_code==200
  await buka(page,alamat_ui+f'/timbangan/transaksi/{tid}')
  assert await page.get_by_text('Selisih perlu pemeriksaan Admin',exact=True).is_visible()
  assert await page.get_by_text('LOT-01 · 2000 kg',exact=True).is_visible()
  assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert not errors,errors
  await browser.close()

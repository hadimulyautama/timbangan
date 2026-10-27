"""Filter nomor polisi, metadata sopir, dan kendaraan baru pada borang asli."""
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright,expect
from sqlalchemy import select,func
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganKendaraan,TimbanganTransaksi,TimbanganAkun
from test_pemasok_kledo import masukan
from test_web import app_uji,klien,login  # noqa: F401

OUT=Path(__file__).parents[3]/'output/pilihan-nomor-polisi-20261025'

@pytest.mark.parametrize('width',[390,1440])
async def test_filter_tanpa_spasi_pilih_atau_simpan_kendaraan_valid(klien,width):
 async with database.SessionLocal() as db:
  db.add_all([TimbanganKendaraan(nomor_polisi=n) for n in ['AD 8872 LA','K 8382 CC','K 8482 CC']])
  akun=await db.get(TimbanganAkun,1)
  data=masukan(1);data.nomor_polisi='H9313IC';data.nama_sopir='TIMBUL'
  await service.simpan_timbang_pertama(db,akun=akun,data=data)
 await login(klien)
 OUT.mkdir(parents=True,exist_ok=True)
 async with async_playwright() as p:
  browser=await p.chromium.launch()
  context=await browser.new_context(viewport={'width':width,'height':950},is_mobile=width<600,has_touch=width<600,reduced_motion='reduce',service_workers='block')
  page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  async def layani(route):
   req=route.request;u=urlsplit(req.url)
   if u.hostname!='uji':return await route.abort()
   headers={k:v for k,v in req.headers.items() if k.lower() in ['content-type','x-timbangan-kiriman','x-timbangan-akun','x-timbangan-waktu','x-timbangan-luring']}
   r=await klien.request(req.method,u.path+('?' +u.query if u.query else ''),content=req.post_data_buffer,headers=headers)
   await route.fulfill(status=r.status_code,headers={'content-type':r.headers.get('content-type','text/html')},body=r.content)
  await page.route('**/*',layani)
  await page.goto('http://uji/timbangan/timbang/GABAH_BASAH')
  await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
  await page.locator('#pembuka').wait_for(state='detached')
  plate=page.locator('[name="nomor_polisi"]');hasil=page.locator('#f-nomor_polisi-hasil')
  await plate.click();await expect(hasil.get_by_role('option')).to_have_count(4)
  await plate.fill('ad8872');await expect(hasil.get_by_role('option')).to_have_text('AD 8872 LA')
  await page.screenshot(path=str(OUT/f'filter-{width}.png'),full_page=True)
  await hasil.get_by_role('option').click()
  assert await plate.input_value()=='AD 8872 LA' and await plate.evaluate('e=>e.checkValidity()')
  await plate.fill('K8');await expect(hasil.get_by_role('option')).to_have_count(2)
  await plate.press('Enter');assert await plate.input_value()=='K8'
  async with database.SessionLocal() as db:
   assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==1
  await context.set_offline(True)
  await plate.fill('h9313ic');await expect(hasil.get_by_role('option')).to_have_text('H 9313 IC')
  await plate.press('ArrowDown');await plate.press('Enter')
  assert await plate.input_value()=='H 9313 IC'
  assert await page.locator('[name="nama_sopir"]').input_value()=='TIMBUL'
  await plate.fill('3840');assert not await plate.evaluate('e=>e.checkValidity()')
  await expect(hasil).to_contain_text('Ketik nomor lengkap')
  await plate.fill('ad9999zz');await expect(hasil.get_by_role('option')).to_have_count(0)
  await expect(hasil).to_contain_text('Kendaraan baru disimpan bersama tiket')
  async with database.SessionLocal() as db:
   assert await db.scalar(select(func.count()).select_from(TimbanganKendaraan))==4
  await context.set_offline(False)
  await plate.press('Escape')
  await page.locator('[name="nama_sopir"]').fill('Rizal Pratama')
  await page.locator('[name="berat_kg"]').fill('15000')
  await page.locator('[name="supplier_id"]').select_option('1')
  await page.get_by_role('button',name='Simpan timbang pertama').click()
  await page.wait_for_url('**/transaksi/*')
  async with database.SessionLocal() as db:
   t=await db.scalar(select(TimbanganTransaksi).where(TimbanganTransaksi.nomor_polisi=='AD 9999 ZZ'))
   assert t is not None
   assert await db.scalar(select(func.count()).select_from(TimbanganKendaraan))==5
  await page.goto('http://uji/timbangan/timbang/GABAH_BASAH')
  await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
  await page.locator('[name="nomor_polisi"]').fill('ad9999')
  await expect(page.locator('#f-nomor_polisi-hasil').get_by_role('option')).to_have_text('AD 9999 ZZ')
  await page.goto(f'http://uji/timbangan/transaksi/{t.id}/koreksi')
  plate=page.locator('[name="nomor_polisi"]');await plate.fill('K8382')
  await expect(page.locator('#f-nomor_polisi-hasil').get_by_role('option')).to_have_text('K 8382 CC')
  await page.locator('#f-nomor_polisi-hasil').get_by_role('option').click()
  assert await plate.input_value()=='K 8382 CC'
  assert await page.locator('[name="asli_nomor_polisi"]').input_value()=='AD 9999 ZZ'
  async with database.SessionLocal() as db:
   assert (await db.get(TimbanganTransaksi,t.id)).nomor_polisi=='AD 9999 ZZ'
   # Simulasikan tiket lama yang nomornya belum lengkap: koreksi lain tetap boleh.
   legacy=await db.get(TimbanganTransaksi,t.id);legacy.nomor_polisi='3840'
   await db.commit()
  await page.goto(f'http://uji/timbangan/transaksi/{t.id}/koreksi')
  plate=page.locator('[name="nomor_polisi"]')
  assert await plate.input_value()=='3840' and await plate.evaluate('e=>e.checkValidity()')
  await plate.fill('HURUF');assert not await plate.evaluate('e=>e.checkValidity()')
  assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert not errors,errors
  await browser.close()

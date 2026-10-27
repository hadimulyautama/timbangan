"""Perapian dan penolakan format pada browser dan kiriman luring."""
from urllib.parse import urlsplit
import pytest
from playwright.async_api import async_playwright
from test_web import app_uji,klien,login,kode_dari  # noqa: F401
from test_kiriman_luring import headers

@pytest.mark.parametrize('bad',['3840','HURUF','-','A12B3'])
async def test_kiriman_luring_nomor_invalid_ditolak_dan_bisa_diperbaiki(klien,bad):
 await login(klien)
 key=kode_dari((await klien.get('/timbangan/timbang/GABAH_BASAH')).text)
 data={'kunci':key,'berat_kg':'15000','supplier_id':'1','nama_sopir':'Sopir Uji','nomor_polisi':bad}
 r=await klien.post('/timbangan/timbang/GABAH_BASAH',data=data,headers=headers(key))
 assert r.status_code==422 and not r.json()['tersimpan'] and 'Format nomor polisi' in r.text
 data['nomor_polisi']='h9313ic'
 r=await klien.post('/timbangan/timbang/GABAH_BASAH',data=data,headers=headers(key))
 assert r.status_code==200 and r.json()['tersimpan']

@pytest.mark.parametrize('width',[390,1440])
async def test_nopol_tanpa_spasi_dirapikan_dan_format_invalid_ditahan(klien,width):
 await login(klien)
 async with async_playwright() as p:
  browser=await p.chromium.launch()
  context=await browser.new_context(viewport={'width':width,'height':950},reduced_motion='reduce',service_workers='block')
  page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  async def layani(route):
   u=urlsplit(route.request.url)
   if u.hostname!='uji':return await route.abort()
   r=await klien.get(u.path+('?' +u.query if u.query else ''))
   await route.fulfill(status=r.status_code,headers={'content-type':r.headers.get('content-type','text/html')},body=r.content)
  await page.route('**/*',layani)
  await page.goto('http://uji/timbangan/timbang/GABAH_BASAH')
  await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
  await page.locator('#pembuka').wait_for(state='detached')
  plate=page.locator('[name="nomor_polisi"]')
  await plate.fill('h9313ic');await plate.blur()
  assert await plate.input_value()=='H 9313 IC'
  assert await plate.evaluate('e=>e.checkValidity()')
  for bad in ['3840','HURUF','-','A12B3']:
   await plate.fill(bad)
   assert not await plate.evaluate('e=>e.checkValidity()')
  await plate.fill('AD8872LA');await plate.blur()
  assert await plate.input_value()=='AD 8872 LA' and await plate.evaluate('e=>e.checkValidity()')
  assert not errors,errors
  await browser.close()

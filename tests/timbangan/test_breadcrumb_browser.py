"""Rantai, tombol Kembali dan ukuran latar pada halaman asli lintas jenis."""
from urllib.parse import quote,urlsplit,parse_qs
import pytest
from playwright.async_api import async_playwright,expect
from test_web import app_uji,klien,login
from test_timbang_pertama_desain_browser import lokal
from data_riwayat import isi_riwayat
from app import database
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('engine',['chromium','webkit'])
async def test_rantai_latar_dan_kembali_antarhalaman(lokal,engine):
 url,client=lokal;ids=await isi_riwayat(database.SessionLocal,jumlah=7)
 async with async_playwright() as pw:
  browser=await getattr(pw,engine).launch()
  try:
   for width in [1440,1024,390]:
    ctx=await browser.new_context(viewport={'width':width,'height':1000},service_workers='block',reduced_motion='reduce');await ctx.add_cookies([{'name':k,'value':v,'url':url} for k,v in client.cookies.items()]);page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    await page.route('https://fonts.googleapis.com/**',lambda r:r.abort());await page.route('https://fonts.gstatic.com/**',lambda r:r.abort())
    # Tidak ada perangkat timbang dalam uji navigasi; hentikan SSE dengan 204.
    await page.route('**/timbangan/aliran',lambda r:r.fulfill(status=204))
    async def selesai():
     await page.wait_for_function('!window.timbanganLuring || window.timbanganLuring.siap()')
     await page.wait_for_load_state('networkidle')
    async def buka(target):
     response=await page.goto(target);await selesai();return response
    sizes=[]
    for path in ['/','/tiket','/transaksi','/pengaturan','/printer','/timbang/GABAH_BASAH']+['/transaksi/'+str(i) for i in ids]:
     r=await buka(url+'/timbangan'+path);assert r.status<400,(path,r.status)
     await selesai()
     crumb=page.locator('.pd-crumb')
     if width<900:
      await expect(crumb).not_to_be_visible();continue
     await expect(crumb).to_be_visible();labels=await crumb.locator('.nav-rantai>li').all_text_contents();labels=[' '.join(x.replace('›','').split()) for x in labels]
     assert all(a!=b for a,b in zip(labels,labels[1:])),(path,labels)
     assert await crumb.locator('[aria-current=page]').count()==1
     back=crumb.locator('.pd-desktop-back');links=crumb.locator('nav a')
     if await links.count():assert await back.get_attribute('href')==await links.last.get_attribute('href')
     bounds=await crumb.bounding_box();bar=await page.locator('header.bar').bounding_box();assert abs(bounds['width']-bar['width'])<=1
     sizes.append((path,bounds['width'],bounds['height']))
     assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    if width>=900:
     assert len({round(x[1]) for x in sizes})==1,sizes
     assert len({round(x[2]) for x in sizes})==1,sizes
     # Satu kode tiket, induk daftar tetap ada, filter ikut saat kembali.
     target='/timbangan/transaksi?cari=Suroto&arah=KELUAR';rid=ids[1]
     await buka(url+'/timbangan/transaksi/'+str(rid)+'?kembali='+quote(target,safe=''))
     await selesai()
     crumb=page.locator('.pd-crumb');assert await crumb.locator('.nav-rantai>li').count()==3
     await crumb.locator('.pd-desktop-back').click();await page.wait_for_url('**cari=Suroto**');await selesai();assert parse_qs(urlsplit(page.url).query)['arah']==['KELUAR']
     await buka(url+'/timbangan/transaksi/'+str(rid)+'/koreksi?kembali='+quote(target,safe=''))
     back=page.locator('.pd-crumb .pd-desktop-back');href=await back.get_attribute('href');assert urlsplit(href).path=='/timbangan/transaksi/'+str(rid) and parse_qs(urlsplit(href).query)['kembali']==[target]
     await selesai();await back.click();await page.wait_for_url('**/transaksi/'+str(rid)+'?**');await selesai();await page.locator('.pd-desktop-back').click();await page.wait_for_url('**cari=Suroto**');await selesai()
     await page.screenshot(path=f'/bukti/teraflow-{engine}-{width}.png')
    assert not errors,errors
    await ctx.close()
  finally:await browser.close()

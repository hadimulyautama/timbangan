"""Penanda opt-in, URI lokal, dan pembaruan tautan tanpa menyentuh fokus."""
import os
from pathlib import Path
import pytest
pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_CARI')!='1',reason='Browser fixture opsional')]
SOURCE=Path(__file__).resolve().parents[2]/'app/timbangan/static/navigasi-pos.js'

async def test_tautan_opt_in_dan_pembaruan_tidak_memindah_fokus():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();page=await browser.new_page()
        html='''<input id="filter"><table><tr class="rh-item" id="rh-tiket-35" data-riwayat-mandiri data-riwayat-id="35" data-buka="/timbangan/transaksi/35?kembali=%2Ftimbangan%2Ftransaksi%3Fhal%3D2">
          <td><a class="rh-open" href="/timbangan/transaksi/35?kembali=%2Ftimbangan%2Ftransaksi%3Fhal%3D2">Tiket</a><a id="cetak" href="/timbangan/transaksi/35/cetak">Cetak</a></td></tr>
          <tr class="rh-item" data-riwayat-id="36"><td><a id="lain" href="/timbangan/transaksi/36?kembali=%2Ftimbangan%2Ftransaksi%3Fhal%3D2">Lain</a></td></tr></table>'''
        await page.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
        try:
            await page.goto('http://uji/timbangan/transaksi?hal=2');await page.add_script_tag(path=str(SOURCE))
            result=await page.evaluate('''()=>{const a=document.querySelector('.rh-open'),url=new URL(a.href),back=new URL(url.searchParams.get('kembali'),location.origin);
              const first={hash:back.hash,page:back.searchParams.get('hal'),cetak:document.getElementById('cetak').getAttribute('href'),lain:document.getElementById('lain').getAttribute('href')};
              a.href='/timbangan/transaksi/35?kembali=%2Ftimbangan%2Ftransaksi%3Fhal%3D2';document.getElementById('filter').focus();window.dispatchEvent(new Event('teraflow:data'));
              return {first,focus:document.activeElement.id,updated:new URL(new URL(a.href).searchParams.get('kembali'),location.origin).hash,storage:sessionStorage.length};}''')
            assert result==dict(first=dict(hash='#rh-tiket-35',page='2',cetak='/timbangan/transaksi/35/cetak',lain='/timbangan/transaksi/36?kembali=%2Ftimbangan%2Ftransaksi%3Fhal%3D2'),focus='filter',updated='#rh-tiket-35',storage=0)
        finally:await browser.close()

@pytest.mark.parametrize('opt_in',[True,False])
@pytest.mark.parametrize('hash_id',['35','36'])
async def test_fragment_hanya_tiket_bertanda_dan_id_sama(opt_in,hash_id):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();page=await browser.new_page()
        html='<header class="bar"><a aria-label="Kembali" href="/timbangan/">Kembali</a></header>'+('<span data-riwayat-mandiri-detail="35"></span>' if opt_in else '')
        await page.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
        try:
            await page.goto('http://uji/timbangan/transaksi/35?kembali=%2Ftimbangan%2Ftransaksi%3Fhal%3D2%23rh-tiket-'+hash_id);await page.add_script_tag(path=str(SOURCE))
            assert await page.locator('.bar a').get_attribute('href')=='/timbangan/transaksi?hal=2'+('#rh-tiket-35' if opt_in and hash_id=='35' else '')
        finally:await browser.close()

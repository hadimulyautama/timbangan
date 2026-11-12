"""Bobot partai dapat dibaca ulang tanpa berubah makna dan tiap kolom bernama."""
from decimal import Decimal

import re
from html.parser import HTMLParser

class Elemen(HTMLParser):
    def __init__(self,html):
        super().__init__(); self.items=[]; self.feed(html)
    def handle_starttag(self,tag,attrs):
        self.items.append((tag,dict(attrs)))
import pytest

from app.timbangan.format import angka_rinci
from app.timbangan.routes.pos import _angka
from test_web import app_uji, klien, login, kode_dari
from test_beranda_tiket import benih


@pytest.mark.parametrize('nilai,teks', [
    (0,'0'), (Decimal('0.005'),'0,005'), (Decimal('0.250'),'0,25'),
    (Decimal('12.345'),'12,345'), (Decimal('24.690'),'24,69'),
    (1000,'1.000'), (Decimal('1234567.125'),'1.234.567,125'),
])
def test_bobot_tampilan_dapat_diketik_ulang(nilai,teks):
    assert angka_rinci(nilai)==teks
    assert _angka(angka_rinci(nilai))==pytest.approx(float(nilai))


@pytest.mark.asyncio
async def test_partai_ringkasan_riwayat_konfirmasi_dan_isian_bermakna_sama(klien):
    await login(klien)
    await benih(0,1)
    r=await klien.get('/timbangan/partai/1')
    assert '12,345' in r.text
    r=await klien.post('/timbangan/partai/1',data={
        'kunci':kode_dari(r.text),'berat_kg':'12,345','aksi':'sementara'})
    assert r.status_code==200
    items=Elemen(r.text).items
    assert re.search(r'class="hasil__angka">24,69\s*<span',r.text)
    assert len([a for tag,a in items if tag=='form' and 'Hapus timbangan 12,345 kg?' in a.get('onsubmit','')])==2
    assert any(tag=='label' and a.get('for')=='f-jumlah_karung' for tag,a in items)
    assert next(a for tag,a in items if a.get('id')=='f-jumlah_karung')['aria-describedby']=='bantu-jumlah_karung'
    assert next(a for tag,a in items if tag=='label' and a.get('for')=='f-berat-1')['aria-label']=='Berat timbangan 3 dalam kg'

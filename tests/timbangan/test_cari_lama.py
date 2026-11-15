"""Pencarian arsip menggunakan jendela terbatas dan gerbang izin yang sama."""
import html,re
from datetime import date,timedelta
from urllib.parse import parse_qs,urlsplit
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from test_web import app_uji,klien,login
from data_cari_lama import arsip
from app.timbangan.db import hari_ini
from app.timbangan.web import PREFIX
from test_riwayat import ids,snapshot


def tautan(text):
    match=re.search(r'data-rh-cari-lama href="([^"]+)"',text)
    return html.unescape(match[1]) if match else None


@pytest.mark.parametrize('peran',['operator','admin','superadmin'])
async def test_kosong_eksplisit_jendela_365_hari_dan_paginasi(klien,peran):
    await arsip(peran);await login(klien,'fixture-'+peran)
    before=await snapshot()
    q=dict(cari='ARSIP',arah='MASUK',jenis='GABAH_BASAH',status='NORMAL',tiket='SELESAI')
    r=await klien.get(PREFIX+'/transaksi',params=q)
    assert ids(r.text)==[]
    assert f'name="dari" value="{hari_ini()-timedelta(days=13)}"' in r.text
    target=tautan(r.text);assert target
    parsed=parse_qs(urlsplit(target).query)
    assert all(parsed[k]==[v] for k,v in q.items())
    assert parsed['hal']==['1']
    awal=date.fromisoformat(parsed['dari'][0]);akhir=date.fromisoformat(parsed['sampai'][0])
    assert akhir==hari_ini()-timedelta(days=14) and (akhir-awal).days==364
    r=await klien.get(target)
    assert len(ids(r.text))==50 and '80 transaksi' in r.text
    assert tautan(r.text) is None
    following=html.unescape(re.search(r'rel="next" href="([^"]+)"',r.text)[1])
    r=await klien.get(following);assert len(ids(r.text))==30
    detail=html.unescape(re.search(r'class="rh-open" href="([^"]+)"',r.text)[1])
    kembali=parse_qs(urlsplit(detail).query)['kembali'][0]
    assert parse_qs(urlsplit(kembali).query)=={**parsed,'hal':['2']}
    assert f'href="{html.escape(kembali,quote=True)}" aria-label="Kembali"' in (await klien.get(detail)).text
    assert (await klien.get(PREFIX+'/ekspor.csv')).status_code==(403 if peran=='operator' else 200)
    assert await snapshot()==before


async def test_tiket_lebih_dari_setahun_jendela_tidak_membesar(klien):
    await arsip();await login(klien,'fixture-operator')
    r=await klien.get(PREFIX+'/transaksi?cari=DUATAHUN')
    for i in range(2):
        target=tautan(r.text);assert target
        params=parse_qs(urlsplit(target).query)
        assert (date.fromisoformat(params['sampai'][0])-date.fromisoformat(params['dari'][0])).days==364
        r=await klien.get(target)
        assert len(ids(r.text))==(0 if i==0 else 1)
    assert 'DUATAHUN-SINTETIS' in r.text


async def test_tidak_menawarkan_pencarian_tanpa_kata_atau_tanggal_sah(klien):
    await login(klien)
    assert tautan((await klien.get(PREFIX+'/transaksi?cari=ARSIP')).text) is None
    await arsip()
    for q in ({},{'cari':'   '},{'cari':'ARSIP','dari':'0001-01-01','sampai':'0001-01-01'},{'cari':'ARSIP','dari':'2026-12-31','sampai':'2026-01-01'}):
        r=await klien.get(PREFIX+'/transaksi',params=q)
        assert r.status_code==200 and tautan(r.text) is None


async def test_kosong_tidak_menghitung_semua_arsip(klien):
    await arsip();await login(klien,'fixture-operator')
    sql=[]
    def capture(conn,cursor,statement,parameters,context,executemany):sql.append(statement)
    event.listen(Engine,'before_cursor_execute',capture)
    try:r=await klien.get(PREFIX+'/transaksi?cari=ARSIP')
    finally:event.remove(Engine,'before_cursor_execute',capture)
    assert r.status_code==200
    counts=[s for s in sql if 'count(timbangan_transaksi.id)' in s]
    assert len([s for s in counts if 'tanggal >=' in s and 'tanggal <=' in s])==1
    assert all(' WHERE ' in ' '.join(s.split()) for s in counts)
    assert any('SELECT timbangan_transaksi.id ' in s and 'LIMIT' in s for s in sql)

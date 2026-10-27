"""Cookie mode PadiFlow harus sampai ke kontrak baca; tidak mengubah tiket."""
import pytest,httpx
from copy import deepcopy
from dataclasses import replace
from test_web import app_uji,klien,login
from test_rincian_retur import tiket,tautkan,payload
from hmu_identitas import peran as P
from app import database
from app.timbangan import klien_produksi as client
from app.timbangan.models import TimbanganTransaksi

@pytest.mark.parametrize('view',[None,'admin','operator:g1','operator:g2'])
async def test_halaman_retur_meneruskan_mode_dan_menghormati_penolakan(klien,monkeypatch,view):
 tid=await tiket();aid=await tautkan(role=P.SUPERADMIN);await login(klien,'wahid')
 async with database.SessionLocal() as db:data=payload(await db.get(TimbanganTransaksi,tid))
 monkeypatch.setattr(client,'settings',replace(client.settings,produksi_api_url='http://uji-kontrak',produksi_api_token='uji-lokal'))
 seen=[];original=client.httpx.AsyncClient
 def handler(req):
  seen.append(req)
  return httpx.Response(403,json={'detail':'Dibatasi'}) if req.headers.get('X-Produksi-Lihat','').startswith('operator:') else httpx.Response(200,json=deepcopy(data))
 monkeypatch.setattr(client.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
 if view:klien.cookies.set('produksi_lihat',view)
 r=await klien.get(f'/timbangan/transaksi/{tid}')
 assert r.status_code==200 and len(seen)==1
 assert seen[0].method=='GET' and seen[0].headers['X-Operator-Akun']==str(aid)
 assert seen[0].headers.get('X-Produksi-Lihat')==view
 if view and view.startswith('operator:'):
  assert 'Rincian PadiFlow dibatasi oleh izin akun' in r.text and 'RET-UJI-4' not in r.text
 else:assert 'RET-UJI-4' in r.text
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);assert t.status_tiket=='SELESAI' and float(t.berat_barang_kg)==70.1

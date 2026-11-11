"""Contrat perjalanan PK: form nyata, replay, kegagalan RPC dan hak koreksi."""
from uuid import uuid4
import pytest
from sqlalchemy import select,func,text
from test_web import app_uji,klien,login,kode_dari
from test_rincian_transfer import master
from app import database
from app.timbangan import transfer_pk as p,service,klien_produksi as rpc
from app.timbangan.models import TimbanganTransaksi,TimbanganAkun

@pytest.fixture
async def plan(klien,monkeypatch):
 await master()
 data=dict(id=51,status='dalam_perjalanan',sidik='f'*64,nomor_polisi='K 9773 J',nama_sopir='Sopir Uji',total='2000',items=[dict(id=1,permintaan_id=1,lot='LOT-01',berat_kg='2000')],lintasan=dict(versi=1,asal=dict(gudang_id=101,nama='Gudang asal'),tujuan=dict(gudang_id=102,silo_id=None,pilihan='gudang:102',nama='Tumpukan tujuan')))
 async def pilihan(*a,**kw):return data.copy()
 monkeypatch.setattr(p,'pilihan',pilihan)
 async with database.SessionLocal() as db:
  # Tabel ini dimiliki PadiFlow; TeraFlow hanya membaca statusnya.
  await db.execute(text('CREATE TABLE pengiriman_pk(id INTEGER PRIMARY KEY,status TEXT)'))
  await db.execute(text("INSERT INTO pengiriman_pk VALUES(51,'dalam_perjalanan')"));await db.commit()
 await login(klien)
 return data

async def first(klien):
 page=await klien.get('/timbangan/timbang/TRANSFER?pengiriman_pk_id=51')
 assert page.status_code==200 and 'LOT-01' in page.text and 'value="K 9773 J"' in page.text
 body=dict(kunci=kode_dari(page.text),berat_kg='8500',nama_sopir='Sopir Uji',nomor_polisi='K 9773 J',pengiriman_pk_id='51',jumlah_karung='40',tara_per_karung_kg='0',lintasan_format='1',transfer_asal='101',transfer_tujuan='gudang:102')
 response=await klien.post('/timbangan/timbang/TRANSFER',data=body)
 assert 'Timbang pertama tersimpan' in response.text,response.text[-3000:]
 async with database.SessionLocal() as db:tid=await db.scalar(select(TimbanganTransaksi.id))
 return tid,body

async def test_form_replay_dan_selesai_tanpa_menggandakan(klien,plan,monkeypatch):
 tid,body=await first(klien)
 await klien.post('/timbangan/timbang/TRANSFER',data=body)
 async with database.SessionLocal() as db:
  assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==1
  t=await db.get(TimbanganTransaksi,tid);assert t.pengiriman_pk_id==51 and t.lintasan_transfer['_pengiriman_pk']['total']=='2000'
 calls=[]
 monkeypatch.setattr(rpc,'terkonfigurasi',lambda:True)
 async def minta(method,path,**kw):
  calls.append(path)
  # A fresh connection proves the caller released its write transaction.
  async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).status_tiket=='SELESAI'
  return dict(ok=True,status='selesai')
 monkeypatch.setattr(rpc,'_minta',minta)
 r=await klien.post(f'/timbangan/tiket/{tid}',data={'berat_kg':'6500'})
 assert r.status_code==200 and 'stok telah tercatat' in r.text,str(r.url)
 assert len(calls)==1
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);assert t.berat_barang_kg==2000 and t.pengiriman_pk_status=='selesai'
  # Actual PadiFlow status, not the cache, protects a stock-affecting correction.
  await db.execute(text("UPDATE pengiriman_pk SET status='selesai' WHERE id=51"));await db.commit()
  a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
  with pytest.raises(service.LayananError,match='Stok perjalanan'):await p.penjaga_koreksi(db,t,{'timbang2_kg':6400},None)

async def test_rpc_terputus_dan_ulang_termasuk_keputusan_admin(klien,plan,monkeypatch):
 tid,_=await first(klien);monkeypatch.setattr(rpc,'terkonfigurasi',lambda:True)
 async def putus(*a,**kw):raise rpc.ProduksiTakTersedia('Jaringan putus')
 monkeypatch.setattr(rpc,'_minta',putus)
 r=await klien.post(f'/timbangan/tiket/{tid}',data={'berat_kg':'6510'})
 assert r.status_code==200 and 'Menunggu penyelesaian otomatis' in r.text
 async def wait(*a,**kw):return dict(ok=True,status='menunggu_admin')
 monkeypatch.setattr(rpc,'_minta',wait);p._terakhir=0;await p.sinkron_tertunda()
 async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).pengiriman_pk_status=='menunggu_admin'
 async def accepted(*a,**kw):return dict(ok=True,status='selesai')
 monkeypatch.setattr(rpc,'_minta',accepted);p._terakhir=0;await p.sinkron_tertunda()
 async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).pengiriman_pk_status=='selesai'

async def test_satu_perjalanan_satu_tiket_dan_identitas_tidak_boleh_dibuang(klien,plan):
 tid,body=await first(klien)
 r=await klien.post('/timbangan/timbang/TRANSFER',data={**body,'kunci':str(uuid4())})
 assert 'sudah memiliki tiket' in r.text
 r=await klien.post('/timbangan/timbang/TRANSFER',data={**body,'pengiriman_pk_id':''})
 assert 'transfer berbeda' in r.text
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid)
  from app.timbangan.tautan_produksi import pastikan_bebas_tautan
  with pytest.raises(service.LayananError):await pastikan_bebas_tautan(db,t,tindakan="Membatalkan")

"""Dipanggil uji dua aplikasi pada database PostgreSQL lokal terisolasi."""
import asyncio,json,sys
from uuid import uuid4
from sqlalchemy import select,func
from app.database import SessionLocal,dapatkan_engine
from app.timbangan import service,transfer_pk
from app.timbangan.models import TimbanganAkun,TimbanganTransaksi

async def run():
 data=json.loads(sys.argv[1]);ids=[]
 async with SessionLocal() as db:
  await service.pastikan_jenis(db)
  akun=TimbanganAkun(username='uji-transfer-sumber',nama='Operator sumber uji',role='PETUGAS',password_hash='x',perangkat_kode='UT',akun_id=data['akun_id']);db.add(akun);await db.commit()
  for pid,loaded in data['journeys']:
   first=8500
   muatan=[service.InputMuatan(jenis_kode='TRANSFER',jumlah_karung=40,tara_per_karung_kg=0)]
   body=service.InputTimbang(kunci=uuid4().hex,arah='TRANSFER',jenis_kode='TRANSFER',berat_kg=first,nomor_polisi='K 9773 J',nama_sopir='Kasidi',pengiriman_pk_id=pid,muatan=muatan)
   t=await service.simpan_timbang_pertama(db,akun=akun,data=body)
   assert t.pengiriman_pk_id==pid and t.lintasan_transfer['_pengiriman_pk']['id']==pid
   again=await service.simpan_timbang_pertama(db,akun=akun,data=body);assert again.id==t.id
   tid=t.id;ids.append(tid)
   t=await service.simpan_timbang_kedua(db,akun=akun,kode=t.kode,berat_kg=first-loaded,muatan=muatan)
   await db.commit()
   await transfer_pk.sinkron_satu(tid)
   await db.refresh(t);assert t.pengiriman_pk_status=='selesai',t.pengiriman_pk_status
   await db.commit()
  assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==len(ids)
 await dapatkan_engine().dispose()
 print(json.dumps(dict(ids=ids)))
asyncio.run(run())

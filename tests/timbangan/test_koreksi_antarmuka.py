"""Kontrak web koreksi: presisi, pihak, preview baca saja dan akses."""
import re,json,os
from pathlib import Path
import pytest
from sqlalchemy import select,func
from test_web import app_uji,klien,login  # noqa
from test_formulir import fields
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganAkun,TimbanganTransaksi,TimbanganAudit

async def tiket(*,jasa=False,arah='MASUK',kode='GABAH_BASAH',cara='DUA_KALI',selesai=True):
 async with database.SessionLocal() as db:
  a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
  t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(kunci='ui-koreksi',arah=arah,jenis_kode=kode,berat_kg=5000 if arah in ('KELUAR','RETUR_KELUAR') else (120 if cara=='PARTAI' else 15000),cara_timbang=cara,pihak_nama='Pihak Sintetis' if arah=='TRANSFER' else None,supplier_id=1 if not jasa and arah not in ('TRANSFER','KELUAR') else None,pelanggan_id=1 if jasa else None,jasa=jasa,nomor_polisi='W 123 UJ',nama_sopir='Sopir Lama',muatan=[service.InputMuatan(jenis_kode=kode,jumlah_karung=100,tara_per_karung_kg=.0858,berat_acuan_kg=9990.5,nomor_acuan='UJI-NOTA')]))
  if arah=='RETUR_MASUK':
   from sqlalchemy import text
   await db.execute(text('CREATE TABLE IF NOT EXISTS customer_returns (id integer primary key,timbangan_transaksi_id integer,kode text)'))
  if cara=='DUA_KALI' and selesai:
   t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=15000 if arah in ('KELUAR','RETUR_KELUAR') else 5000)
  if cara=='PARTAI':await service.tambah_penimbangan(db,akun=a,kode=t.kode,berat=[160,80])
  return t.id

def payload(html):
 return {n:v for n,v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"',html)}

@pytest.mark.parametrize('siapa',['budi','wahid'])
async def test_ketikan_sopir_tidak_membulatkan_muatan_web(klien,siapa):
 tid=await tiket();await login(klien,siapa);r=await klien.get(f'/timbangan/transaksi/{tid}/koreksi');d=payload(r.text);d.update(nama_sopir='Sopir Baru',alasan='Perbaikan nama uji')
 await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=d)
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);assert t.nama_sopir=='Sopir Baru'
  assert float(t.muatan[0].tara_per_karung_kg)==.0858 and float(t.muatan[0].berat_acuan_kg)==9990.5

@pytest.mark.parametrize('jasa',[False,True])
async def test_pihak_koreksi_mengikuti_penanda_jasa(klien,jasa):
 tid=await tiket(jasa=jasa);await login(klien);r=await klien.get(f'/timbangan/transaksi/{tid}/koreksi')
 assert ('Toko Uji' in r.text)==jasa

@pytest.mark.parametrize('siapa',['budi','wahid'])
@pytest.mark.parametrize('arah,kode,cara,selesai',[('MASUK','GABAH_BASAH','DUA_KALI',True),('MASUK','GABAH_BASAH','DUA_KALI',False),('BEBAS','BEBAS','SEKALI',True),('BEBAS','BEBAS','PARTAI',False)])
async def test_kontrak_form_koreksi_awal(klien,siapa,arah,kode,cara,selesai):
 tid=await tiket(arah=arah,kode=kode,cara=cara,selesai=selesai);await login(klien,siapa);r=await klien.get(f'/timbangan/transaksi/{tid}/koreksi');got=fields(r.text);key=f'{siapa}-{cara}-{selesai}';p=Path(__file__).with_name('koreksi_kontrak.json')
 # ID berbeda tidak relevan; method, nama, kewajiban, versi dan aksi tetap.
 if os.environ.get('REKAM_KONTRAK_KOREKSI')=='1':
  semua=json.loads(p.read_text()) if p.exists() else {};semua[key]=got;p.write_text(json.dumps(semua,indent=2));return
 assert got==json.loads(p.read_text())[key]

@pytest.mark.parametrize('ubah',['sopir','angka'])
@pytest.mark.parametrize('arah,kode,cara,selesai',[('MASUK','GABAH_BASAH','DUA_KALI',True),('MASUK','GABAH_KERING','DUA_KALI',True),('MASUK','BERAS_PK','DUA_KALI',True),('MASUK','BERAS_MASUK','DUA_KALI',True),('MASUK','BROKEN_MASUK','DUA_KALI',True),('KELUAR','PENGIRIMAN','DUA_KALI',True),('TRANSFER','TRANSFER','DUA_KALI',True),('RETUR_MASUK','RETUR_PELANGGAN','DUA_KALI',True),('RETUR_KELUAR','RETUR_SUPPLIER','DUA_KALI',True),('BEBAS','BEBAS','SEKALI',True),('BEBAS','BEBAS','PARTAI',False),('MASUK','GABAH_BASAH','DUA_KALI',False)])
async def test_pratinjau_koreksi_sama_hasil_resmi_tanpa_mutasi(klien,arah,kode,cara,selesai,ubah):
 from test_riwayat import snapshot
 from app.timbangan import koreksi
 tid=await tiket(arah=arah,kode=kode,cara=cara,selesai=selesai);await login(klien);d=payload((await klien.get(f'/timbangan/transaksi/{tid}/koreksi')).text)
 d.update(nama_sopir='Sopir Baru',alasan='Periksa kesamaan hasil')
 if ubah=='angka':
  d.update(berat_acuan_kg='9900',jumlah_karung='101')
  if cara!='PARTAI':d['timbang1_kg']='4900' if arah in ('KELUAR','RETUR_KELUAR') else '14900'
 before=await snapshot();r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi/pratinjau',data=d)
 assert r.status_code==200,r.text;assert await snapshot()==before;assert r.headers['cache-control']=='no-store'
 got=r.json()
 if ubah=='sopir':assert [x['field'] for x in got['perubahan']]==['nama_sopir']
 else:assert 'berat_acuan_kg' in [x['field'] for x in got['perubahan']]
 await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=d)
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);assert t.jumlah_revisi==1
  if got['terbuka']:assert t.status_tiket=='TERBUKA' and t.berat_barang_kg is None
  else:assert got['nilai']['Berat barang setelah koreksi']==koreksi.tampil(t.berat_barang_kg,'timbang1_kg')

async def test_tanpa_perubahan_atau_beda_ejaan_tidak_menambah_revisi(klien):
 tid=await tiket();await login(klien);d=payload((await klien.get(f'/timbangan/transaksi/{tid}/koreksi')).text)
 d.update(timbang1_kg='15.000',tara_per_karung_kg='0.0858',berat_acuan_kg='9.990,50',alasan='Cek penulisan angka')
 r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi/pratinjau',data=d);assert r.json()['perubahan']==[]
 await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=d)
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);assert t.jumlah_revisi==0
  assert await db.scalar(select(func.count()).select_from(TimbanganAudit).where(TimbanganAudit.aksi=='KOREKSI'))==0

async def test_edit_muatan_pertama_tidak_meratakan_baris_dan_metadata(klien):
 tid=await tiket();await login(klien)
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid)
  await service._pasang_muatan(db,t,[service.InputMuatan(jenis_kode='GABAH_BASAH',jumlah_karung=100,tara_per_karung_kg=.0858,berat_acuan_kg=6000,catatan='Meta A'),service.InputMuatan(jenis_kode='GABAH_KERING',jumlah_karung=80,tara_per_karung_kg=.125,berat_acuan_kg=3990.5,nomor_acuan='NOTA-B',catatan='Meta B')]);await db.commit()
 d=payload((await klien.get(f'/timbangan/transaksi/{tid}/koreksi')).text);d.update(jumlah_karung='101',alasan='Perbaiki hitungan baris pertama')
 await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=d)
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);assert len(t.muatan)==2;assert t.muatan[0].jumlah_karung==101 and t.muatan[0].catatan=='Meta A'
  assert t.muatan[1].jenis_kode=='GABAH_KERING' and float(t.muatan[1].tara_per_karung_kg)==.125 and t.muatan[1].catatan=='Meta B'

@pytest.mark.parametrize('siapa',['budi','wahid','super'])
async def test_pratinjau_koreksi_akses_void_kunci_versi(klien,app_uji,siapa):
 from test_web import _jadi_super
 tid=await tiket()
 if siapa=='super':await _jadi_super(app_uji)
 await login(klien,'wahid' if siapa=='super' else siapa)
 d=payload((await klien.get(f'/timbangan/transaksi/{tid}/koreksi')).text)
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);t.jumlah_revisi=1;await db.commit()
 r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi/pratinjau',data=d);assert r.status_code==409
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);t.status_transaksi='VOID';await db.commit()
 r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi/pratinjau',data=d);assert r.status_code==403

@pytest.mark.parametrize('berat',['0','-1','NaN','Infinity','25000'])
async def test_koreksi_bacaan_tiket_terbuka_tetap_menjalankan_batas_fisik(klien,berat):
 tid=await tiket(selesai=False);await login(klien);d=payload((await klien.get(f'/timbangan/transaksi/{tid}/koreksi')).text);d.update(timbang1_kg=berat,alasan='Periksa batas bacaan terbuka')
 r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi/pratinjau',data=d);assert r.status_code==422,r.text
 await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=d)
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);assert float(t.timbang1_kg)==15000 and t.status_tiket=='TERBUKA' and t.berat_barang_kg is None and t.jumlah_revisi==0

async def test_pratinjau_memakai_snapshot_bukan_master_baru(klien):
 from app.timbangan.models import TimbanganJenis
 tid=await tiket();await login(klien)
 async with database.SessionLocal() as db:
  m=await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode=='GABAH_BASAH'));m.ambang_nilai=0;await db.commit()
 d=payload((await klien.get(f'/timbangan/transaksi/{tid}/koreksi')).text);d.update(nama_sopir='Sopir Baru',alasan='Snapshot tetap')
 r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi/pratinjau',data=d);assert r.json()['nilai']['Status kontrol']=='NORMAL'
 await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=d)
 async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).status_kontrol=='NORMAL'

async def test_tara_retur_yang_diabaikan_bukan_revisi_fiktif(klien):
 tid=await tiket(arah='RETUR_MASUK',kode='RETUR_PELANGGAN');await login(klien)
 d=payload((await klien.get(f'/timbangan/transaksi/{tid}/koreksi')).text);d.update(tara_per_karung_kg='0.250',alasan='Tara retur tetap nol')
 r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi/pratinjau',data=d);assert r.json()['perubahan']==[]
 await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=d)
 async with database.SessionLocal() as db:
  t=await db.get(TimbanganTransaksi,tid);assert t.jumlah_revisi==0 and float(t.total_tara_kg)==0

async def test_endpoint_koreksi_tanpa_sesi_tidak_membaca_atau_mengubah(klien):
 from test_riwayat import snapshot
 tid=await tiket();before=await snapshot()
 for path in ['/koreksi','/koreksi/pratinjau','/jenis']:
  r=await klien.post(f'/timbangan/transaksi/{tid}'+path,data={'nama_sopir':'Tidak boleh','alasan':'Tanpa sesi','jenis_kode':'GABAH_KERING'})
  assert 'name="sandi"' in r.text or r.status_code in (401,403)
  assert 'tersedia' not in r.text and await snapshot()==before

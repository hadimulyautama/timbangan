"""Jumlah karung boleh menyusul, tetapi tiket baru tidak boleh selesai kosong."""
from uuid import uuid4
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganTransaksi, TimbanganAkun, TimbanganKiriman
from test_web import app_uji, klien, login  # noqa: F401
from test_kiriman_luring import headers
from test_formulir import tiket_uji, pasang_muatan, fields

async def post(klien,url,*,data,headers=None):
    if headers:data={**data,'kunci':headers['X-Timbangan-Kiriman']}
    return await klien.post(url,data=data,headers=headers)

ARAH=[('MASUK','GABAH_BASAH'),('KELUAR','PENGIRIMAN'),('TRANSFER','TRANSFER'),
      ('RETUR_MASUK','RETUR_PELANGGAN'),('RETUR_KELUAR','RETUR_SUPPLIER'),('BEBAS','BEBAS')]

@pytest.mark.parametrize('nilai',[0,-1,1.5,100001,float('nan'),float('inf')])
def test_jumlah_tidak_sah_ditolak(nilai):
    with pytest.raises(service.LayananError):
        service.periksa_jumlah_karung([SimpleNamespace(jumlah_karung=nilai)], wajib=True)

@pytest.mark.parametrize('arah,kode',ARAH)
async def test_pagar_layanan_sebelum_mutasi_berlaku_semua_arah(klien,arah,kode):
    tid=await tiket_uji(arah,kode)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);akun=await db.get(TimbanganAkun,1)
        awal=(t.timbang2_kg,t.tanggal,t.status_tiket)
        with pytest.raises(service.LayananError,match='Jumlah karung belum diisi'):
            await service.simpan_timbang_kedua(db,akun=akun,kode=t.kode,berat_kg=5000)
        assert (t.timbang2_kg,t.tanggal,t.status_tiket)==awal
        assert not t.muatan

@pytest.mark.parametrize('arah,kode',[x for x in ARAH if x[0]!='KELUAR'])
async def test_boleh_kosong_pertama_wajib_kedua_dan_sementara_tetap_aman(klien,arah,kode):
    tid=await tiket_uji(arah,kode);await login(klien)
    url=f'/timbangan/tiket/{tid}'
    berat='15000' if arah=='RETUR_KELUAR' else '5000'
    key=str(uuid4());payload={'berat_kg':berat,'aksi':'selesai'}
    r=await post(klien,url,data=payload,headers=headers(key))
    assert r.status_code==422 and not r.json()['tersimpan']
    assert 'Jumlah karung belum diisi' in r.text
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.status_tiket=='TERBUKA' and t.timbang2_kg is None
        assert await db.scalar(select(func.count()).select_from(TimbanganKiriman))==0
    r=await post(klien,url,data={**payload,'aksi':'sementara'},headers=headers(str(uuid4())))
    assert r.status_code==200 and r.json()['tersimpan']
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.status_tiket=='TERBUKA' and float(t.timbang2_kg)==float(berat)
    r=await post(klien,url,data={**payload,'jumlah_karung':'200'},headers=headers(key))
    assert r.status_code==200 and r.json()['tersimpan'],r.text
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.status_tiket=='SELESAI' and t.jumlah_karung==200
        if arah.startswith('RETUR'):assert float(t.total_tara_kg)==0

@pytest.mark.parametrize('arah,kode',[x for x in ARAH if x[0]!='KELUAR'])
async def test_jumlah_pertama_dipertahankan_dan_tampil_di_kedua(klien,arah,kode):
    await login(klien)
    r=await post(klien,'/timbangan/timbang/'+kode,data={
        'berat_kg':'5000' if arah=='RETUR_KELUAR' else '15000',
        'supplier_id':'1','pihak_nama':'Pihak Sintetis' if arah=='TRANSFER' else '',
        'nama_sopir':'Sopir Uji','nomor_polisi':'W 123 UJ','jumlah_karung':'123'})
    async with database.SessionLocal() as db:t=await db.scalar(select(TimbanganTransaksi));tid=t.id
    form=(await klien.get(f'/timbangan/tiket/{tid}')).text
    assert 'value="123"' in form
    r=await post(klien,f'/timbangan/tiket/{tid}',data={
        'berat_kg':'15000' if arah=='RETUR_KELUAR' else '5000','aksi':'selesai'})
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.status_tiket=='SELESAI' and t.jumlah_karung==123,r.text

@pytest.mark.parametrize('nilai',['0','-1','1,5','abc','NaN','100001'])
async def test_isian_kedua_tidak_boleh_dipotong_atau_diam_diam_memakai_lama(klien,nilai):
    tid=await tiket_uji('TRANSFER','TRANSFER');await login(klien)
    r=await post(klien,f'/timbangan/tiket/{tid}',data={'berat_kg':'5000','jumlah_karung':nilai},headers=headers(str(uuid4())))
    assert r.status_code==422 and not r.json()['tersimpan'],r.text
    async with database.SessionLocal() as db:
        assert (await db.get(TimbanganTransaksi,tid)).timbang2_kg is None

async def test_pengiriman_wajib_jumlah_dari_produksi_bukan_ketikan_manual(klien,monkeypatch):
    tid=await tiket_uji('KELUAR','PENGIRIMAN');await login(klien)
    calls=await pasang_muatan(monkeypatch,{'muatan':[{'jenis_kode':'BERAS','berat_kg':7000,'jumlah_karung':0,'tara_per_karung_kg':0}]})
    payload={'berat_kg':'12100','jumlah_karung':'999'}
    assert (await post(klien,f'/timbangan/tiket/{tid}/pratinjau',data=payload)).status_code==422
    r=await post(klien,f'/timbangan/tiket/{tid}',data=payload,headers=headers(str(uuid4())))
    assert r.status_code==422 and not calls
    calls=await pasang_muatan(monkeypatch)
    r=await post(klien,f'/timbangan/tiket/{tid}',data=payload,headers=headers(str(uuid4())))
    assert r.status_code==200 and r.json()['tersimpan'],r.text
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t.jumlah_karung==140

async def test_tiket_selesai_lama_dengan_karung_nol_tetap_bisa_dibaca_dan_replay(klien):
    tid=await tiket_uji('TRANSFER','TRANSFER')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        t.status_tiket='SELESAI';t.timbang2_kg=5000;t.jumlah_karung=0
        await db.commit();akun=await db.get(TimbanganAkun,1)
        hasil=await service.simpan_timbang_kedua(db,akun=akun,kode=t.kode,berat_kg=5000)
        assert hasil.id==tid and hasil.jumlah_karung==0
    await login(klien);assert (await klien.get(f'/timbangan/transaksi/{tid}')).status_code==200

async def test_jasa_sekali_wajib_karung_saat_pertama(klien):
    await login(klien)
    payload={'berat_kg':'100','nama_sopir':'Sopir Uji','cara_timbang':'SEKALI','supplier_id':'1'}
    r=await post(klien,'/timbangan/timbang/BEBAS',data=payload,headers=headers(str(uuid4())))
    assert r.status_code==422
    r=await post(klien,'/timbangan/timbang/BEBAS',data={**payload,'jumlah_karung':'2'},headers=headers(str(uuid4())))
    assert r.status_code==200 and r.json()['tersimpan'],r.text
    async with database.SessionLocal() as db:
        t=await db.scalar(select(TimbanganTransaksi));assert t.status_tiket=='SELESAI' and t.jumlah_karung==2

async def test_partai_wajib_jumlah_total_sebelum_ditutup(klien):
    await login(klien)
    payload={'supplier_id':'1','berat_kg':['40','50'],'aksi':'selesai'}
    r=await post(klien,'/timbangan/partai/GABAH_KERING/baru',data=payload,headers=headers(str(uuid4())))
    assert r.status_code==422
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==0
    r=await post(klien,'/timbangan/partai/GABAH_KERING/baru',data={**payload,'aksi':'sementara','jumlah_karung':'2'},headers=headers(str(uuid4())))
    assert r.status_code==200 and r.json()['tersimpan']
    async with database.SessionLocal() as db:
        t=await db.scalar(select(TimbanganTransaksi));tid=t.id;assert t.muatan[0].jumlah_karung==2
    r=await post(klien,f'/timbangan/partai/{tid}',data={'aksi':'selesai','jumlah_karung':'2'},headers=headers(str(uuid4())))
    assert r.status_code==200 and r.json()['tersimpan']
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t.jumlah_karung==2 and float(t.berat_barang_kg)==90

@pytest.mark.parametrize('nilai',['0','-1','1,5','abc'])
async def test_koreksi_tidak_boleh_menghapus_jumlah_yang_sudah_ada(klien,nilai):
    tid=await tiket_uji('TRANSFER','TRANSFER')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);akun=await db.get(TimbanganAkun,1)
        await service.simpan_timbang_kedua(db,akun=akun,kode=t.kode,berat_kg=5000,
            muatan=[service.InputMuatan(jenis_kode='TRANSFER',jumlah_karung=12)])
    await login(klien,'wahid')
    r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data={
        'jumlah_karung':nilai,'alasan':'Koreksi jumlah uji sintetis'})
    assert r.status_code==200 and 'Jumlah karung' in r.text
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t.jumlah_karung==12 and t.muatan[0].jumlah_karung==12

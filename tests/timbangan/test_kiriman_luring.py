"""Tanda terima mengikat akun/isi dan disahkan atomik dengan transaksi lama."""
import json
import re
from uuid import uuid4

from sqlalchemy import select,func
import pytest

from test_web import app_uji,klien,login,kode_dari  # noqa: F401
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganTransaksi,TimbanganKiriman,TimbanganAudit
from app.timbangan.web import PREFIX


def headers(key,akun='1'):
    return {'X-Timbangan-Kiriman':key,'X-Timbangan-Akun':akun}


async def jumlah(model):
    async with database.SessionLocal() as db:return await db.scalar(select(func.count()).select_from(model))


async def timbang1(c,jenis='GABAH_BASAH',**more):
    key=kode_dari((await c.get(PREFIX+'/timbang/'+jenis)).text)
    data={'kunci':key,'berat_kg':'15000','supplier_id':'1','nomor_polisi':'W 1234 OF',
          'nama_sopir':'Sopir Uji','cara_timbang':'DUA_KALI',**more}
    return key,data


async def test_respons_hilang_dikirim_ulang_tanpa_transaksi_atau_audit_ganda(klien):
    await login(klien)
    key,data=await timbang1(klien)
    r=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(key))
    assert r.status_code==200 and r.json()['tersimpan']
    audit=await jumlah(TimbanganAudit)
    for _ in range(3):
        again=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(key))
        assert again.json()==r.json()
    assert await jumlah(TimbanganTransaksi)==1
    assert await jumlah(TimbanganKiriman)==1 and await jumlah(TimbanganAudit)==audit
    changed=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data={**data,'berat_kg':'14000'},headers=headers(key))
    assert changed.status_code==409
    await klien.post(PREFIX+'/keluar');await login(klien,'miftah')
    other=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(key,'2'))
    assert other.status_code==403


async def test_validasi_dan_sesi_bukan_tanda_tersimpan_dan_bisa_diperbaiki(klien):
    await login(klien)
    key,data=await timbang1(klien,berat_kg='0')
    r=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(key))
    assert r.status_code==422 and not r.json()['tersimpan']
    assert await jumlah(TimbanganTransaksi)==await jumlah(TimbanganKiriman)==0
    data['berat_kg']='15000'
    assert (await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(key))).json()['tersimpan']
    await klien.post(PREFIX+'/keluar')
    r=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(key))
    assert r.status_code==401 and not r.json()['tersimpan']


async def test_nama_pengganti_ditolak_dan_kiriman_bisa_diperbaiki(klien):
    await login(klien)
    key,data=await timbang1(klien,nama_sopir='LAIN-LAIN')
    r=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(key))
    assert r.status_code==422 and not r.json()['tersimpan']
    assert 'Isi nama sopir sebenarnya' in r.text
    assert await jumlah(TimbanganTransaksi)==await jumlah(TimbanganKiriman)==0
    data['nama_sopir']='Sopir Uji'
    r=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(key))
    assert r.status_code==200 and r.json()['tersimpan'],r.text
    assert await jumlah(TimbanganTransaksi)==await jumlah(TimbanganKiriman)==1


@pytest.mark.parametrize('aksi',['sementara','selesai'])
async def test_partai_multibaris_dan_penutupan_replay_tetap_satu(klien,aksi):
    await login(klien)
    key=str(uuid4());data={'kunci':key,'supplier_id':'1','berat_kg':['12,345','15,678'],'aksi':aksi,'jumlah_karung':'2'}
    r=await klien.post(PREFIX+'/partai/GABAH_KERING/baru',data=data,headers=headers(key))
    assert r.status_code==200 and r.json()['tersimpan'],r.text
    for _ in range(2):assert (await klien.post(PREFIX+'/partai/GABAH_KERING/baru',data=data,headers=headers(key))).json()==r.json()
    async with database.SessionLocal() as db:
        t=await db.scalar(select(TimbanganTransaksi))
        assert len(t.penimbangan)==2 and float(t.timbang1_kg)==28.023
        assert t.selesai==(aksi=='selesai')


async def test_partai_validasi_baris_berikut_rollback_seluruh_kiriman(klien):
    await login(klien)
    key=str(uuid4());data={'kunci':key,'supplier_id':'1','berat_kg':['12','900'],'aksi':'sementara'}
    r=await klien.post(PREFIX+'/partai/GABAH_KERING/baru',data=data,headers=headers(key))
    assert r.status_code==422 and not r.json()['tersimpan']
    assert await jumlah(TimbanganTransaksi)==await jumlah(TimbanganKiriman)==0
    data['berat_kg']=['12','13']
    assert (await klien.post(PREFIX+'/partai/GABAH_KERING/baru',data=data,headers=headers(key))).json()['tersimpan']


async def test_timbang_kedua_sementara_dan_selesai_dengan_kunci_berbeda(klien):
    await login(klien)
    first,data=await timbang1(klien)
    r=await klien.post(PREFIX+'/timbang/GABAH_BASAH',data=data,headers=headers(first))
    tid=int(re.search(r'/transaksi/(\d+)',r.json()['tujuan']).group(1))
    for aksi in ['sementara','selesai']:
        key=str(uuid4());payload={'kunci':key,'berat_kg':'5000','jumlah_karung':'100','tara_per_karung_kg':'0.25','aksi':aksi}
        r=await klien.post(PREFIX+f'/tiket/{tid}',data=payload,headers=headers(key))
        assert r.status_code==200 and r.json()['tersimpan'],r.text
        audit=await jumlah(TimbanganAudit)
        assert (await klien.post(PREFIX+f'/tiket/{tid}',data=payload,headers=headers(key))).json()==r.json()
        assert await jumlah(TimbanganAudit)==audit
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid)
            assert t.selesai==(aksi=='selesai')
            assert t.timbang2_kg==5000
    assert await jumlah(TimbanganTransaksi)==1


async def test_lanjut_partai_tutup_ulang_tidak_menambah_baris(klien):
    await login(klien)
    key=str(uuid4());data={'kunci':key,'supplier_id':'1','berat_kg':['10'],'aksi':'sementara'}
    r=await klien.post(PREFIX+'/partai/GABAH_KERING/baru',data=data,headers=headers(key))
    tid=int(re.search(r'/partai/(\d+)',r.json()['tujuan']).group(1))
    key=str(uuid4());payload={'kunci':key,'berat_kg':['12,345','13,678'],'aksi':'selesai','jumlah_karung':'3'}
    r=await klien.post(PREFIX+f'/partai/{tid}',data=payload,headers=headers(key))
    assert r.json()['tersimpan'],r.text
    assert (await klien.post(PREFIX+f'/partai/{tid}',data=payload,headers=headers(key))).json()==r.json()
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.selesai and len(t.penimbangan)==3 and t.timbang1_kg==36.023


async def test_pengiriman_receipt_komit_sebelum_integrasi_dan_replay_tidak_memanggil_lagi(klien,app_uji,monkeypatch):
    from fastapi import Request
    from app.timbangan.security import butuh_akun
    from app.timbangan.models import TimbanganAkun
    from app.timbangan import klien_produksi
    await login(klien)
    key,payload=await timbang1(klien,jenis='PENGIRIMAN',berat_kg='5000')
    first=await klien.post(PREFIX+'/timbang/PENGIRIMAN',data=payload,headers=headers(key))
    tid=int(re.search(r'/transaksi/(\d+)',first.json()['tujuan']).group(1))
    async with database.SessionLocal() as db:
        akun=await db.get(TimbanganAkun,1)
    akun.akun_id=123  # Aktor sintetis untuk batas HTTP; tidak ditulis ke DB.
    async def uji_aktor(request:Request):
        request.state.akun=akun;return akun
    app_uji.dependency_overrides[butuh_akun]=uji_aktor
    async def muatan(_):
        return {'muatan':[{'jenis_kode':'BERAS','nama':'Beras Sintetis','berat_kg':1000,'jumlah_karung':20,'tara_per_karung_kg':0.1}]}
    calls=[]
    async def integrasi(tiket,aktor):
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid)
            assert t.selesai
            assert await db.scalar(select(func.count()).select_from(TimbanganKiriman))==2
        calls.append((tiket,aktor))
        raise klien_produksi.ProduksiTakTersedia('Gangguan sintetis sesudah timbang disimpan')
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',muatan)
    monkeypatch.setattr(klien_produksi,'selesaikan_pengiriman',integrasi)
    key=str(uuid4());payload={'kunci':key,'berat_kg':'6000','aksi':'selesai'}
    r=await klien.post(PREFIX+f'/tiket/{tid}',data=payload,headers=headers(key))
    assert r.status_code==200 and r.json()['tersimpan'] and r.json()['peringatan']
    assert 'gagal' in r.json()['pesan']
    again=await klien.post(PREFIX+f'/tiket/{tid}',data=payload,headers=headers(key))
    assert again.json()==r.json() and calls==[(tid,123)]

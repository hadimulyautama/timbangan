"""Bukti balapan kiriman pada constraint/row lock PostgreSQL sungguhan."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select,func

from app.timbangan import service
from app.timbangan.models import ROLE_PETUGAS,TimbanganAkun,TimbanganTransaksi,TimbanganKiriman,TimbanganAudit
from app.timbangan.security import buat_token,NAMA_COOKIE


async def aktor(mesin):
    async with mesin() as db:
        a=TimbanganAkun(username='offline',nama='Petugas Sintetis',role=ROLE_PETUGAS,password_hash='x',perangkat_kode='U1')
        from app.models import Supplier
        db.add(Supplier(nama_supplier='Pemasok Sintetis',kledo_contact_id=990001))
        db.add(a);await db.commit();return a


async def test_sepuluh_kiriman_bersamaan_satu_receipt_satu_timbang(mesin,klien):
    a=await aktor(mesin);key=str(uuid4())
    payload={'kunci':key,'berat_kg':'15000','supplier_id':'1','nomor_polisi':'W 12 OF','nama_sopir':'Sopir Sintetis'}
    h={'Cookie':NAMA_COOKIE+'='+buat_token(a.id),'X-Timbangan-Kiriman':key,'X-Timbangan-Akun':str(a.id)}
    results=await asyncio.gather(*[klien.post('/timbangan/timbang/GABAH_BASAH',data=payload,headers=h) for _ in range(10)])
    assert all(r.status_code==200 and r.json()['tersimpan'] for r in results),[r.text for r in results]
    assert all(r.json()==results[0].json() for r in results)
    async with mesin() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==1
        assert await db.scalar(select(func.count()).select_from(TimbanganKiriman))==1
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit).where(TimbanganAudit.aksi=='SIMPAN_TIMBANG_1'))==1


async def test_dua_tambahan_partai_bersamaan_tidak_saling_menimpa(mesin,klien):
    a=await aktor(mesin)
    async with mesin() as db:
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(
            kunci=str(uuid4()),arah='MASUK',jenis_kode='GABAH_KERING',berat_kg=10,cara_timbang='PARTAI',supplier_id=1))
        tid=t.id
    async def tambah(w):
        key=str(uuid4())
        return await klien.post(f'/timbangan/partai/{tid}',data={'kunci':key,'berat_kg':str(w),'aksi':'sementara'},
            headers={'Cookie':NAMA_COOKIE+'='+buat_token(a.id),'X-Timbangan-Kiriman':key,'X-Timbangan-Akun':str(a.id)})
    rs=await asyncio.gather(tambah(11),tambah(12))
    assert all(r.status_code==200 for r in rs),[r.text for r in rs]
    async with mesin() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert len(t.penimbangan)==3 and t.timbang1_kg==33


async def test_objek_lama_di_sesi_tidak_menimpa_timbang_yang_baru_selesai(mesin):
    a=await aktor(mesin)
    async with mesin() as db:
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(
            kunci=str(uuid4()),arah='TRANSFER',jenis_kode='TRANSFER',berat_kg=15000,nomor_polisi='W 21 OF',nama_sopir='Uji',pihak_nama='Uji'))
        kode=t.kode
    async with mesin() as sesi_lama:
        await service.ambil_kode(sesi_lama,kode)
        async with mesin() as db:
            await service.simpan_timbang_kedua(db,akun=a,kode=kode,berat_kg=5000,
                muatan=[service.InputMuatan(jenis_kode='TRANSFER',jumlah_karung=200)])
        with pytest.raises(service.LayananError,match='sudah diselesaikan'):
            await service.simpan_timbang_kedua(sesi_lama,akun=a,kode=kode,berat_kg=4000,
                muatan=[service.InputMuatan(jenis_kode='TRANSFER',jumlah_karung=200)])

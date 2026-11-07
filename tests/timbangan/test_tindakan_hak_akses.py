"""Pembatasan tetap di server pada tiket terkunci dan dibatalkan."""
import pytest
from test_web import app_uji,klien,login
from test_koreksi_antarmuka import tiket
from test_rincian_retur import tautkan
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganTransaksi
from hmu_identitas import peran as P

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
@pytest.mark.parametrize('state',['terkunci','batal'])
async def test_pilihan_dan_endpoint_mengikuti_status(klien,role,state):
    tid=await tiket();await tautkan('budi',role);await login(klien,'budi')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);t.terkunci=state=='terkunci'
        if state=='batal':t.status_transaksi='VOID'
        await db.commit();await db.refresh(t);versi=service.versi_tiket(t);awal=t.nama_sopir
    allowed=state=='terkunci' and role!=P.OPERATOR
    r=await klien.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200
    assert (f'href="/timbangan/transaksi/{tid}/koreksi"' in r.text)==allowed
    koreksi=await klien.get(f'/timbangan/transaksi/{tid}/koreksi',follow_redirects=False)
    assert (koreksi.status_code==200)==allowed
    if not allowed:
        await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data={'versi':versi,'nama_sopir':'Perubahan yang dilarang','alasan':'Uji izin server'})
        async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).nama_sopir==awal

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_tiket_terbuka_tetap_boleh_dibatalkan(klien,role):
    tid=await tiket(selesai=False);await tautkan('budi',role);await login(klien,'budi')
    r=await klien.get(f'/timbangan/transaksi/{tid}');assert 'Hapus tiket ini' in r.text
    await klien.post(f'/timbangan/transaksi/{tid}/batal',data={'alasan':'Tiket uji batal sebelum timbang kedua'})
    async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).status_transaksi=='VOID'

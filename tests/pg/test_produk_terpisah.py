"""Sesi TeraFlow mematuhi aktivasi dan peran produknya, bukan PadiFlow."""
import uuid
from unittest.mock import patch
import pytest
from fastapi import Depends
from sqlalchemy import select
from hmu_core import User,Perusahaan,KeanggotaanPerusahaan,ProdukAplikasiPerusahaan as CP,AksesProdukAnggota as UP,IntegrasiProdukPerusahaan as CI
from hmu_identitas import peran as P
from hmu_identitas.produk import PADIFLOW,TERAFLOW,INTEGRASI
from app.timbangan.models import TimbanganAkun
from app.timbangan import security as sec,klien_produksi as client
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def orang(mesin,monkeypatch):
    async with mesin() as db:
        co=Perusahaan(kode='produk-uji',nama='Perusahaan uji');user=User(nama='Petugas uji',role=P.ADMIN,status='aktif');db.add_all([co,user]);await db.flush()
        member=KeanggotaanPerusahaan(company_id=co.id,user_id=user.id,aktif=True,peran=P.OPERATOR)
        profile=TimbanganAkun(username='petugas-uji',nama='Petugas uji',role=P.ke_timbangan(P.ADMIN),password_hash='x',perangkat_kode='P1',user_id=user.id)
        db.add_all([member,profile]);db.add_all([CP(company_id=co.id,produk=p,aktif=True,warisan=True) for p in (PADIFLOW,TERAFLOW)]);await db.flush()
        db.add(CI(company_id=co.id,kode=INTEGRASI,aktif=False));db.add(UP(company_id=co.id,user_id=user.id,produk=TERAFLOW,aktif=True,peran=P.OPERATOR));await db.commit()
        data=dict(cid=co.id,uid=user.id,pid=profile.id)
    monkeypatch.setenv('HMU_COMPANY_ID',str(data['cid']));monkeypatch.setenv('HMU_RUANG_DATA',str(uuid.uuid4()));monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI','0')
    return data

async def test_sesi_tf_tetap_berjalan_saat_pf_nonaktif_dan_peran_master_tidak_berubah(mesin,klien,orang):
    x=orang
    @klien._transport.app.get('/uji/hak')
    async def hak(akun=Depends(sec.butuh_akun)):return dict(role=akun.role,admin=akun.is_admin)
    klien.cookies.set(sec.NAMA_COOKIE,sec.buat_token(x['pid']))
    async with mesin() as db:
        (await db.get(CP,(x['cid'],PADIFLOW))).aktif=False;await db.commit()
    r=await klien.get('/uji/hak');assert r.status_code==200 and r.json()==dict(role=P.ke_timbangan(P.OPERATOR),admin=False)
    async with mesin() as db:
        assert (await db.get(User,x['uid'])).role==P.ADMIN
        assert (await db.get(TimbanganAkun,x['pid'])).role==P.ke_timbangan(P.ADMIN)
        grant=await db.get(UP,(x['cid'],x['uid'],TERAFLOW));grant.peran=P.ADMIN;await db.commit()
    assert (await klien.get('/uji/hak')).json()['admin']
    async with mesin() as db:
        (await db.get(UP,(x['cid'],x['uid'],TERAFLOW))).aktif=False;await db.commit()
    r=await klien.get('/uji/hak');assert r.status_code==403 and 'TeraFlow'.lower() in r.text.lower()

async def test_tf_nonaktif_menolak_cookie_lama_dan_pf_tidak_berubah(mesin,klien,orang):
    x=orang
    @klien._transport.app.get('/uji/hak')
    async def hak(akun=Depends(sec.butuh_akun)):return dict(role=akun.role)
    klien.cookies.set(sec.NAMA_COOKIE,sec.buat_token(x['pid']))
    async with mesin() as db:
        (await db.get(CP,(x['cid'],TERAFLOW))).aktif=False;await db.commit()
    assert (await klien.get('/uji/hak')).status_code==403
    async with mesin() as db:assert (await db.get(CP,(x['cid'],PADIFLOW))).aktif

async def test_integrasi_nonaktif_tidak_memanggil_http_dan_timbang_mandiri_tetap_bisa(mesin,klien,orang,monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(client,'settings',replace(client.settings,produksi_api_url='https://pf.uji',produksi_api_token='uji'))
    with patch.object(client.httpx,'AsyncClient') as http:
        with pytest.raises(client.ProduksiDilarang,match='Integrasi'):
            await client.muatan_pengiriman(123)
        http.assert_not_called()
    klien.cookies.set(sec.NAMA_COOKIE,sec.buat_token(orang['pid']))
    assert (await klien.get('/timbangan/')).status_code==200

async def test_profil_lama_tanpa_tautan_hmu_tetap_bisa_bekerja(mesin,klien,orang):
    async with mesin() as db:
        p=TimbanganAkun(username='petugas-lama',nama='Petugas lama',role=P.ke_timbangan(P.OPERATOR),password_hash='x',perangkat_kode='P2');db.add(p);await db.commit();pid=p.id
    @klien._transport.app.get('/uji/hak')
    async def hak(akun=Depends(sec.butuh_akun)):return dict(role=akun.role)
    klien.cookies.set(sec.NAMA_COOKIE,sec.buat_token(pid))
    r=await klien.get('/uji/hak');assert r.status_code==200 and r.json()['role']==P.ke_timbangan(P.OPERATOR)


async def test_anggota_lintas_perusahaan_tidak_memakai_peran_master_sebagai_akses_warisan(mesin,klien,orang):
    x=orang
    async with mesin() as db:
        company=Perusahaan(kode='asing',nama='Perusahaan lain');db.add(company);await db.flush()
        db.add(KeanggotaanPerusahaan(company_id=company.id,user_id=x['uid'],aktif=True,peran=P.ADMIN))
        grant=await db.get(UP,(x['cid'],x['uid'],TERAFLOW));await db.delete(grant);await db.commit()
    klien.cookies.set(sec.NAMA_COOKIE,sec.buat_token(x['pid']))
    assert (await klien.get('/timbangan/')).status_code==403
    async with mesin() as db:
        db.add(UP(company_id=x['cid'],user_id=x['uid'],produk=TERAFLOW,aktif=True,peran=P.OPERATOR));await db.commit()
    assert (await klien.get('/timbangan/')).status_code==200


async def test_penolakan_produk_bukan_salah_sandi_dan_tidak_menahan_setelah_dipulihkan(mesin,klien,orang,monkeypatch):
    from hmu_identitas.model import Akun
    from hmu_identitas.sandi import hash_sandi
    from app.timbangan import gerbang_masuk as gerbang,monitoring
    x=orang;gerbang.bersihkan();events=[]
    monkeypatch.setattr(monitoring,'catat_login',lambda request,kode:events.append(kode))
    async with mesin() as db:
        a=Akun(user_id=x['uid'],username='petugas-uji',password_hash=hash_sandi('sandi-audit-produk-123'),status='aktif');db.add(a);await db.flush()
        (await db.get(TimbanganAkun,x['pid'])).akun_id=a.id
        for code in (PADIFLOW,TERAFLOW):
            row=await db.get(CP,(x['cid'],code));row.warisan=False;row.aktif=False
        await db.commit()
    try:
        for _ in range(gerbang.BATAS_GAGAL+2):
            r=await klien.post('/timbangan/masuk',data=dict(username='petugas-uji',sandi='sandi-audit-produk-123'))
            assert r.status_code==200 and 'tidak diaktifkan' in r.text
        assert events==['peran']*(gerbang.BATAS_GAGAL+2)
        async with mesin() as db:(await db.get(CP,(x['cid'],TERAFLOW))).aktif=True;await db.commit()
        r=await klien.post('/timbangan/masuk',data=dict(username='petugas-uji',sandi='sandi-audit-produk-123'))
        assert r.status_code==303 and sec.NAMA_COOKIE in r.cookies
    finally:gerbang.bersihkan()


async def test_sandi_salah_tetap_dibatasi_pada_produk_nonaktif(mesin,klien,orang):
    from hmu_identitas.model import Akun
    from hmu_identitas.sandi import hash_sandi
    from app.timbangan import gerbang_masuk as gerbang
    gerbang.bersihkan()
    async with mesin() as db:
        db.add(Akun(user_id=orang['uid'],username='petugas-uji',password_hash=hash_sandi('sandi-yang-benar-123'),status='aktif'))
        (await db.get(CP,(orang['cid'],TERAFLOW))).aktif=False;await db.commit()
    try:
        for _ in range(gerbang.BATAS_GAGAL):
            r=await klien.post('/timbangan/masuk',data=dict(username='petugas-uji',sandi='sandi-salah'))
            assert 'sandi salah' in r.text
        r=await klien.post('/timbangan/masuk',data=dict(username='petugas-uji',sandi='sandi-salah'))
        assert 'Terlalu banyak percobaan' in r.text
    finally:gerbang.bersihkan()

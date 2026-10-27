"""Kategori Pengaturan: kontrak HTTP nyata, SQLite baru per kasus; Produksi tiruan."""
import pytest
from sqlalchemy import select, func
from test_web import app_uji, klien, login, _jadi_super, _master_tara_kemasan
from app import database
from app.timbangan import setelan, klien_produksi
from app.timbangan.routes import master
from app.timbangan.models import TimbanganConfig, TimbanganAudit, TimbanganTransaksi, TimbanganCetak
from app.timbangan.web import PREFIX

@pytest.fixture(autouse=True)
def produksi_terpisah(monkeypatch):
    async def status():
        return dict(terkonfigurasi=True, sedang_berjalan=False, hasil_terakhir=None, gagal_terakhir=None, selesai_pada=None)
    monkeypatch.setattr(klien_produksi, 'status_sinkron_kontak', status)

@pytest.mark.parametrize('siapa,super_aktif,n', [('budi',False,4),('wahid',False,6),('wahid',True,5),('miftah',True,6)])
async def test_kategori_berdasarkan_kewenangan(klien,app_uji,siapa,super_aktif,n):
    if super_aktif:await _jadi_super(app_uji,'miftah')
    await login(klien,siapa)
    r=await klien.get(PREFIX+'/pengaturan');assert r.status_code==200
    assert r.text.count('class="set-kategori__baris"')==n
    assert 'name="nilai"' not in r.text and 'name="sandi_lama"' not in r.text
    assert 'name="printer_url"' not in r.text
    for b in ('akun','printer','aturan','sistem'):
        assert (await klien.get(PREFIX+'/pengaturan?bagian='+b)).status_code==200
    for b,allowed in [('pihak',siapa!='budi'),('pengguna',siapa=='miftah' or (siapa=='wahid' and not super_aktif))]:
        assert (await klien.get(PREFIX+'/pengaturan?bagian='+b)).status_code==(200 if allowed else 403)

async def test_hanya_kategori_pihak_membaca_produksi(klien,monkeypatch):
    calls=[]
    async def fail():calls.append(1);raise klien_produksi.ProduksiTakTersedia('Gangguan sintetis')
    monkeypatch.setattr(klien_produksi,'status_sinkron_kontak',fail)
    await login(klien,'wahid')
    for bagian in ('','akun','printer','aturan','sistem','operasional','pengguna'):
        assert (await klien.get(PREFIX+'/pengaturan?bagian='+bagian)).status_code==200
    assert not calls
    r=await klien.get(PREFIX+'/pengaturan?bagian=pihak')
    assert 'Tak bisa menghubungi sistem produksi' in r.text and calls==[1]

@pytest.mark.parametrize('state,pesan,disabled',[
    ('unreachable','Tak bisa menghubungi sistem produksi',True),
    ('off','Kledo belum tersambung',True),('running','Sedang berjalan',True),
    ('failed','Percobaan terakhir',False),('ok','UJI pembaruan berhasil',False),
    ('never','Belum pernah dijalankan',False)])
async def test_enam_status_kledo(klien,monkeypatch,state,pesan,disabled):
    async def status():
        if state=='unreachable':raise klien_produksi.ProduksiTakTersedia('Jaringan uji putus')
        return dict(terkonfigurasi=state!='off',sedang_berjalan=state=='running',
                    hasil_terakhir='UJI pembaruan berhasil' if state=='ok' else None,
                    gagal_terakhir='UJI gagal' if state=='failed' else None,selesai_pada=None)
    monkeypatch.setattr(klien_produksi,'status_sinkron_kontak',status)
    await login(klien,'wahid');r=await klien.get(PREFIX+'/pengaturan?bagian=pihak')
    assert pesan in r.text
    import re
    btn=re.search(r'<form[^>]+kledo-kontak[^>]*>\s*<button([^>]+)>',r.text).group(1)
    assert ('disabled' in btn)==disabled
    assert 'name="api_key"' not in r.text

@pytest.mark.parametrize('hasil',[True,False,'gagal'])
async def test_pemicu_kledo_tidak_mengaku_selesai(klien,monkeypatch,hasil):
    calls=[]
    async def mulai():
        calls.append(1)
        if hasil=='gagal':raise klien_produksi.ProduksiTakTersedia('UJI tidak tersambung')
        return hasil
    monkeypatch.setattr(klien_produksi,'mulai_sinkron_kontak',mulai)
    await login(klien,'wahid');r=await klien.post(PREFIX+'/pengaturan/kledo-kontak')
    assert calls==[1] and 'bagian=pihak' in str(r.url)
    assert ('dimulai' if hasil is True else 'sudah berjalan' if hasil is False else 'tidak tersambung') in r.text
    assert 'pembaruan selesai' in r.text # penjelasan: diterima BELUM berarti selesai

@pytest.mark.parametrize('bagian',['','akun','printer','aturan','sistem','operasional'])
async def test_get_tidak_memutasi_konfigurasi_tiket_audit_cetak(klien,bagian):
    await login(klien,'wahid')
    async def counts():
        async with database.SessionLocal() as db:
            return [await db.scalar(select(func.count()).select_from(m)) for m in (TimbanganConfig,TimbanganAudit,TimbanganTransaksi,TimbanganCetak)]
    before=await counts();await klien.get(PREFIX+'/pengaturan?bagian='+bagian);assert await counts()==before

async def test_seluruh_parameter_dan_prioritas_reset(klien,app_uji,monkeypatch):
    from app.timbangan.config import tsettings
    await _jadi_super(app_uji);await login(klien,'wahid')
    from dataclasses import replace
    monkeypatch.setattr(setelan,'tsettings',replace(tsettings,jam_kunci_otomatis=37))
    for d in setelan.DAFTAR:
        r=await klien.get(PREFIX+'/pengaturan?bagian=operasional')
        assert f'name="kunci" value="{d.kunci}"' in r.text
    r=await klien.post(PREFIX+'/pengaturan',data={'kunci':'jam_kunci_otomatis','nilai':'48','aksi':'simpan'})
    assert 'bagian=operasional' in str(r.url) and 'value="48"' in r.text
    r=await klien.post(PREFIX+'/pengaturan',data={'kunci':'jam_kunci_otomatis','aksi':'bawaan'})
    assert 'kembali ke bawaan 37 jam' in r.text and 'value="37"' in r.text
    async with database.SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganConfig))==0
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit).where(TimbanganAudit.aksi=='UBAH_SETELAN'))==2

@pytest.mark.parametrize('nilai',['NaN','Infinity','-1','200001','abc',''])
async def test_validasi_super_tidak_mengubah_nilai(klien,app_uji,nilai):
    await _jadi_super(app_uji);await login(klien,'wahid')
    r=await klien.post(PREFIX+'/pengaturan',data={'kunci':'kapasitas_jembatan_kg','nilai':nilai})
    assert 'err=' in str(r.url)
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganConfig))==0

async def test_bagian_tidak_dikenal_aman_dan_url_lama_tetap(klien):
    await login(klien)
    for path in ['/pengaturan?bagian=../../akun','/printer?dari=cetak','/akun?ok=UJI','/aturan']:
        assert (await klien.get(PREFIX+path)).status_code==200
    r=await klien.get(PREFIX+'/printer?dari=cetak')
    assert 'Pos &amp; printer' in r.text and 'data-periksa-printer' in r.text
    assert '/pengaturan' in r.text

async def test_master_belum_tersedia_terisolasi(klien,monkeypatch):
    async def kosong(db):return None
    monkeypatch.setattr(master.kemasan_tara,'daftar',kosong)
    await login(klien,'wahid')
    r=await klien.get(PREFIX+'/pengaturan?bagian=aturan')
    assert 'Master tara belum tersedia' in r.text and 'Aturan komoditas' in r.text

async def test_parameter_rahasia_dan_skema_hanya_admin(klien,monkeypatch):
    async def info():return dict(versi='92',komit='uji',revisi='lama',head='baru',keadaan='tertinggal')
    monkeypatch.setattr(master._versi,'info',info)
    await login(klien)
    r=await klien.get(PREFIX+'/pengaturan?bagian=sistem')
    assert 'data-uji="skema-tertinggal"' not in r.text and 'Kunci penanda sesi' not in r.text
    await login(klien,'wahid');r=await klien.get(PREFIX+'/pengaturan?bagian=sistem')
    assert 'data-uji="skema-tertinggal"' in r.text and 'Kunci penanda sesi' in r.text

async def test_master_gagal_simpan_tidak_merusak_kategori_lain(klien):
    await login(klien,'wahid')
    r=await klien.post(PREFIX+'/pengaturan/tara-kemasan',data={'tara_id':'1','tara_per_karung_kg':'0,0858'})
    assert 'Master tara kemasan belum tersedia' in r.text and 'err=' in str(r.url)
    assert (await klien.get(PREFIX+'/pengaturan?bagian=sistem')).status_code==200

async def test_master_tara_tidak_mengubah_snapshot_historis(klien):
    from test_rincian_supplier import tiket
    from app.timbangan.models import TimbanganMuatan
    await _master_tara_kemasan();tid=await tiket();await login(klien,'wahid')
    async def rekam():
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid)
            rows=(await db.scalars(select(TimbanganMuatan).where(TimbanganMuatan.transaksi_id==tid))).all()
            return ({c.name:getattr(t,c.name) for c in t.__table__.columns},
                    [{c.name:getattr(x,c.name) for c in x.__table__.columns} for x in rows])
    before=await rekam()
    r=await klien.post(PREFIX+'/pengaturan/tara-kemasan',data={'tara_id':'1','tara_per_karung_kg':'0,0858'})
    assert 'tersimpan' in r.text and await rekam()==before

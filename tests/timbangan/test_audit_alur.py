"""Probe baca kode dan SQLite sintetis, tidak menyentuh produksi."""
from datetime import date,timedelta
import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from sqlalchemy import select
from test_service import masuk_gabah
from test_web import app_uji,klien,login
from test_cetak_pratinjau import siapkan
from test_rincian_supplier import tiket
from app.timbangan import service,gerbang_masuk,cetak,logic
from app.timbangan.models import TimbanganAudit,TimbanganTransaksi
from app.timbangan.routes.pos import _angka

@pytest.mark.parametrize('nilai',['0,2x5','abc','nan','inf','-inf'])
def test_angka_tidak_sah_tidak_boleh_dianggap_nol(nilai):
    with pytest.raises(logic.ValidasiError):_angka(nilai)
    assert _angka('',.25)==.25
    assert _angka('0,25')==.25

@pytest.mark.usefixtures('jenis_tersemai')
async def test_jumlah_bobot_sementara_harus_positif(db,petugas,supplier):
    t=await service.simpan_timbang_pertama(db,akun=petugas,data=masuk_gabah('AUDIT-NOL',supplier.id,15000))
    with pytest.raises(service.LayananError):
        await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=0,selesaikan=False)

@pytest.mark.usefixtures('jenis_tersemai')
async def test_metode_timbang_tidak_dikenal_tidak_boleh_membuka_tiket(db,petugas,supplier):
    d=masuk_gabah('AUDIT-METODE',supplier.id,15000);d.cara_timbang='METODE-TIDAK-ADA'
    with pytest.raises(service.LayananError):
        await service.simpan_timbang_pertama(db,akun=petugas,data=d)

@pytest.mark.usefixtures('jenis_tersemai')
async def test_hapus_jasa_menyimpan_identitas_pemilik_di_audit(db,super_admin,pelanggan_kledo):
    t=TimbanganTransaksi(kode='AUDIT-JASA',tanggal=date.today(),arah='MASUK',jenis_kode='PK',jasa=True,pelanggan_id=pelanggan_kledo.id,timbang1_kg=1000,status_tiket='TERBUKA',dibuat_oleh_id=super_admin.id)
    db.add(t);await db.commit()
    await service.hapus_transaksi(db,akun=super_admin,trx=t,alasan='Uji audit lokal')
    a=await db.scalar(select(TimbanganAudit).where(TimbanganAudit.aksi=='HAPUS_TRANSAKSI'))
    x=json.loads(a.nilai_sebelum) if isinstance(a.nilai_sebelum,str) else a.nilai_sebelum
    assert x.get('pelanggan_id')==pelanggan_kledo.id and x.get('jasa') is True, x

def test_login_gagal_kedaluwarsa_tidak_menetap_di_memori():
    gerbang_masuk.bersihkan()
    with patch.object(gerbang_masuk.time,'monotonic',return_value=0):
        for i in range(500):gerbang_masuk.catat_gagal('nama'+str(i),'127.0.0.1')
    with patch.object(gerbang_masuk.time,'monotonic',return_value=3600):
        gerbang_masuk.boleh_coba('baru','127.0.0.1')
    n=len(gerbang_masuk._gagal);gerbang_masuk.bersihkan()
    assert n<=1,f'{n} pasangan username/IP lama tetap disimpan'

async def test_admin_bisa_melihat_pekerjaan_cetak_petugas_sebelumnya(klien):
    tid=await tiket();await login(klien,'budi');j,_=await siapkan(klien,tid)
    await klien.post(f'/timbangan/transaksi/{tid}/cetak/pekerjaan/'+j['kunci']+'/kirim',json={})
    await login(klien,'wahid')
    x=(await klien.get(f'/timbangan/transaksi/{tid}/cetak/konteks')).json()
    from uuid import uuid4
    blocked=await klien.post(f'/timbangan/transaksi/{tid}/cetak/pekerjaan',json={'kunci':uuid4().hex,'sidik':x['sidik'],'format':'80MM','keluaran':'printer','alasan':''})
    assert blocked.status_code==409 and 'Masih ada pekerjaan' in blocked.text
    assert x['pekerjaan'] is not None, 'Admin tidak melihat pekerjaan aktif milik petugas sebelumnya'


@pytest.mark.parametrize('tabel',['finished_goods_stock','byproduct_stock'])
@pytest.mark.usefixtures('jenis_tersemai')
async def test_tiket_sumber_stok_produk_padiflow_tidak_boleh_void(db,admin,supplier,tabel):
    from sqlalchemy import text
    d=masuk_gabah('AUDIT-PRODUK',supplier.id,15000)
    d.jenis_kode='BERAS_MASUK' if tabel=='finished_goods_stock' else 'BROKEN_MASUK'
    d.muatan[0].jenis_kode=d.jenis_kode
    t=await service.simpan_timbang_pertama(db,akun=admin,data=d)
    t=await service.simpan_timbang_kedua(db,akun=admin,kode=t.kode,berat_kg=5000)
    await db.execute(text('CREATE TABLE '+tabel+' (id INTEGER PRIMARY KEY, source_type VARCHAR(30),source_id INTEGER,berat_kg REAL)'))
    await db.execute(text('INSERT INTO '+tabel+"(id,source_type,source_id,berat_kg) VALUES(1,'timbangan',:tid,9970)"),{'tid':t.id})
    await db.commit()
    with pytest.raises(service.LayananError):
        await service.void_transaksi(db,akun=admin,trx=t,alasan='Uji konsistensi aplikasi')

@pytest.mark.usefixtures('jenis_tersemai')
async def test_replay_partai_tidak_menukar_operator_awal(db,petugas,petugas2,supplier):
    from app.timbangan.models import CARA_PARTAI
    d=masuk_gabah('AUDIT-PARTAI',supplier.id,100);d.cara_timbang=CARA_PARTAI;d.nomor_polisi=None;d.nama_sopir=None
    t=await service.simpan_timbang_pertama(db,akun=petugas,data=d)
    await service.tambah_penimbangan(db,akun=petugas,kode=t.kode,berat_kg=50)
    lama=t.timbang1_petugas_id
    t=await service.simpan_timbang_pertama(db,akun=petugas2,data=d,komit=False)
    await db.commit()  # komit receipt PWA di kiriman.terima_kiriman
    await db.refresh(t)
    assert t.timbang1_petugas_id==lama, 'Replay tiket partai mengubah siapa penimbang awalnya'

@pytest.mark.usefixtures('jenis_tersemai')
async def test_replay_awal_selesai_beda_muatan_tidak_boleh_dibilang_tersimpan(db,petugas,supplier):
    from uuid import uuid4
    d=masuk_gabah('AUDIT-REPLAY-MUATAN',supplier.id,15000);d.kunci=str(uuid4())
    t=await service.simpan_timbang_pertama(db,akun=petugas,data=d)
    await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=5000)
    d.muatan[0].jumlah_karung=200
    with pytest.raises(service.LayananError):
        await service.simpan_timbang_pertama(db,akun=petugas,data=d)

@pytest.mark.usefixtures('jenis_tersemai')
async def test_replay_awal_terbuka_tidak_boleh_mengganti_supplier(db,petugas,supplier):
    from uuid import uuid4
    from app.models import Supplier
    lain=Supplier(nama_supplier='Supplier lain sintetis',kledo_contact_id=5002);db.add(lain);await db.commit()
    d=masuk_gabah('AUDIT-REPLAY-PEMILIK',supplier.id,15000);d.kunci=str(uuid4())
    t=await service.simpan_timbang_pertama(db,akun=petugas,data=d)
    d.supplier_id=lain.id
    with pytest.raises(service.LayananError):
        await service.simpan_timbang_pertama(db,akun=petugas,data=d)


def test_pagar_url_database_harus_memeriksa_hostname_bukan_substring():
    import importlib.util,os
    from urllib.parse import urlsplit
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('audit_guard',Path(__file__).resolve().parents[1]/'pg/conftest.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    with patch.dict(os.environ,{'UJI_PG_URL':'postgresql+asyncpg://127.0.0.1@db-luar.invalid/uji_sintetis'}):
        with pytest.raises(pytest.fail.Exception):mod._url()

@pytest.mark.parametrize('hasil',['dikonfirmasi','belum_tercetak'])
async def test_admin_menuntaskan_cetak_tanpa_mengganti_pencetak_semula(klien,hasil):
    from sqlalchemy import func
    from app import database
    from app.timbangan.models import TimbanganCetak,TimbanganAkun,TimbanganPekerjaanCetak
    tid=await tiket();await login(klien,'budi');j,_=await siapkan(klien,tid)
    base=f'/timbangan/transaksi/{tid}/cetak/pekerjaan/'+j['kunci']
    await klien.post(base+'/kirim',json={})
    async with database.SessionLocal() as sesi:
        budi=await sesi.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        pencetak=budi.id;budi.status='nonaktif';await sesi.commit()
    await login(klien,'wahid')
    konteks=(await klien.get(f'/timbangan/transaksi/{tid}/cetak/konteks')).json()
    assert konteks['pekerjaan']['boleh_menuntaskan']
    assert (await klien.post(base+'/kirim',json={})).status_code==409
    assert (await klien.post(base+'/hasil',json={'hasil':hasil})).status_code==409
    assert (await klien.post(base+'/hasil',json={'hasil':'printer_berhasil','alasan_penyelesaian':'Sudah diperiksa'})).status_code==409
    data={'hasil':hasil,'alasan_penyelesaian':'Kedua lembar diperiksa di akhir shift; pencetak semula sudah berhenti mengirim.'}
    for _ in range(2):assert (await klien.post(base+'/hasil',json=data)).status_code==200
    async with database.SessionLocal() as sesi:
        assert await sesi.scalar(select(func.count()).select_from(TimbanganCetak))==int(hasil=='dikonfirmasi')
        job=await sesi.get(TimbanganPekerjaanCetak,j['kunci']);assert job.oleh_id==pencetak
        audit=(await sesi.scalars(select(TimbanganAudit).where(TimbanganAudit.aksi=='TUNTASKAN_CETAK'))).all()
        wahid=await sesi.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        assert len(audit)==1 and audit[0].akun_id==wahid.id
        if hasil=='dikonfirmasi':assert (await sesi.scalar(select(TimbanganCetak))).oleh_id==pencetak

@pytest.mark.usefixtures('jenis_tersemai')
async def test_arsip_penerimaan_tetap_melindungi_tiket_setelah_stok_habis(db,admin,supplier):
    from sqlalchemy import text
    d=masuk_gabah('ARSIP-TIKET-1',supplier.id,15000);d.jenis_kode='BERAS_MASUK';d.muatan[0].jenis_kode=d.jenis_kode
    t=await service.simpan_timbang_pertama(db,akun=admin,data=d)
    await service.simpan_timbang_kedua(db,akun=admin,kode=t.kode,berat_kg=5000)
    await db.execute(text('CREATE TABLE activity_logs (id INTEGER PRIMARY KEY, action TEXT,table_name TEXT,aksi TEXT,field_name TEXT,old_value TEXT,new_value TEXT)'))
    await db.execute(text("INSERT INTO activity_logs VALUES(1,'INSERT','finished_goods_stock','produk_timbang_masuk','timbangan_transaksi_id',:tid,:nama)"),{'tid':str(t.id),'nama':t.kode+' · 9970.00 kg · Beras'})
    await db.commit()
    with pytest.raises(service.LayananError,match='arsip penerimaan'):
        await service.void_transaksi(db,akun=admin,trx=t,alasan='Uji arsip')

@pytest.mark.usefixtures('jenis_tersemai')
async def test_stok_tidak_terkait_tidak_menghalangi_tiket_baru(db,admin,supplier):
    from sqlalchemy import text
    t=await service.simpan_timbang_pertama(db,akun=admin,data=masuk_gabah('BEBAS-LINK',supplier.id,15000))
    await db.execute(text('CREATE TABLE finished_goods_stock (id INTEGER PRIMARY KEY,source_type TEXT,source_id INTEGER)'))
    await db.execute(text("INSERT INTO finished_goods_stock VALUES(1,'polishing',:tid)"),{'tid':t.id});await db.commit()
    await service.void_transaksi(db,akun=admin,trx=t,alasan='Truk batal masuk')
    assert t.status_transaksi=='VOID'

def test_memori_gagal_login_dibatasi_tanpa_mengubah_jeda_normal(monkeypatch):
    gerbang_masuk.bersihkan();monkeypatch.setattr(gerbang_masuk,'MAKS_KUNCI',16)
    for i in range(100):gerbang_masuk.catat_gagal(str(i),'127.0.0.1')
    assert len(gerbang_masuk._gagal)==16
    for _ in range(5):gerbang_masuk.catat_gagal('operator','127.0.0.1')
    assert gerbang_masuk.boleh_coba('operator','127.0.0.1')>0
    gerbang_masuk.catat_berhasil('operator','127.0.0.1')
    assert gerbang_masuk.boleh_coba('operator','127.0.0.1') is None
    gerbang_masuk.bersihkan()

@pytest.mark.usefixtures('jenis_tersemai')
async def test_replay_pertama_setelah_karung_dilengkapi_timbang_kedua(db,petugas,supplier):
    from uuid import uuid4
    d=masuk_gabah('REPLAY-AWAL-UTUH',supplier.id,15000);d.kunci=str(uuid4())
    t=await service.simpan_timbang_pertama(db,akun=petugas,data=d)
    muatan=[service.InputMuatan(jenis_kode=d.jenis_kode,jumlah_karung=200,tara_per_karung_kg=.25,berat_acuan_kg=10000)]
    await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=5000,muatan=muatan,catatan='Jumlah karung nyata')
    hasil=float(t.berat_barang_kg)
    ulang=await service.simpan_timbang_pertama(db,akun=petugas,data=d)
    assert ulang.id==t.id and ulang.selesai and float(ulang.berat_barang_kg)==hasil
    assert ulang.muatan[0].jumlah_karung==200 and ulang.catatan=='Jumlah karung nyata'
    d.muatan[0].jumlah_karung=99
    with pytest.raises(service.LayananError):
        await service.simpan_timbang_pertama(db,akun=petugas,data=d)

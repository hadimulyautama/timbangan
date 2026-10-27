"""Revisi tara umum: database sintetis per kasus, tanpa koneksi produksi."""
from datetime import timedelta
from decimal import Decimal
import re

import pytest
from sqlalchemy import select, func
from app import database
from app.timbangan import service, logic
from app.timbangan.db import sekarang
from app.timbangan.models import TimbanganTaraStandar, TimbanganMuatan, TimbanganTransaksi, TimbanganAudit, TimbanganJenis
from test_web import app_uji, klien, login, _jadi_super, kode_dari
from app.timbangan.web import PREFIX


async def histori(db, akun, supplier_id=None, nilai=.0858):
    # Data historis dibangun langsung sebagai fixture; bukan pintu pembuatan baru.
    row = TimbanganTaraStandar(jenis_kode='BERAS_PK', supplier_id=supplier_id,
        jumlah_sampel=100, total_berat_kg=nilai*100, tara_per_karung_kg=nilai,
        berlaku_mulai=sekarang().date()-timedelta(days=10),
        berlaku_sampai=sekarang().date()+timedelta(days=2), dibuat_oleh_id=akun.id)
    db.add(row); await db.flush(); return row


@pytest.mark.usefixtures('jenis_tersemai')
@pytest.mark.parametrize('khusus', [False, True])
async def test_saran_umum_tidak_membaca_sampling(db, petugas, supplier, monkeypatch, khusus):
    row = await histori(db, petugas, supplier.id if khusus else None)
    aturan = await service.aturan_untuk(db, 'BERAS_PK')
    async def dilarang(*a, **kw): raise AssertionError('Jalur baru membaca sampling')
    monkeypatch.setattr(service, 'tara_berlaku', dilarang)
    nilai, asal = await service.tara_disarankan(db, supplier_id=supplier.id, aturan=aturan)
    assert nilai == aturan.tara_bawaan_kg and asal is None
    assert row.status == 'BERLAKU' and float(row.tara_per_karung_kg) == .0858


@pytest.mark.usefixtures('jenis_tersemai')
async def test_service_lama_tidak_dapat_mencatat_sampling(db, admin2, supplier):
    row = await histori(db, admin2, supplier.id)
    before = {c.name:getattr(row,c.name) for c in row.__table__.columns}
    with pytest.raises(service.LayananError, match='tara umum'):
        await service.simpan_tara_standar(db, akun=admin2, supplier_id=supplier.id,
            jenis_kode='BERAS_PK', jumlah_sampel=100, total_berat_kg=20)
    assert await db.scalar(select(func.count()).select_from(TimbanganTaraStandar)) == 1
    assert {c.name:getattr(row,c.name) for c in row.__table__.columns} == before
    assert await db.scalar(select(func.count()).select_from(TimbanganAudit)) == 0


@pytest.mark.parametrize('who,allowed', [('budi',False),('wahid',True),('miftah',True)])
async def test_endpoint_lama_dan_menu(klien, app_uji, who, allowed):
    await _jadi_super(app_uji, 'miftah'); await login(klien, who)
    r = await klien.get(PREFIX+'/tara', follow_redirects=False)
    assert r.status_code == (303 if allowed else 403)
    if allowed: assert r.headers['location'] == PREFIX+'/pengaturan?bagian=aturan'
    for payload in ({}, dict(jenis_kode='BERAS_PK',jumlah_sampel='10',total_berat_kg='2')):
        r = await klien.post(PREFIX+'/tara',data=payload,follow_redirects=False)
        assert r.status_code == (410 if allowed else 403)
    for path in ['/pengaturan','/pengaturan?bagian=aturan','/aturan'] + (['/laporan'] if allowed else []):
        r=await klien.get(PREFIX+path); assert r.status_code==200
        assert 'href="'+PREFIX+'/tara"' not in r.text
        assert 'Catat sampling' not in r.text and 'Perbarui sampling' not in r.text
        assert 'action="'+PREFIX+'/tara"' not in r.text
    async with database.SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganTaraStandar)) == 0


async def tiket_lama(klien, tara):
    await login(klien)
    form=(await klien.get(PREFIX+'/timbang/BERAS_PK')).text
    r=await klien.post(PREFIX+'/timbang/BERAS_PK',data=dict(kunci=kode_dari(form),
        berat_kg='13600',supplier_id='1',nomor_polisi='AD 1234 UJ',nama_sopir='Slamet',
        cara_timbang='DUA_KALI',jumlah_karung='100',tara_per_karung_kg=str(tara),
        berat_acuan_kg='9000,125',nomor_acuan='UJI',tara_lain_kg='2'))
    assert 'err=' not in str(r.url), r.text[-1000:]
    async with database.SessionLocal() as db:
        t=await db.scalar(select(TimbanganTransaksi)); tid=t.id
        row=await histori(db, await db.get(service.TimbanganAkun,t.dibuat_oleh_id), t.supplier_id, tara)
        m=await db.scalar(select(TimbanganMuatan).where(TimbanganMuatan.transaksi_id==tid))
        m.tara_standar_id=row.id
        j=await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode=='BERAS_PK'))
        j.tara_bawaan_kg=.9
        await db.commit()
        return tid,row.id,t.aturan_snapshot


@pytest.mark.parametrize('tara', [.0858,0.0])
async def test_tiket_berjalan_presisi_referensi_dan_master_baru(klien,tara):
    tid,sid,snapshot=await tiket_lama(klien,tara)
    form=(await klien.get(PREFIX+f'/tiket/{tid}')).text
    raw=re.search(r'name="tara_per_karung_kg"[^>]*value="([^"]*)"',form)
    assert raw and Decimal(raw.group(1))==Decimal(str(tara)),raw
    assert f'#{sid}' in form
    data=dict(berat_kg='4600',jumlah_karung='100',tara_per_karung_kg=raw.group(1),
              berat_acuan_kg='9000,125',nomor_acuan='UJI',aksi='sementara')
    r=await klien.post(PREFIX+f'/tiket/{tid}',data=data)
    assert 'err=' not in str(r.url)
    async with database.SessionLocal() as db:
        m=await db.scalar(select(TimbanganMuatan).where(TimbanganMuatan.transaksi_id==tid))
        t=await db.get(TimbanganTransaksi,tid)
        assert float(m.tara_per_karung_kg)==tara and m.tara_standar_id==sid
        assert t.aturan_snapshot==snapshot and t.status_tiket=='TERBUKA' and t.berat_barang_kg is None
    data['aksi']='selesai'
    r=await klien.post(PREFIX+f'/tiket/{tid}',data=data)
    assert 'err=' not in str(r.url)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        m=await db.scalar(select(TimbanganMuatan).where(TimbanganMuatan.transaksi_id==tid))
        assert m.tara_standar_id==sid and float(m.tara_per_karung_kg)==tara
        assert t.status_tiket=='SELESAI' and t.aturan_snapshot==snapshot
        assert float(t.total_tara_kg)==pytest.approx(100*tara+2)
        assert float(t.berat_barang_kg)==pytest.approx(9000-100*tara-2)
        assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==1


@pytest.mark.usefixtures('jenis_tersemai')
async def test_nilai_tetap_dan_pengecualian_tetap_dari_master(db,supplier):
    for a in (await service.peta_aturan(db)).values():
        nilai,asal=await service.tara_disarankan(db,supplier_id=supplier.id,aturan=a)
        assert nilai==a.tara_default() and asal is None


@pytest.mark.usefixtures('jenis_tersemai','pelanggan_kledo')
async def test_replay_tiket_berjalan_tidak_mengganti_snapshot_dan_referensi(db,petugas,supplier):
    from test_service import masuk_gabah
    data=masuk_gabah('UJI-TARA-ULANG',supplier.id,13600)
    t=await service.simpan_timbang_pertama(db,akun=petugas,data=data)
    snapshot=t.aturan_snapshot
    row=await histori(db,petugas,supplier.id,.25)
    await db.refresh(t,['muatan']);t.muatan[0].tara_standar_id=row.id
    j=await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode=='GABAH_BASAH'))
    j.tara_tetap_kg=.7;j.ambang_nilai=999
    await db.commit()
    again=await service.simpan_timbang_pertama(db,akun=petugas,data=data)
    await db.refresh(again,['muatan'])
    assert again.id==t.id and again.aturan_snapshot==snapshot
    assert float(again.muatan[0].tara_per_karung_kg)==.25
    assert again.muatan[0].tara_standar_id==row.id
    assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==1


@pytest.mark.usefixtures('jenis_tersemai','pelanggan_kledo')
async def test_tiket_baru_menolak_referensi_sampling_dari_pemanggil_lama(db,petugas,supplier):
    from test_service import masuk_gabah
    row=await histori(db,petugas,supplier.id)
    data=masuk_gabah('UJI-SAMPLING-DITOLAK',supplier.id,13600)
    data.muatan[0].tara_standar_id=row.id
    with pytest.raises(service.LayananError,match='referensi sampling baru'):
        async with db.begin_nested():
            await service.simpan_timbang_pertama(db,akun=petugas,data=data,komit=False)
    assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==0
    assert await db.scalar(select(func.count()).select_from(TimbanganTaraStandar))==1


async def test_histori_utuh_dibaca_dan_koreksi_sopir_tidak_mengubah_tara(klien):
    tid,sid,snapshot=await tiket_lama(klien,.0858)
    await klien.post(PREFIX+f'/tiket/{tid}',data=dict(berat_kg='4600',jumlah_karung='100',
        tara_per_karung_kg='0,0858',berat_acuan_kg='9000,125',nomor_acuan='UJI',aksi='selesai'))
    async def rekam():
        async with database.SessionLocal() as db:
            t=(await service.ambil_transaksi(db,tid)).trx
            row=await db.get(TimbanganTaraStandar,sid)
            return ({c.name:getattr(t,c.name) for c in t.__table__.columns},
                    [{c.name:getattr(m,c.name) for c in m.__table__.columns} for m in t.muatan],
                    {c.name:getattr(row,c.name) for c in row.__table__.columns})
    before=await rekam()
    for path in [f'/transaksi/{tid}','/transaksi','/pengaturan?bagian=aturan','/aturan']:
        assert (await klien.get(PREFIX+path)).status_code==200
    assert await rekam()==before
    async with database.SessionLocal() as db:
        t=(await service.ambil_transaksi(db,tid)).trx
        a=await db.get(service.TimbanganAkun,t.dibuat_oleh_id)
        await service.koreksi_transaksi(db,akun=a,trx=t,alasan='Uji koreksi nama historis',
                                       perubahan={'nama_sopir':'Sopir Sintetis Baru'})
    after=await rekam()
    assert after[1:]==before[1:]
    for k in ('aturan_snapshot','berat_barang_kg','total_tara_kg','netto_timbangan_kg','selisih_kg'):
        assert after[0][k]==before[0][k]


@pytest.mark.parametrize('kode,jasa', [
    ('GABAH_BASAH',False),('GABAH_KERING',False),('BERAS_PK',False),
    ('BERAS_MASUK',False),('BROKEN_MASUK',False),
    ('GABAH_BASAH',True),('GABAH_KERING',True),('BERAS_PK',True),('BERAS_MASUK',True)])
async def test_transaksi_baru_memakai_master_meski_sampling_pihak_ada(klien,kode,jasa):
    await login(klien)
    async with database.SessionLocal() as db:
        akun=await db.scalar(select(service.TimbanganAkun).where(service.TimbanganAkun.username=='budi'))
        await histori(db,akun,1,.4321)
        j=await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode==kode))
        # Nilai uji berbeda dari seed/mockup; memverifikasi sumber data resmi.
        j.tara_tetap_kg=.1234;j.tara_bawaan_kg=.2345
        await db.commit()
        aturan=await service.aturan_untuk(db,kode);nilai=aturan.tara_default()
    path=PREFIX+('/jasa/' if jasa else '/timbang/')+kode
    form=(await klien.get(path)).text
    raw=re.search(r'name="tara_per_karung_kg"[^>]*value="([^"]*)"',form)
    assert raw and Decimal(raw.group(1))==Decimal(str(nilai))
    data=dict(kunci=kode_dari(form),berat_kg='13600',jumlah_karung='100',
              tara_per_karung_kg=raw.group(1),nomor_polisi='AD 9911 UJ',nama_sopir='Slamet',
              cara_timbang='DUA_KALI',pelanggan_id='1',supplier_id='1')
    r=await klien.post(path,data=data);assert 'err=' not in str(r.url)
    async with database.SessionLocal() as db:
        t=await db.scalar(select(TimbanganTransaksi));tid=t.id
        m=await db.scalar(select(TimbanganMuatan))
        assert float(m.tara_per_karung_kg)==nilai and m.tara_standar_id is None
        assert t.jasa==jasa
        if jasa:assert t.pelanggan_id==1 and t.supplier_id is None
    r=await klien.post(PREFIX+f'/tiket/{tid}',data=dict(berat_kg='4600',jumlah_karung='100',
         tara_per_karung_kg=raw.group(1),aksi='selesai'))
    assert 'err=' not in str(r.url)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.status_tiket=='SELESAI' and float(t.berat_barang_kg)==pytest.approx(9000-100*nilai)

@pytest.mark.usefixtures('jenis_tersemai','pelanggan_kledo')
async def test_partai_historis_ubah_karung_tidak_membuang_tara(db,petugas,supplier):
    from test_service import partai
    data=partai('UJI-PARTAI-HISTORIS',50)
    data.supplier_id=supplier.id
    data.muatan=[service.InputMuatan(jenis_kode='GABAH_BASAH',jumlah_karung=1,
        tara_per_karung_kg=.0858,catatan='Metadata historis')]
    t=await service.simpan_timbang_pertama(db,akun=petugas,data=data)
    await db.refresh(t,['muatan'])
    sample=await histori(db,petugas,supplier.id)
    sample.jenis_kode='GABAH_BASAH'; t.muatan[0].tara_standar_id=sample.id
    sid=sample.id; snapshot=t.aturan_snapshot
    await db.commit()
    await service.tambah_penimbangan(db,akun=petugas,kode=t.kode,berat=[70],kunci='tambah-partai-uji')
    t=await service.selesaikan_partai(db,akun=petugas,kode=t.kode,jumlah_karung=3)
    await db.refresh(t,['muatan','penimbangan'])
    assert float(t.muatan[0].tara_per_karung_kg)==.0858
    assert t.muatan[0].tara_standar_id==sid and t.muatan[0].catatan=='Metadata historis'
    assert t.aturan_snapshot==snapshot and len(t.penimbangan)==2
    assert float(t.netto_timbangan_kg)==120
    assert float(t.total_tara_kg)==pytest.approx(.257)
    assert float(t.berat_barang_kg)==pytest.approx(119.743)

async def test_http_partai_sementara_dan_selesai_menjaga_tara_historis(klien):
    from test_service import partai
    await login(klien)
    async with database.SessionLocal() as db:
        akun=await db.scalar(select(service.TimbanganAkun).where(service.TimbanganAkun.username=='budi'))
        data=partai('UJI-PARTAI-HTTP',50)
        data.muatan=[service.InputMuatan(jenis_kode='GABAH_BASAH',jumlah_karung=1,
            tara_per_karung_kg=.0858,catatan='Metadata partai HTTP')]
        t=await service.simpan_timbang_pertama(db,akun=akun,data=data)
        await db.refresh(t,['muatan'])
        row=await histori(db,akun,1);row.jenis_kode='GABAH_BASAH'
        t.muatan[0].tara_standar_id=row.id
        tid,sid=t.id,row.id;await db.commit()
    for aksi,berat,karung in [('sementara','70','2'),('selesai','','3')]:
        r=await klien.post(PREFIX+f'/partai/{tid}',data=dict(aksi=aksi,berat_kg=berat,
            jumlah_karung=karung,kunci='uji-partai-'+aksi))
        assert r.status_code==200 and 'err=' not in str(r.url)
        async with database.SessionLocal() as db:
            t=(await service.ambil_transaksi(db,tid)).trx
            assert t.muatan[0].tara_standar_id==sid
            assert float(t.muatan[0].tara_per_karung_kg)==.0858
            assert t.muatan[0].catatan=='Metadata partai HTTP'
            assert t.status_tiket==('TERBUKA' if aksi=='sementara' else 'SELESAI')
            assert len(t.penimbangan)==2

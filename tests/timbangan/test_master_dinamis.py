"""Kontrak master PadiFlow dibaca tanpa menulis aturan/transaksi historis."""
import json
import pytest
from sqlalchemy import text,select,func
from app.timbangan import pengiriman,service,klien_produksi
from app.timbangan.models import TimbanganJenis,TimbanganTransaksi

KODE='hs_1234567890abcde'
async def master(db,aktif=True):
    await db.execute(text('INSERT INTO setelan_pabrik(kunci,nilai) VALUES(:k,:v)'),dict(
        k='jenis_hasil_samping:'+KODE,v=json.dumps(dict(kode=KODE,nama='Dedak baru',aktif=aktif,bentuk='karung',kg_karung=37))))
    await db.flush()

async def test_pengiriman_jenis_master_baru(db,monkeypatch):
    await service.pastikan_jenis(db);await master(db)
    from tests.timbangan.test_pengiriman_gabungan import payload
    async def muatan(_):
        data=payload();data['muatan'][0].update(jenis_kode=KODE.upper(),nama='Dedak baru');return data
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',muatan)
    data=await pengiriman.baca(db,123)
    assert data['muatan'][0]['jenis_kode']==KODE.upper()
    assert await db.scalar(select(func.count()).select_from(TimbanganJenis))==len(service.logic.JENIS_AWAL)
    assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==0

async def test_jenis_tidak_terdaftar_ditolak(db):
    with pytest.raises(service.LayananError,match='tidak dikenal'):
        await service.aturan_untuk(db,KODE.upper())

async def test_master_masuk_keluar_jasa_dan_nonaktif(db):
    await service.pastikan_jenis(db);await master(db)
    assert (await service.aturan_untuk(db,KODE.upper())).nama=='Dedak baru'
    assert KODE.upper()+'_MASUK' in {r.kode for r in await service.daftar_jenis_jasa(db)}
    assert KODE.upper() in {r.kode for r in await service.daftar_jenis(db,arah='KELUAR',hanya_aktif=True)}
    await db.execute(text('UPDATE setelan_pabrik SET nilai=:v'),dict(v=json.dumps(dict(kode=KODE,nama='Dedak diubah',aktif=False,bentuk='karung',kg_karung=37))))
    assert KODE.upper() not in {r.kode for r in await service.daftar_jenis(db,arah='KELUAR',hanya_aktif=True)}
    assert (await service.aturan_untuk(db,KODE.upper())).nama=='Dedak diubah'
    assert KODE.upper()+'_MASUK' not in {r.kode for r in await service.daftar_jenis_jasa(db)}

async def test_ganti_nama_master_lama_tidak_menulis_aturan_tf(db):
    await service.pastikan_jenis(db)
    sebelum=(await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode=='BROKEN'))).nama
    await db.execute(text('INSERT INTO setelan_pabrik(kunci,nilai) VALUES(:k,:v)'),dict(k='jenis_hasil_samping:broken',v=json.dumps(dict(kode='broken',nama='Beras pecah pilihan',aktif=True,bentuk='karung',kg_karung=50))))
    assert (await service.aturan_untuk(db,'BROKEN')).nama=='Beras pecah pilihan'
    assert next(r for r in await service.daftar_jenis(db) if r.kode=='BROKEN').nama=='Beras pecah pilihan'
    assert await db.scalar(select(TimbanganJenis.nama).where(TimbanganJenis.kode=='BROKEN'))==sebelum

async def test_curah_tidak_memerlukan_karung_dan_snapshot_stabil(db,petugas,supplier):
    from uuid import uuid4
    await service.pastikan_jenis(db)
    await db.execute(text('INSERT INTO setelan_pabrik(kunci,nilai) VALUES(:k,:v)'),dict(k='jenis_hasil_samping:'+KODE,v=json.dumps(dict(kode=KODE,nama='Hasil curah',aktif=True,bentuk='curah',kg_karung=None))))
    code=KODE.upper()+'_MASUK'
    data=service.InputTimbang(kunci=str(uuid4()),arah='MASUK',jenis_kode=code,berat_kg=2000,
        supplier_id=supplier.id,nomor_polisi='B 1234 UJ',nama_sopir='Sopir uji',
        muatan=[service.InputMuatan(jenis_kode=code,berat_acuan_kg=998,nomor_acuan='NOTA-CURAH')])
    trx=await service.simpan_timbang_pertama(db,akun=petugas,data=data)
    trx=await service.simpan_timbang_kedua(db,akun=petugas,kode=trx.kode,berat_kg=1002)
    assert trx.status_tiket=='SELESAI' and float(trx.berat_barang_kg)==998 and float(trx.total_tara_kg)==0
    saved=trx.aturan_snapshot
    await db.execute(text('UPDATE setelan_pabrik SET nilai=:v'),dict(v=json.dumps(dict(kode=KODE,nama='Curah nonaktif',aktif=False,bentuk='curah',kg_karung=None))))
    assert service.samping_curah(service.aturan_dari_snapshot(trx))
    assert trx.aturan_snapshot==saved
    assert (await service.simpan_timbang_pertama(db,akun=petugas,data=data)).id==trx.id
    data.kunci=str(uuid4())
    with pytest.raises(service.LayananError,match='nonaktif'):
        await service.simpan_timbang_pertama(db,akun=petugas,data=data)

@pytest.mark.parametrize('kode',['menir','reject','bekatul'])
async def test_jenis_bawaan_juga_memiliki_jalur_masuk_dari_master(db,kode):
    await service.pastikan_jenis(db)
    await db.execute(text('INSERT INTO setelan_pabrik(kunci,nilai) VALUES(:k,:v)'),dict(k='jenis_hasil_samping:'+kode,v=json.dumps(dict(kode=kode,nama='Nama '+kode,aktif=True,bentuk='karung',kg_karung=40))))
    incoming=kode.upper()+'_MASUK'
    aturan=await service.aturan_untuk(db,incoming)
    assert aturan.arah=='MASUK' and aturan.boleh_jasa and aturan.nama=='Nama '+kode
    assert incoming in {r.kode for r in await service.daftar_jenis(db,arah='MASUK')}

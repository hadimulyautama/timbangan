"""Muatan kg resmi PadiFlow tidak meminta karung rekaan di Pos Timbang."""
from copy import deepcopy
import pytest
from test_pengiriman_gabungan import payload,tiket
from test_web import app_uji,klien,login
from test_formulir import tiket_uji
from app.timbangan import service,pengiriman,klien_produksi
from app import database
from app.timbangan.models import TimbanganTransaksi


def curah():
    p=payload()
    for b in p['muatan']:
        b.update(jenis_kode='BEKATUL',nama='Bekatul curah',satuan='kg',jumlah=b['berat_kg'],jumlah_karung=0,tara_per_karung_kg=0)
    return p

async def test_curah_resmi_selesai_dan_replay_tanpa_karung(db,petugas):
    t=await tiket(db,petugas)
    t=await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9000,pengiriman_snapshot=curah())
    assert t.selesai and t.jumlah_karung==0 and float(t.berat_barang_kg)==4000
    await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9000,pengiriman_snapshot=curah())
    assert t.selesai and float(t.total_tara_kg)==0

async def test_pratinjau_dan_post_curah_resmi_sama(klien,monkeypatch):
    tid=await tiket_uji('KELUAR','PENGIRIMAN');await login(klien)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);p=curah();p['nomor_polisi']=t.nomor_polisi
    async def baca(*a,**k):return deepcopy(p)
    async def selesai(*a,**k):return {'selesai':True,'kode_perintah':'OUT-UJI'}
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',baca)
    monkeypatch.setattr(klien_produksi,'selesaikan_pengiriman',selesai)
    preview=await klien.post(f'/timbangan/tiket/{tid}/pratinjau',data={'berat_kg':'9000'})
    assert preview.status_code==200 and preview.json()['tersedia'],preview.text
    r=await klien.post(f'/timbangan/tiket/{tid}',data={'berat_kg':'9000','aksi':'selesai'})
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.selesai and t.jumlah_karung==0 and float(t.total_tara_kg)==0,r.text


def test_muatan_berkarung_tidak_boleh_hilang_karung_dalam_kiriman_campuran():
    p=payload();p['muatan'][0]['jumlah_karung']=0
    with pytest.raises(pengiriman.MuatanTidakSah):pengiriman.cuplikan(p)

async def test_koreksi_cuplikan_berkarung_menjadi_curah_resmi(db,admin):
    t=await tiket(db,admin)
    t=await service.simpan_timbang_kedua(db,akun=admin,kode=t.kode,berat_kg=9018.5,pengiriman_snapshot=payload())
    await service.koreksi_transaksi(db,akun=admin,trx=t,perubahan={},pengiriman_snapshot=curah(),alasan='Muatan aktual diperbaiki di PadiFlow menjadi curah')
    assert t.jumlah_karung==0 and float(t.total_tara_kg)==0
    assert float(t.timbang2_kg)==9018.5 and float(t.berat_acuan_kg)==4000

@pytest.mark.parametrize('cacat',['tanpa-sidik','tanpa-satuan'])
async def test_payload_lama_tidak_memakai_pengecualian_curah(db,petugas,cacat):
    p=curah();t=await tiket(db,petugas)
    if cacat=='tanpa-sidik':p['kiriman_id']=None;p['sidik_sumber']=None
    else:
        for b in p['muatan']:b.pop('satuan')
    with pytest.raises(service.LayananError,match='Jumlah karung'):
        await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9000,pengiriman_snapshot=p)

async def test_jam_bawaan_kedua_tidak_memundurkan_waktu_perangkat(klien,monkeypatch):
    import re
    from datetime import datetime,timedelta
    from app.timbangan.routes import pos
    from app.timbangan.db import sekarang
    tid=await tiket_uji('MASUK','GABAH_BASAH');await login(klien)
    awal=sekarang().replace(second=30,microsecond=123456)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);t.timbang1_waktu=awal;await db.commit()
    monkeypatch.setattr(pos,'sekarang',lambda:awal)
    monkeypatch.setattr(service,'sekarang',lambda:awal+timedelta(seconds=1))
    r=await klien.get(f'/timbangan/tiket/{tid}')
    teks=re.search(r'name="waktu"[^>]*value="([^"]+)"',r.text).group(1)
    cap=datetime.fromisoformat(teks)
    assert cap>=awal.replace(tzinfo=None) and cap-awal.replace(tzinfo=None)<timedelta(milliseconds=1)
    r=await klien.post(f'/timbangan/tiket/{tid}',data={'berat_kg':'5000','jumlah_karung':'200','waktu':teks,'aksi':'selesai'})
    async with database.SessionLocal() as db:assert (await db.get(TimbanganTransaksi,tid)).selesai,r.text

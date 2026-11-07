"""Retur curah resmi tidak memerlukan karung fiktif untuk timbang kedua."""
from sqlalchemy import text,select
import pytest
from app import database
from app.timbangan import service
from app.timbangan.models import TimbanganTransaksi,TimbanganAkun
from test_web import app_uji,klien,login
from test_rincian_supplier import tiket

async def tautan_kg(db,tid,*,satuan='kg',status='diajukan',supplier=None):
    t=await db.get(TimbanganTransaksi,tid)
    await db.execute(text('CREATE TABLE retur_supplier (id INTEGER PRIMARY KEY,timbangan_transaksi_id INTEGER,supplier_id INTEGER,status TEXT)'))
    await db.execute(text('CREATE TABLE retur_supplier_items (id INTEGER PRIMARY KEY,retur_supplier_id INTEGER,satuan TEXT,jumlah NUMERIC,bobot_kg NUMERIC)'))
    await db.execute(text('INSERT INTO retur_supplier VALUES (1,:tid,:sid,:status)'),dict(tid=tid,sid=t.supplier_id if supplier is None else supplier,status=status))
    await db.execute(text('INSERT INTO retur_supplier_items VALUES (1,1,:unit,70,70)'),dict(unit=satuan));await db.commit()

async def test_retur_curah_resmi_bisa_selesai_tanpa_karung_fiktif_layanan(klien):
    tid=await tiket(selesai=False)
    async with database.SessionLocal() as db:
        await tautan_kg(db,tid)
        t=await db.get(TimbanganTransaksi,tid);a=await db.get(TimbanganAkun,1)
        t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=6570)
        assert t.status_tiket=='SELESAI' and t.jumlah_karung==0 and t.berat_barang_kg==70

async def test_form_pratinjau_dan_post_retur_curah_tidak_meminta_karung(klien):
    tid=await tiket(selesai=False)
    async with database.SessionLocal() as db:await tautan_kg(db,tid)
    await login(klien)
    form=await klien.get(f'/timbangan/tiket/{tid}')
    assert 'name="jumlah_karung"' not in form.text
    r=await klien.post(f'/timbangan/tiket/{tid}/pratinjau',data={'berat_kg':'6570'})
    assert r.status_code==200 and r.json()['tersedia'],r.text
    r=await klien.post(f'/timbangan/tiket/{tid}',data={'berat_kg':'6570','aksi':'selesai'})
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.status_tiket=='SELESAI' and t.jumlah_karung==0,r.text[:400]

@pytest.mark.parametrize('kasus',['kemasan','campuran','batal','supplier','kosong','jumlah-nol','bobot-nol'])
async def test_pengecualian_curah_hanya_untuk_sumber_resmi_seluruhnya_kg(klien,kasus):
    from app.timbangan.tautan_produksi import retur_supplier_curah
    tid=await tiket(selesai=False)
    async with database.SessionLocal() as db:
        await tautan_kg(db,tid,satuan='karung' if kasus=='kemasan' else 'kg',status='dibatalkan' if kasus=='batal' else 'diajukan',supplier=999 if kasus=='supplier' else None)
        if kasus=='campuran':await db.execute(text("INSERT INTO retur_supplier_items VALUES (2,1,'karung',1,50)"))
        if kasus=='kosong':await db.execute(text('DELETE FROM retur_supplier_items'))
        if kasus=='jumlah-nol':await db.execute(text('UPDATE retur_supplier_items SET jumlah=0'))
        if kasus=='bobot-nol':await db.execute(text('UPDATE retur_supplier_items SET bobot_kg=0'))
        await db.commit()
        t=await db.get(TimbanganTransaksi,tid)
        assert not await retur_supplier_curah(db,t)
        with pytest.raises(service.LayananError,match='Jumlah karung belum diisi'):
            await service.simpan_timbang_kedua(db,akun=await db.get(TimbanganAkun,1),kode=t.kode,berat_kg=6570)
        assert t.status_tiket=='TERBUKA' and t.timbang2_kg is None

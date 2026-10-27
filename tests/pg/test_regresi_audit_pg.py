"""Lima perbaikan audit pada PostgreSQL sementara (fixture mesin).

Khusus replay, float 0,00015 yang dikirim asyncpg disimpan menjadi 0,0001
oleh NUMERIC(9,4). Mengirim ulang input aslinya tetap harus diterima.
"""
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.models import Supplier
from app.timbangan import service
from app.timbangan.models import TimbanganAkun, TimbanganJenis, TimbanganTransaksi


async def awal(mesin, jenis="GABAH_BASAH"):
    async with mesin() as db:
        a = TimbanganAkun(username="audit", nama="Petugas Audit", role="ADMIN",
                          password_hash="uji", perangkat_kode="UA")
        s = Supplier(nama_supplier="Pemasok Audit", kledo_contact_id=990001)
        db.add_all([a, s])
        await db.flush()
        t = await service.simpan_timbang_pertama(db, akun=a, data=service.InputTimbang(
            kunci=str(uuid4()), arah="KELUAR" if jenis == "PENGIRIMAN" else "MASUK",
            jenis_kode=jenis, berat_kg=5000 if jenis == "PENGIRIMAN" else 15000,
            supplier_id=s.id if jenis != "PENGIRIMAN" else None,
            nomor_polisi="AD 1234 XY", nama_sopir="Sopir Audit"))
        return a.id, t.id, t.kode


def muatan(**ubah):
    return service.InputMuatan(**{
        "jenis_kode": "GABAH_BASAH", "jumlah_karung": 100,
        "tara_per_karung_kg": 0.25, "berat_acuan_kg": 9975, **ubah})


async def test_tara_negatif_tidak_mengubah_bacaan_pg(mesin):
    aid, tid, kode = await awal(mesin)
    async with mesin() as db:
        a = await db.get(TimbanganAkun, aid)
        with pytest.raises(service.LayananError):
            await service.simpan_timbang_kedua(db, akun=a, kode=kode, berat_kg=5000,
                                             muatan=[muatan(tara_per_karung_kg=-1)])
        t = await db.get(TimbanganTransaksi, tid)
        assert t.timbang2_kg is None and t.berat_barang_kg is None


async def test_replay_presisi_pg_diterima_isi_berbeda_ditolak(mesin):
    aid, tid, kode = await awal(mesin)
    async with mesin() as db:
        a = await db.get(TimbanganAkun, aid)
        await service.simpan_timbang_kedua(db, akun=a, kode=kode, berat_kg=5000,
                                         muatan=[muatan(tara_per_karung_kg=0.00015)])
    async with mesin() as db:
        a = await db.get(TimbanganAkun, aid)
        tersimpan = await db.get(TimbanganTransaksi, tid)
        assert float(tersimpan.muatan[0].tara_per_karung_kg) == 0.0001
        t = await service.simpan_timbang_kedua(db, akun=a, kode=kode, berat_kg=5000,
                                             muatan=[muatan(tara_per_karung_kg=0.00015)])
        assert t.id == tid and float(t.muatan[0].tara_per_karung_kg) == 0.0001
        with pytest.raises(service.LayananError, match="Koreksi"):
            await service.simpan_timbang_kedua(db, akun=a, kode=kode, berat_kg=5000,
                muatan=[muatan(tara_per_karung_kg=0.00015, jumlah_karung=200)])


async def test_koreksi_sementara_tetap_tanpa_hasil_pg(mesin):
    aid, tid, kode = await awal(mesin)
    async with mesin() as db:
        a = await db.get(TimbanganAkun, aid)
        t = await service.simpan_timbang_kedua(db, akun=a, kode=kode, berat_kg=5000,
                                             selesaikan=False)
        await service.koreksi_transaksi(db, akun=a, trx=t,
            perubahan={"nama_sopir": "Sopir Audit Baru"}, alasan="Perbaiki ejaan")
    async with mesin() as db:
        t = await db.get(TimbanganTransaksi, tid)
        assert t.status_tiket == "TERBUKA" and t.berat_barang_kg is None
        assert t.status_kontrol is None
        r = await service.ringkasan_dashboard(db, service.FilterTransaksi())
        assert r.masuk_kg == 0


async def test_snapshot_dipakai_saat_penyelesaian_pg(mesin):
    aid, tid, kode = await awal(mesin)
    async with mesin() as db:
        a = await db.get(TimbanganAkun, aid)
        j = await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode == "GABAH_BASAH"))
        j.ambang_nilai = 0
        await db.commit()
        t = await service.simpan_timbang_kedua(db, akun=a, kode=kode, berat_kg=5000,
                                             muatan=[muatan(berat_acuan_kg=9985)])
        assert t.status_kontrol == "NORMAL"
        await service.koreksi_transaksi(db, akun=a, trx=t,
            perubahan={"catatan": "Dokumen diterima"}, alasan="Lengkapi catatan")
        assert t.status_kontrol == "NORMAL"


@pytest.mark.parametrize("status", ["perintah", "dimuat", "selesai"])
async def test_pengiriman_tertaut_menahan_void_pg(mesin, status):
    aid, tid, _ = await awal(mesin, "PENGIRIMAN")
    async with mesin() as db:
        await db.execute(text("CREATE TABLE IF NOT EXISTS outgoing_records (id INTEGER PRIMARY KEY, kode VARCHAR(20), status VARCHAR(20), timbangan_transaksi_id INTEGER)"))
        await db.execute(text("INSERT INTO outgoing_records VALUES (1,'OUT-AUDIT',:s,:t)"), {"s": status, "t": tid})
        await db.commit()
        a = await db.get(TimbanganAkun, aid)
        t = await db.get(TimbanganTransaksi, tid)
        with pytest.raises(service.LayananError, match="OUT-AUDIT"):
            await service.void_transaksi(db, akun=a, trx=t, alasan="Uji pagar")
        assert t.status_transaksi == "AKTIF"

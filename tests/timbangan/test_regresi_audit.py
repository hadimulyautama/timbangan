"""Regresi audit TeraFlow: bobot, replay, snapshot, dan tautan Produksi.

Alur HTTP memakai SQLite sementara. Tabel pengiriman hanya dibuat sebagai
kontrak baca lintas aplikasi; tidak menyentuh database operasional.
"""
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from test_web import app_uji, klien, login  # noqa: F401
from app import database
from app.timbangan import logic, service
from app.timbangan.models import (
    TimbanganAkun, TimbanganAudit, TimbanganJenis, TimbanganKiriman,
    TimbanganTransaksi,
)


def kepala(kunci):
    return {"X-Timbangan-Kiriman": kunci, "X-Timbangan-Akun": "1"}


async def tiket(klien, jenis="GABAH_BASAH"):
    kunci = str(uuid4())
    r = await klien.post(f"/timbangan/timbang/{jenis}", headers=kepala(kunci), data={
        "kunci": kunci, "berat_kg": "5000" if jenis == "PENGIRIMAN" else "15000",
        "supplier_id": "1", "nomor_polisi": "AD 1234 XY", "nama_sopir": "Slamet",
    })
    assert r.status_code == 200 and r.json()["tersimpan"], r.text
    async with database.SessionLocal() as db:
        return await db.scalar(select(TimbanganTransaksi.id).where(
            TimbanganTransaksi.kunci_kiriman == kunci))


async def kedua(klien, tid, **ubah):
    kunci = str(uuid4())
    data = dict(kunci=kunci, berat_kg="5000", jumlah_karung="100",
                tara_per_karung_kg="0.25", berat_acuan_kg="9975", aksi="selesai")
    data.update(ubah)
    return await klien.post(f"/timbangan/tiket/{tid}", data=data, headers=kepala(kunci))


@pytest.mark.parametrize("isian,nilai", [
    ("tara_per_karung_kg", "-1"), ("berat_acuan_kg", "-1"),
    ("tara_per_karung_kg", "1001"), ("berat_acuan_kg", "1000001"),
])
@pytest.mark.parametrize("aksi", ["sementara", "selesai"])
async def test_angka_muatan_ditolak_sebelum_tiket_diubah(klien, isian, nilai, aksi):
    await login(klien)
    tid = await tiket(klien)
    r = await kedua(klien, tid, aksi=aksi, **{isian: nilai})
    assert r.status_code == 422 and not r.json()["tersimpan"], r.text
    async with database.SessionLocal() as db:
        t = await db.get(TimbanganTransaksi, tid)
        assert t.timbang2_kg is None and t.berat_barang_kg is None
        assert t.status_tiket == "TERBUKA"
        assert await db.scalar(select(func.count()).select_from(TimbanganKiriman)) == 1


@pytest.mark.parametrize("isian", ["tara_per_karung_kg", "berat_acuan_kg"])
@pytest.mark.parametrize("nilai", [-1, float("nan"), float("inf")])
def test_rumus_menolak_muatan_tidak_sah_termasuk_pratinjau(isian, nilai):
    m = logic.BarisMuatan(jenis_kode="GABAH_BASAH", jumlah_karung=100)
    setattr(m, isian, nilai)
    with pytest.raises(logic.ValidasiError):
        logic.hitung(aturan=logic.JENIS_PETA["GABAH_BASAH"],
                     berat_bermuatan_kg=15000, berat_kosong_kg=5000, muatan=[m])


async def test_tara_negatif_ditolak_pratinjau_dan_koreksi(klien):
    await login(klien)
    tid = await tiket(klien)
    data = dict(berat_kg="5000", jumlah_karung="100", tara_per_karung_kg="-1")
    r = await klien.post(f"/timbangan/tiket/{tid}/pratinjau", data=data)
    assert r.status_code == 422, r.text
    assert (await kedua(klien, tid)).json()["tersimpan"]
    data = {"tara_per_karung_kg": "-1", "alasan": "Salah tanda"}
    r = await klien.post(f"/timbangan/transaksi/{tid}/koreksi/pratinjau", data=data)
    assert r.status_code == 422, r.text
    await klien.post(f"/timbangan/transaksi/{tid}/koreksi", data=data)
    async with database.SessionLocal() as db:
        t = await db.get(TimbanganTransaksi, tid)
        assert t.total_tara_kg == 25 and t.berat_barang_kg == 9975
        assert t.jumlah_revisi == 0


@pytest.mark.parametrize("ubah", [
    {"jumlah_karung": "200"}, {"tara_per_karung_kg": "0.5"},
    {"berat_acuan_kg": "9900"}, {"nomor_acuan": "NOTA-BARU"},
    {"catatan": "Catatan berbeda"}, {"waktu": "2026-10-25T07:00"},
])
async def test_kiriman_baru_yang_berbeda_tidak_boleh_diakui_tersimpan(klien, ubah):
    await login(klien)
    tid = await tiket(klien)
    assert (await kedua(klien, tid)).json()["tersimpan"]
    async with database.SessionLocal() as db:
        audit = await db.scalar(select(func.count()).select_from(TimbanganAudit))
    r = await kedua(klien, tid, **ubah)
    assert r.status_code == 422 and not r.json()["tersimpan"], r.text
    assert "Koreksi" in r.json()["pesan"]
    async with database.SessionLocal() as db:
        t = await db.get(TimbanganTransaksi, tid)
        assert t.jumlah_karung == 100 and t.total_tara_kg == 25
        assert t.catatan is None
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit)) == audit


async def test_replay_sama_tetap_idempoten_dengan_kunci_baru(klien):
    await login(klien)
    tid = await tiket(klien)
    assert (await kedua(klien, tid)).json()["tersimpan"]
    async with database.SessionLocal() as db:
        audit = await db.scalar(select(func.count()).select_from(TimbanganAudit))
    assert (await kedua(klien, tid)).json()["tersimpan"]
    async with database.SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit)) == audit


@pytest.mark.parametrize("jenis", ["GABAH_BASAH", "GABAH_KERING"])
async def test_snapshot_konsisten_sejak_timbang_pertama_sampai_koreksi(klien, jenis):
    await login(klien)
    tid = await tiket(klien, jenis)
    async with database.SessionLocal() as db:
        j = await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode == jenis))
        j.ambang_nilai = 0
        await db.commit()
    data = dict(berat_kg="5000", jumlah_karung="100", tara_per_karung_kg="0.25",
                berat_acuan_kg="9978")
    preview = await klien.post(f"/timbangan/tiket/{tid}/pratinjau", data=data)
    assert preview.json()["tersedia"], preview.text
    assert (await kedua(klien, tid, berat_acuan_kg="9978")).json()["tersimpan"]
    async with database.SessionLocal() as db:
        t = await db.get(TimbanganTransaksi, tid)
        assert t.status_kontrol == logic.NORMAL
        assert t.batas_bawah_kg < 0
        before = (t.berat_barang_kg, t.selisih_kg, t.batas_bawah_kg)
    await klien.post(f"/timbangan/transaksi/{tid}/koreksi",
                    data={"alasan": "Lengkapi catatan", "catatan": "Dokumen diterima"})
    async with database.SessionLocal() as db:
        t = await db.get(TimbanganTransaksi, tid)
        assert t.status_kontrol == logic.NORMAL
        assert before == (t.berat_barang_kg, t.selisih_kg, t.batas_bawah_kg)


async def test_koreksi_tiket_sementara_tidak_menghitung_hasil_atau_ringkasan(klien):
    await login(klien)
    tid = await tiket(klien)
    assert (await kedua(klien, tid, aksi="sementara", jumlah_karung="0")).json()["tersimpan"]
    data = {"alasan": "Betulkan nama", "nama_sopir": "Slamet Riyadi"}
    r = await klien.post(f"/timbangan/transaksi/{tid}/koreksi/pratinjau", data=data)
    assert r.json()["terbuka"] and r.json()["nilai"]["Berat barang setelah koreksi"] == "Belum tersedia"
    await klien.post(f"/timbangan/transaksi/{tid}/koreksi", data=data)
    async with database.SessionLocal() as db:
        t = await db.get(TimbanganTransaksi, tid)
        assert t.nama_sopir == "Slamet Riyadi" and t.timbang2_kg == 5000
        assert t.status_tiket == "TERBUKA" and t.status_kontrol is None
        assert t.berat_barang_kg is None and t.netto_timbangan_kg is None
        ringkasan = await service.ringkasan_dashboard(db, service.FilterTransaksi())
        assert ringkasan.masuk_kg == 0 and ringkasan.perlu_periksa == 0
    assert (await kedua(klien, tid)).json()["tersimpan"]
    async with database.SessionLocal() as db:
        t = await db.get(TimbanganTransaksi, tid)
        assert t.berat_barang_kg == 9975 and t.status_tiket == "SELESAI"


@pytest.mark.parametrize("status", ["perintah", "dimuat", "selesai"])
@pytest.mark.parametrize("aksi", ["batal", "hapus", "jenis"])
async def test_tautan_pengiriman_aktif_melindungi_tiket(klien, status, aksi):
    await login(klien)
    tid = await tiket(klien, "PENGIRIMAN")
    async with database.SessionLocal() as db:
        await db.execute(text("CREATE TABLE outgoing_records (id INTEGER PRIMARY KEY, kode VARCHAR(20), status VARCHAR(20), timbangan_transaksi_id INTEGER)"))
        await db.execute(text("INSERT INTO outgoing_records VALUES (1,'OUT-UJI-001',:status,:tid)"), {"status": status, "tid": tid})
        await db.commit()
        t = await db.get(TimbanganTransaksi, tid)
        akun = await db.get(TimbanganAkun, 3)
        akun.role = "SUPERADMIN"
        with pytest.raises(service.LayananError, match="OUT-UJI-001"):
            if aksi == "batal":
                await service.void_transaksi(db, akun=akun, trx=t, alasan="Uji pagar")
            elif aksi == "hapus":
                await service.hapus_transaksi(db, akun=akun, trx=t, alasan="Uji pagar")
            else:
                await service.ubah_jenis(db, akun=akun, trx=t, jenis_kode="BEBAS", alasan="Uji pagar")
        assert t.status_transaksi == "AKTIF" and t.jenis_kode == "PENGIRIMAN"


async def test_pengiriman_batal_tidak_mengunci_tiket(klien):
    await login(klien)
    tid = await tiket(klien, "PENGIRIMAN")
    async with database.SessionLocal() as db:
        await db.execute(text("CREATE TABLE outgoing_records (id INTEGER PRIMARY KEY, kode VARCHAR(20), status VARCHAR(20), timbangan_transaksi_id INTEGER)"))
        await db.execute(text("INSERT INTO outgoing_records VALUES (1,'OUT-UJI-001','batal',:tid)"), {"tid": tid})
        await db.commit()
        t = await db.get(TimbanganTransaksi, tid)
        akun = await db.get(TimbanganAkun, 3)
        await service.void_transaksi(db, akun=akun, trx=t, alasan="Perintah sudah batal")
        assert t.status_transaksi == "VOID"

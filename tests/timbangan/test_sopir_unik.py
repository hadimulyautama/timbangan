"""Nama sopir baru boleh, variasi huruf dan spasi memakai satu entri."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.timbangan.models import TimbanganSopir, TimbanganSopirAlias, TimbanganTransaksi
from app.timbangan.sopir import nama_utama, nama_pengganti, NamaSopirTidakSah
from app.timbangan import service
from test_pemasok_kledo import masukan


async def test_variasi_nama_hanya_satu_entri(db):
    for nama in ("Didik Pamungkas", " didik   PAMUNGKAS ", "Ｄｉｄｉｋ Pamungkas"):
        assert await nama_utama(db, nama) == "Didik Pamungkas"
        await db.commit()
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganSopir)) == 1


async def pasang_alias_didik(db):
    await nama_utama(db, "Didik Pamungkas")
    utama = await db.scalar(sa.select(TimbanganSopir))
    db.add(TimbanganSopirAlias(kunci_nama="didik", nama="DIDIK", sopir_id=utama.id))
    await db.commit()


async def test_alias_terkonfirmasi_memakai_satu_sopir_tanpa_menggabung_nama_lain(db):
    await pasang_alias_didik(db)
    for nama in ("DIDIK", " Didik ", "ｄｉｄｉｋ", "Didik Pamungkas"):
        assert await nama_utama(db, nama) == "Didik Pamungkas"
    assert await nama_utama(db, "Ari") == "Ari"
    assert await nama_utama(db, "Pak arif") == "Pak arif"
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganSopir)) == 3
    assert await db.scalar(sa.select(TimbanganSopir).where(TimbanganSopir.kunci_nama == "didik")) is None


@pytest.mark.usefixtures("jenis_tersemai")
async def test_alias_tiket_baru_dan_kiriman_lama_tetap_satu_riwayat(db, admin, supplier):
    await pasang_alias_didik(db)
    data = masukan(supplier.id)
    data.nama_sopir = "DIDIK"
    t = await service.simpan_timbang_pertama(db, akun=admin, data=data)
    assert t.nama_sopir == "Didik Pamungkas"
    data.nama_sopir = "Didik"  # kiriman sebelum penggabungan
    replay = await service.simpan_timbang_pertama(db, akun=admin, data=data)
    assert replay.id == t.id and replay.nama_sopir == "Didik Pamungkas"
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganTransaksi)) == 1
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganSopir)) == 1


def test_migrasi_alias_tidak_mengubah_nama_master_dan_tiket():
    path = Path(__file__).parents[2] / "migrations/versions/0046_sopir_alias.py"
    spec = importlib.util.spec_from_file_location("migrasi_alias", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    mesin = sa.create_engine("sqlite://")
    with mesin.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE timbangan_sopir (id INTEGER PRIMARY KEY, nama TEXT)")
        conn.exec_driver_sql("INSERT INTO timbangan_sopir VALUES (1,'DIDIK'),(3,'Didik Pamungkas')")
        conn.exec_driver_sql("CREATE TABLE timbangan_transaksi (id INTEGER PRIMARY KEY, nama_sopir TEXT)")
        conn.exec_driver_sql("INSERT INTO timbangan_transaksi VALUES (1,'DIDIK')")
        with Operations.context(MigrationContext.configure(conn)):
            m.upgrade()
        assert conn.execute(sa.text("SELECT * FROM timbangan_transaksi")).all() == [(1, "DIDIK")]
        assert conn.execute(sa.text("SELECT * FROM timbangan_sopir ORDER BY id")).all() == [(1, "DIDIK"),(3,"Didik Pamungkas")]
        assert conn.execute(sa.text("SELECT * FROM timbangan_sopir_alias")).all() == []
    mesin.dispose()


@pytest.mark.usefixtures("jenis_tersemai")
async def test_sopir_sama_boleh_banyak_perjalanan_tanpa_master_ganda(db, petugas, supplier):
    hasil = []
    for nama in ("Slamet", "  sLaMet "):
        data = masukan(supplier.id)
        data.nama_sopir = nama
        hasil.append(await service.simpan_timbang_pertama(db, akun=petugas, data=data))
    assert hasil[0].id != hasil[1].id
    assert [t.nama_sopir for t in hasil] == ["Slamet", "Slamet"]
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganSopir)) == 1
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganTransaksi)) == 2


def test_migrasi_merangkum_nama_tanpa_menulis_ulang_riwayat():
    path = Path(__file__).parents[2] / "migrations/versions/0045_sopir_unik.py"
    spec = importlib.util.spec_from_file_location("migrasi_sopir_unik", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    mesin = sa.create_engine("sqlite://")
    with mesin.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE timbangan_transaksi (id INTEGER PRIMARY KEY, nama_sopir TEXT)")
        conn.execute(sa.text("INSERT INTO timbangan_transaksi VALUES (1,'Didik'),(2,' DIDIK  '),(3,'Slamet')"))
        sebelum = conn.execute(sa.text("SELECT * FROM timbangan_transaksi ORDER BY id")).all()
        with Operations.context(MigrationContext.configure(conn)):
            m.upgrade()
        assert conn.execute(sa.text("SELECT * FROM timbangan_transaksi ORDER BY id")).all() == sebelum
        assert conn.execute(sa.text("SELECT nama,kunci_nama FROM timbangan_sopir ORDER BY id")).all() == [("Didik", "didik"), ("Slamet", "slamet")]
    mesin.dispose()


@pytest.mark.parametrize("nama", [
    "LAIN-LAIN", "LAIN LAIN", " lain - lain ", "LAIN–LAIN", "LAIN2",
    "LAIN-LAIN 2", "-", "—", "---", "???", "123", "tidak diketahui",
    "tanpa nama", "N/A", "unknown", "Pak Lain-Lain",
])
async def test_penanda_tanpa_identitas_tidak_didaftarkan(db, nama):
    assert nama_pengganti(nama)
    with pytest.raises(NamaSopirTidakSah, match="Isi nama sopir sebenarnya"):
        await nama_utama(db, nama)
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganSopir)) == 0


@pytest.mark.parametrize("nama", ["Didik", "Didik Pamungkas", "Ari", "Pak arif", "Lainah"])
def test_nama_ambigu_dan_nama_asli_tidak_ditebak(nama):
    assert not nama_pengganti(nama)


@pytest.mark.usefixtures("jenis_tersemai")
@pytest.mark.parametrize("cara", ["DUA_KALI", "PARTAI"])
async def test_server_menolak_tiket_baru_dengan_nama_pengganti(db, petugas, supplier, cara):
    data = masukan(supplier.id, cara=cara)
    data.nama_sopir = "LAIN LAIN"
    with pytest.raises(service.LayananError, match="Isi nama sopir sebenarnya"):
        await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganTransaksi)) == 0


@pytest.mark.usefixtures("jenis_tersemai")
async def test_koreksi_tidak_bisa_mengganti_ke_nama_pengganti(db, admin, supplier):
    t = await service.simpan_timbang_pertama(db, akun=admin, data=masukan(supplier.id))
    with pytest.raises(service.LayananError, match="Isi nama sopir sebenarnya"):
        await service.koreksi_transaksi(db, akun=admin, trx=t, perubahan={"nama_sopir": "-"})
    assert t.nama_sopir == "Sopir Uji"


@pytest.mark.usefixtures("jenis_tersemai")
async def test_riwayat_penanda_lama_tetap_bisa_dikerjakan_tanpa_muncul_di_saran(db, admin, supplier):
    data = masukan(supplier.id)
    t = await service.simpan_timbang_pertama(db, akun=admin, data=data)
    t.nama_sopir = "LAIN-LAIN"  # bentuk catatan historis, bukan masukan baru
    await db.commit()
    data.nama_sopir = "LAIN-LAIN"
    ulang = await service.simpan_timbang_pertama(db, akun=admin, data=data)
    assert ulang.id == t.id and ulang.nama_sopir == "LAIN-LAIN"
    saran = await service.kendaraan_dikenal(db)
    assert len(saran) == 1 and saran[0].sopir_terakhir is None
    hasil = await service.simpan_timbang_kedua(db, akun=admin, kode=t.kode, berat_kg=5000)
    assert hasil.nama_sopir == "LAIN-LAIN" and float(hasil.berat_barang_kg) == 10000
    hasil = await service.koreksi_transaksi(
        db, akun=admin, trx=hasil, perubahan={"nama_sopir": "LAIN-LAIN", "catatan": "Catatan diperbaiki"})
    assert hasil.nama_sopir == "LAIN-LAIN" and hasil.catatan == "Catatan diperbaiki"
    assert await db.scalar(sa.select(sa.func.count()).select_from(TimbanganSopir).where(
        TimbanganSopir.kunci_nama == "lain-lain")) == 0

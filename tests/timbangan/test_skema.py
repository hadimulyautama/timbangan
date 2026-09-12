"""Uji skema modul Timbangan.

Dua hal dijaga di sini:

  1. Migrasi 0022 dan model SQLAlchemy tetap sepadan — kolom demi kolom.
     Tanpa uji ini, menambah kolom di model tanpa menambahnya di migrasi baru
     ketahuan saat deploy ke Railway.
  2. Tidak ada kolom harga atau nilai uang di tabel `timbangan_*`. Aturan
     "operator pos timbang tidak boleh tahu harga" ditegakkan oleh ketiadaan
     kolom; uji ini yang menahannya agar tidak diam-diam ditambahkan kembali.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import app.models  # noqa: F401  (daftarkan suppliers)
from app.database import Base
from app.timbangan import models as M  # noqa: F401

AKAR = pathlib.Path(__file__).resolve().parents[2]
MIGRASI = (
    AKAR / "migrations" / "versions" / "0022_timbangan.py",
    AKAR / "migrations" / "versions" / "0023_timbangan_config.py",
    AKAR / "migrations" / "versions" / "0024_timbangan_aturan_cetak.py",
    AKAR / "migrations" / "versions" / "0025_timbangan_cetak_format.py",
    AKAR / "migrations" / "versions" / "0027_pelanggan_transaksi.py",
    AKAR / "migrations" / "versions" / "0028_timbangan_partai.py",
    # 0029 hanya melebarkan kolom `arah`, jadi tak mengubah daftar kolom —
    # ia sengaja tak ada di sini.
    AKAR / "migrations" / "versions" / "0030_timbangan_nomor_atomik.py",
    AKAR / "migrations" / "versions" / "0032_partai_kunci_baris.py",
    AKAR / "migrations" / "versions" / "0033_cetak_revisi.py",
    AKAR / "migrations" / "versions" / "0034_sesi_versi.py",
    AKAR / "migrations" / "versions" / "0035_indeks_tiket.py",
)

# Daftar di atas DITULIS TANGAN, dan karena itu ia basi tiap kali ada migrasi
# baru yang menambah kolom. Penjaga di bawah menyebutkannya lebih dulu, supaya
# yang gagal berbunyi "migrasi 0031 belum didaftarkan" alih-alih "KeyError:
# 'timbangan_anu'" — kegagalan yang terbacanya seperti model rusak.
#: Migrasi yang TIDAK mengubah daftar kolom, jadi tak perlu ikut diterapkan
#: di sini. Disebut satu per satu berikut alasannya — bukan dilewati diam-diam,
#: karena "tidak mengubah kolom" adalah klaim yang bisa keliru.
TANPA_KOLOM_BARU = {
    "0029_timbangan_retur.py": "hanya melebarkan String(10) → String(16)",
    "0031_semai_penghitung_nomor.py": "hanya mengisi data, tak menambah kolom",
}


def _migrasi_belum_terdaftar() -> list[str]:
    ada = {p.name for p in MIGRASI} | set(TANPA_KOLOM_BARU)
    semua = sorted(
        p.name for p in (AKAR / "migrations" / "versions").glob("00*_timbangan*.py")
    )
    return [n for n in semua if n not in ada and n > "0028"]

# Kata yang tidak boleh muncul sebagai nama kolom di modul ini.
KATA_UANG = (
    "harga", "price", "rupiah", "nilai_rp", "biaya", "total_bayar",
    "potongan", "refaksi", "amount", "tarif",
)


def tabel_model() -> list[str]:
    return sorted(t for t in Base.metadata.tables if t.startswith("timbangan_"))


@pytest.fixture(scope="module")
def kolom_migrasi() -> dict[str, set[str]]:
    """Jalankan seluruh migrasi modul di SQLite sementara, di atas induk tiruan."""
    modul = []
    for berkas in MIGRASI:
        spec = importlib.util.spec_from_file_location(berkas.stem, berkas)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        modul.append(m)

    mesin = sa.create_engine("sqlite://")
    with mesin.begin() as conn:
        for induk in ("users", "suppliers", "purchase_batches", "pk_purchase_batches"):
            conn.exec_driver_sql(f"CREATE TABLE {induk} (id INTEGER PRIMARY KEY)")

        with Operations.context(MigrationContext.configure(conn)):
            for m in modul:
                m.upgrade()

        pemeriksa = sa.inspect(conn)
        return {
            nama: {k["name"] for k in pemeriksa.get_columns(nama)}
            for nama in pemeriksa.get_table_names()
            if nama.startswith("timbangan_")
        }


def test_migrasi_membuat_semua_tabel_model(kolom_migrasi):
    belum = _migrasi_belum_terdaftar()
    assert not belum, (
        f"migrasi belum didaftarkan di MIGRASI: {', '.join(belum)} — "
        "tambahkan, kalau tidak uji ini menjaga skema yang sudah usang")
    assert sorted(kolom_migrasi) == tabel_model()
    # 15 sejak `timbangan_nomor` (penghitung nomor atomik, migrasi 0030).
    assert len(kolom_migrasi) == 15


@pytest.mark.parametrize("nama", tabel_model())
def test_kolom_migrasi_sama_dengan_model(nama, kolom_migrasi):
    assert kolom_migrasi[nama] == set(Base.metadata.tables[nama].columns.keys())


@pytest.mark.parametrize("nama", tabel_model())
def test_tidak_ada_kolom_uang(nama):
    """Kerahasiaan harga diwujudkan lewat rancangan, bukan penyembunyian."""
    melanggar = [
        kolom for kolom in Base.metadata.tables[nama].columns.keys()
        if any(kata in kolom.lower() for kata in KATA_UANG)
    ]
    assert not melanggar, f"{nama} memuat kolom bernuansa uang: {melanggar}"


def test_transaksi_menyimpan_kedua_petugas():
    """Timbang pertama & kedua bisa dilakukan orang berbeda — keduanya tercatat."""
    kolom = Base.metadata.tables["timbangan_transaksi"].columns.keys()
    assert "timbang1_petugas_id" in kolom
    assert "timbang2_petugas_id" in kolom
    assert "timbang1_waktu" in kolom and "timbang1_waktu_sistem" in kolom
    assert "timbang2_waktu" in kolom and "timbang2_waktu_sistem" in kolom


def test_jembatan_integrasi_disiapkan_kosong():
    kolom = Base.metadata.tables["timbangan_transaksi"].columns
    assert kolom["purchase_batch_id"].nullable
    assert kolom["pk_purchase_batch_id"].nullable


def test_migrasi_revisi_aturan_benar_benar_mengubah_baris(kolom_migrasi):
    """Penyemaian tidak pernah menimpa, jadi revisi aturan HARUS lewat migrasi.

    Tanpa uji ini, mengubah `logic.py` saja akan terasa berhasil di laptop
    (tabel masih kosong, jadi disemai dari kode) tetapi diam-diam tidak
    berpengaruh di produksi yang barisnya sudah ada.
    """
    import importlib.util

    berkas = AKAR / "migrations" / "versions" / "0024_timbangan_aturan_cetak.py"
    spec = importlib.util.spec_from_file_location(berkas.stem, berkas)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)

    mesin = sa.create_engine("sqlite://")
    with mesin.begin() as conn:
        conn.exec_driver_sql(
            "create table timbangan_jenis "
            "(kode text, arah text, rahasia boolean, cetak_bukti boolean)"
        )
        # Keadaan SEBELUM revisi, seperti yang tersemai di produksi.
        conn.exec_driver_sql(
            "insert into timbangan_jenis values "
            "('GABAH_BASAH','MASUK',1,0), ('BEKATUL','KELUAR',0,1), "
            "('BERAS_PK','MASUK',0,1)"
        )
        with Operations.context(MigrationContext.configure(conn)):
            modul.upgrade()

        hasil = dict(
            (k, (bool(r), bool(c)))
            for k, r, c in conn.exec_driver_sql(
                "select kode, rahasia, cetak_bukti from timbangan_jenis"
            ).all()
        )

    assert hasil["GABAH_BASAH"] == (True, True)    # bukti tetap dicetak
    assert hasil["BEKATUL"] == (True, True)        # selisih tidak lagi tercetak
    assert hasil["BERAS_PK"] == (False, True)      # PK tidak tersentuh

"""Angka mustahil dan isian kepanjangan ditolak — bukan jadi galat 500.

Temuan QA T-08 & T-09, 11 September 2026.

**T-08.** `_angka` di rute, `setelan._baca`, dan `logic.hitung` menerima "nan".
NaN membuat SETIAP perbandingan bernilai salah, jadi kekurangan 10 ton lolos
sebagai NORMAL — batas atas dan batas bawah sama-sama tak terlampaui, karena
perbandingan dengan NaN selalu False. Laporannya lalu berisi NaN dan
`/monitoring` menjawab 500.

**T-09.** Salah ketik yang wajar jadi galat 500, dan timbang KEDUA hilang saat
truk menunggu di jembatan:

· nota "8" (maksudnya 8 ton) → selisih 124.587%, melampaui NUMERIC(9,4);
· nomor acuan 51 karakter, plat 24 huruf, jumlah karung 3 miliar;
· `supplier_id` yang tak ada.

Suite ini berjalan di SQLite, dan SQLite tak menegakkan panjang VARCHAR
maupun NUMERIC — jadi tak satu pun tertangkap di sini sampai ia tertangkap di
Postgres, yaitu di pos timbang, dengan truk menunggu.
"""
from __future__ import annotations

import math

import pytest

from app.timbangan import logic, service
from app.timbangan.routes import pos as rute

GB = "GABAH_BASAH"


def _muatan(**kw):
    d = dict(jenis_kode=GB, tara_per_karung_kg=0.25)
    d.update(kw)
    return service.InputMuatan(**d)


# ─────────────────────────── T-08 ───────────────────────────

@pytest.mark.parametrize("teks", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_angka_menolak_tak_hingga(teks):
    """`_angka` mengembalikan bawaannya untuk teks yang bukan angka — tetapi
    "nan" LOLOS `float()`, jadi ia menembus tanpa satu pun keluhan."""
    hasil = rute._angka(teks, bawaan=0.0)
    assert math.isfinite(hasil), f"{teks!r} → {hasil!r}"


def test_hitung_menolak_berat_tak_hingga():
    """NaN membuat setiap perbandingan False, jadi kekurangan 10 ton lolos
    sebagai NORMAL — batas atas maupun bawah sama-sama tak terlampaui."""
    # Aturan diambil dari daftar awal aplikasinya sendiri — menyusunnya
    # dengan tangan berarti menguji aturan yang tak pernah dipakai siapa pun.
    aturan = next(a for a in logic.JENIS_AWAL if a.kode == GB)
    with pytest.raises((ValueError, logic.ValidasiError)):
        logic.hitung(aturan=aturan, berat_bermuatan_kg=float("nan"),
                     berat_kosong_kg=5000.0)


# ─────────────────────────── T-09 ───────────────────────────

@pytest.mark.asyncio
async def test_nomor_acuan_kepanjangan_ditolak_dengan_kalimat(db, jenis_tersemai, petugas):
    """51 karakter melampaui kolomnya. Di Postgres itu galat 500, dan timbang
    keduanya hilang — truk sudah di jembatan."""
    with pytest.raises(service.LayananError):
        await service.simpan_timbang_pertama(db, akun=petugas, data=service.InputTimbang(
            kunci="k1", arah="MASUK", jenis_kode=GB, berat_kg=15000,
            pihak_nama="Anton", nomor_polisi="AD 1 A", nama_sopir="Joko",
            muatan=[_muatan(nomor_acuan="N" * 51)]))


@pytest.mark.asyncio
async def test_plat_kepanjangan_ditolak(db, jenis_tersemai, petugas):
    with pytest.raises(service.LayananError):
        await service.simpan_timbang_pertama(db, akun=petugas, data=service.InputTimbang(
            kunci="k2", arah="MASUK", jenis_kode=GB, berat_kg=15000,
            pihak_nama="Anton", nomor_polisi="A" * 24, nama_sopir="Joko",
            muatan=[_muatan()]))


@pytest.mark.asyncio
async def test_jumlah_karung_di_luar_akal_ditolak(db, jenis_tersemai, petugas):
    """Tiga miliar karung. Angkanya sendiri tak melanggar apa pun sampai ia
    dikalikan tara dan hasilnya melampaui kolom NUMERIC."""
    with pytest.raises(service.LayananError):
        await service.simpan_timbang_pertama(db, akun=petugas, data=service.InputTimbang(
            kunci="k3", arah="MASUK", jenis_kode=GB, berat_kg=15000,
            pihak_nama="Anton", nomor_polisi="AD 1 A", nama_sopir="Joko",
            muatan=[_muatan(jumlah_karung=3_000_000_000)]))


@pytest.mark.asyncio
async def test_selisih_persen_ekstrem_tak_melampaui_kolomnya(db, jenis_tersemai, petugas):
    """Nota "8" untuk muatan 10 ton → selisih 124.587%. Kolomnya
    NUMERIC(9,4), jadi angka itu menolak disimpan dan seluruh penimbangan
    gagal — padahal yang salah cuma satu angka yang bisa dikoreksi."""
    await service.simpan_timbang_pertama(db, akun=petugas, data=service.InputTimbang(
        kunci="k4", arah="MASUK", jenis_kode=GB, berat_kg=15000,
        pihak_nama="Anton", nomor_polisi="AD 1 A", nama_sopir="Joko",
        muatan=[_muatan()]))
    from sqlalchemy import select
    from app.timbangan.models import TimbanganTransaksi
    kode = (await db.execute(select(TimbanganTransaksi.kode))).scalars().first()

    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=kode, berat_kg=5000,
        muatan=[_muatan(jumlah_karung=100, berat_acuan_kg=8)])
    # Tersimpan — dan selisihnya dijepit supaya muat di kolomnya.
    assert abs(float(trx.selisih_persen or 0)) < 100_000


# ─────────────────────────── T-04 ───────────────────────────

@pytest.mark.asyncio
async def test_tiket_dikunci_saat_diubah(db, jenis_tersemai, petugas):
    """Tak ada satu pun `FOR UPDATE` di layanan yang MENGUBAH tiket.

    Terbukti di QA: satu baris berisi timbang-1 15.500, bruto 15.000, netto
    10.000 sekaligus — tiga angka yang tak mungkin ada bersamaan, hasil dua
    petugas yang menulis dari salinan yang berbeda-beda umurnya.
    """
    import inspect

    from app.timbangan import service as svc

    # Pengambilan untuk MENGUBAH punya jalurnya sendiri, terkunci.
    assert hasattr(svc, "ambil_kode_terkunci")
    assert "with_for_update()" in inspect.getsource(svc.ambil_kode_terkunci)
    # Dan penulis-penulisnya memakai jalur itu, bukan `ambil_kode` biasa.
    assert "ambil_kode_terkunci(" in inspect.getsource(svc.simpan_timbang_kedua)
    # Koreksi menerima tiketnya langsung, jadi ia mengunci baris yang
    # dipegangnya lalu membacanya ULANG — bukan menghitung dari salinan basi.
    assert "with_for_update=True" in inspect.getsource(svc.koreksi_transaksi)


@pytest.mark.asyncio
async def test_formulir_basi_ditolak_dengan_menyebut_siapa(db, jenis_tersemai,
                                                           petugas, petugas2):
    """Formulir yang dibuka sebelum orang lain mengubah tiketnya akan menimpa
    perubahan itu saat disimpan — diam-diam, dan yang kehilangan tak pernah
    tahu.

    Versinya dibawa di borang; yang tak cocok ditolak sambil menyebut SIAPA
    dan PUKUL BERAPA, supaya petugasnya bisa bertanya alih-alih menebak.
    """
    from sqlalchemy import select

    from app.timbangan.models import TimbanganTransaksi

    await service.simpan_timbang_pertama(db, akun=petugas, data=service.InputTimbang(
        kunci="v1", arah="MASUK", jenis_kode=GB, berat_kg=15000,
        pihak_nama="Anton", nomor_polisi="AD 1 A", nama_sopir="Joko",
        muatan=[_muatan()]))
    kode = (await db.execute(select(TimbanganTransaksi.kode))).scalars().first()
    trx = await service.ambil_kode(db, kode)
    versi_lama = service.versi_tiket(trx)

    # Sari mengoreksi lebih dulu.
    await service.koreksi_transaksi(db, akun=petugas2, trx=trx,
                                    perubahan={"nama_sopir": "Slamet"},
                                    alasan="salah tulis")

    # Budi menyimpan dari formulir yang dibuka SEBELUM koreksi itu.
    with pytest.raises(service.LayananError) as e:
        service.pastikan_versi(trx, versi_lama)
    assert "sudah diubah" in str(e.value).lower()

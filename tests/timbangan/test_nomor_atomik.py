"""Nomor tiket atomik, dan kiriman ulang yang tak pernah menimpa milik orang.

Temuan QA T-01 (Kritis) & T-03, 11 September 2026.

**T-01.** Nomor dibentuk saat formulir DIBUKA, dari `jumlah baris hari ini + 1`,
dengan perangkat `P0` bagi akun yang tak punya kode perangkat — dan admin
bawaan maupun akun lama memang tak punya. Dua petugas yang membuka formulir
pada detik yang sama menerima nomor yang SAMA. Penyimpanannya lalu memakai
nomor itu sebagai identitas, dan menganggap nomor terbuka yang sudah ada
sebagai "kirim ulang" lalu menulis ulang seluruh tiket. Keduanya melihat
"tersimpan"; hanya truk yang kedua tersisa.

Ia juga jadi jalan menimpa tiket orang lain dengan sengaja: siapa pun yang
mengirim POST dengan nomor yang ada akan menulis ulang isinya, melewati
`boleh_mengubah`.

**T-03.** Timbang kedua pada tiket yang sudah SELESAI langsung mengembalikan
tiketnya, dan layar berkata "Timbangan selesai dan tersimpan" — padahal
angka yang baru diketik dibuang tanpa jejak audit.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.timbangan import service
from app.timbangan.models import ROLE_PETUGAS, TimbanganAkun, TimbanganTransaksi

GB = "GABAH_BASAH"


def _muatan(**kw):
    d = dict(jenis_kode=GB, tara_per_karung_kg=0.25)
    d.update(kw)
    return service.InputMuatan(**d)


async def _timbang1(db, akun, **kw):
    d = dict(arah="MASUK", jenis_kode=GB, berat_kg=15000, supplier_id=None,
             pihak_nama="Anton", nomor_polisi="AD 1 A", nama_sopir="Joko",
             muatan=[_muatan()])
    d.update(kw)
    return await service.simpan_timbang_pertama(
        db, akun=akun, data=service.InputTimbang(**d))


async def _akun_tanpa_perangkat(db, nama: str) -> TimbanganAkun:
    """Akun TANPA kode perangkat — persis keadaan admin bawaan & akun lama."""
    a = TimbanganAkun(username=nama, nama=nama.title(), role=ROLE_PETUGAS,
                      password_hash="x")
    db.add(a)
    await db.flush()
    return a


# ───────────────────────────── T-01 ─────────────────────────────

@pytest.mark.asyncio
async def test_dua_petugas_tanpa_kode_perangkat_tidak_saling_menimpa(db, jenis_tersemai):
    """Andi & Budi menimbang truk yang berbeda pada detik yang sama.

    Keduanya harus punya tiket sendiri. Sebelumnya keduanya menerima
    `MSK-…-P0-001`, dan truk Andi hilang tanpa satu pun pesan.
    """
    a = await _akun_tanpa_perangkat(db, "andi")
    b = await _akun_tanpa_perangkat(db, "budi")

    await _timbang1(db, a, nomor_polisi="AD 1111 AA", kunci="kunci-andi")
    await _timbang1(db, b, nomor_polisi="AD 2222 BB", kunci="kunci-budi")

    semua = (await db.execute(select(TimbanganTransaksi))).scalars().all()
    nopol = sorted(t.nomor_polisi for t in semua)
    assert len(semua) == 2, f"satu truk tertimpa — tersisa {nopol}"
    assert nopol == ["AD 1111 AA", "AD 2222 BB"], nopol
    assert len({t.kode for t in semua}) == 2, "dua tiket bernomor sama"


@pytest.mark.asyncio
async def test_nomor_dialokasikan_saat_simpan_bukan_saat_formulir_dibuka(db, jenis_tersemai):
    """Nomor yang diterbitkan saat formulir dibuka adalah nomor yang belum
    jadi milik siapa pun: dua formulir yang terbuka bersamaan memegang angka
    yang sama, dan yang menyimpan belakangan menimpa yang duluan.

    Alokasinya kini di dalam penyimpanan, jadi dua formulir yang membuka
    bersamaan pun berujung pada dua nomor.
    """
    a = await _akun_tanpa_perangkat(db, "andi")
    b = await _akun_tanpa_perangkat(db, "budi")

    # Kedua formulir dibuka LEBIH DULU — keduanya melihat perkiraan yang sama.
    perkiraan_a = await service.kode_baru(db, a, "MASUK")
    perkiraan_b = await service.kode_baru(db, b, "MASUK")
    assert perkiraan_a == perkiraan_b, "prasyarat uji: perkiraannya memang sama"

    t1 = await _timbang1(db, a, nomor_polisi="AD 1111 AA", kunci="k-a")
    t2 = await _timbang1(db, b, nomor_polisi="AD 2222 BB", kunci="k-b")
    assert t1.kode != t2.kode, f"nomor sama: {t1.kode}"


@pytest.mark.asyncio
async def test_kirim_ulang_kunci_sama_isi_sama_tak_menggandakan(db, jenis_tersemai):
    """Antrean luring mengirim ulang kiriman yang sama saat sinyal kembali.
    Itu harus berakhir sebagai satu tiket, bukan dua."""
    a = await _akun_tanpa_perangkat(db, "andi")
    satu = await _timbang1(db, a, kunci="k-sama")
    dua = await _timbang1(db, a, kunci="k-sama")

    assert satu.kode == dua.kode
    semua = (await db.execute(select(TimbanganTransaksi))).scalars().all()
    assert len(semua) == 1


@pytest.mark.asyncio
async def test_kunci_sama_isi_berbeda_ditolak(db, jenis_tersemai):
    """Kunci yang sama dengan isi yang lain bukan kirim ulang — ia dua
    penimbangan yang tertukar kuncinya. Menimpa diam-diam membuang salah
    satunya."""
    a = await _akun_tanpa_perangkat(db, "andi")
    await _timbang1(db, a, berat_kg=15000, kunci="k-satu")
    with pytest.raises(service.LayananError):
        await _timbang1(db, a, berat_kg=9000, kunci="k-satu")


@pytest.mark.asyncio
async def test_nomor_milik_orang_lain_tak_bisa_ditimpa(db, jenis_tersemai):
    """Mengirim POST dengan nomor tiket yang sudah ada dulu menulis ulang
    seluruh isinya, melewati `boleh_mengubah`."""
    a = await _akun_tanpa_perangkat(db, "andi")
    b = await _akun_tanpa_perangkat(db, "budi")
    milik_a = await _timbang1(db, a, nomor_polisi="AD 1111 AA", kunci="k-a")

    with pytest.raises(service.LayananError):
        await _timbang1(db, b, nomor_polisi="AD 2222 BB",
                        kode=milik_a.kode, kunci="k-b")

    await db.refresh(milik_a)
    assert milik_a.nomor_polisi == "AD 1111 AA", "tiket orang lain tertimpa"


# ───────────────────────────── T-03 ─────────────────────────────

@pytest.mark.asyncio
async def test_timbang2_pada_tiket_selesai_dengan_isi_berbeda_ditolak(
        db, jenis_tersemai, petugas, petugas2):
    """Isian Budi dibuang tanpa audit, dan layarnya berkata "tersimpan"."""
    await _timbang1(db, petugas, kunci="k1")
    kode = (await db.execute(select(TimbanganTransaksi.kode))).scalars().first()
    await service.simpan_timbang_kedua(
        db, akun=petugas, kode=kode, berat_kg=5000,
        muatan=[_muatan(jumlah_karung=100, berat_acuan_kg=9975)])

    with pytest.raises(service.LayananError) as e:
        await service.simpan_timbang_kedua(
            db, akun=petugas2, kode=kode, berat_kg=4000,
            muatan=[_muatan(jumlah_karung=120, berat_acuan_kg=11000)])
    # Pesannya menyebut SIAPA dan KAPAN, berikut angka yang tersimpan —
    # tanpa itu petugas kedua tak tahu apakah angkanya sudah benar.
    pesan = str(e.value)
    assert petugas.nama in pesan, pesan
    assert "5.000" in pesan or "5000" in pesan, pesan


@pytest.mark.asyncio
async def test_timbang2_kirim_ulang_isi_sama_tetap_sukses(db, jenis_tersemai, petugas):
    """Kirim ulang dari antrean luring tak boleh berubah jadi galat."""
    await _timbang1(db, petugas, kunci="k1")
    kode = (await db.execute(select(TimbanganTransaksi.kode))).scalars().first()
    muatan = [_muatan(jumlah_karung=100, berat_acuan_kg=9975)]
    satu = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=kode, berat_kg=5000, muatan=muatan)
    dua = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=kode, berat_kg=5000, muatan=muatan)
    assert dua.id == satu.id
    assert float(dua.timbang2_kg) == 5000.0


@pytest.mark.asyncio
async def test_timbang1_pada_tiket_selesai_dengan_isi_berbeda_ditolak(
        db, jenis_tersemai, petugas):
    """Aturan yang sama berlaku untuk timbang pertama."""
    trx = await _timbang1(db, petugas, berat_kg=12000, cara_timbang="SEKALI",
                          nomor_polisi=None, nama_sopir="Darto",
                          jenis_kode="BEBAS", arah="BEBAS", muatan=[],
                          kunci="k-sekali")
    assert trx.selesai, "prasyarat: tiket SEKALI langsung selesai"

    with pytest.raises(service.LayananError):
        await _timbang1(db, petugas, berat_kg=8000, cara_timbang="SEKALI",
                        nomor_polisi=None, nama_sopir="Darto",
                        jenis_kode="BEBAS", arah="BEBAS", muatan=[],
                        kunci="k-sekali")


# ──────────────────── Kode perangkat: wajib & unik ────────────────────

def test_kode_perangkat_wajib_dan_unik_untuk_akun_baru():
    """Kode perangkat masuk ke nomor tiket dan tercetak di struk.

    Akun tanpa kode memakai "P0" — dan SEMUA akun tanpa kode memakai P0 yang
    sama, sehingga dua petugas menerima nomor yang sama. Admin bawaan justru
    salah satu yang tak punya kode.
    """
    import inspect

    from app.timbangan.routes import master

    sumber = inspect.getsource(master.simpan_pengguna)
    assert "Kode perangkat wajib diisi" in sumber
    assert "sudah dipakai" in sumber
    # Diperiksa SEBELUM akunnya dibuat, bukan sesudah.
    assert sumber.index("Kode perangkat wajib") < sumber.index("db.add(baru)")


def test_akun_lama_tanpa_kode_tidak_diisi_otomatis():
    """Kodenya sudah tercetak di struk yang beredar. Menetapkannya diam-diam
    membuat struk lama menunjuk perangkat yang bukan penerbitnya — jadi
    pemiliknya yang memutuskan, bukan migrasi."""
    import pathlib

    import ast

    berkas = (pathlib.Path(__file__).resolve().parents[2]
              / "migrations/versions/0030_timbangan_nomor_atomik.py")
    teks = berkas.read_text()

    # Penjelasannya MEMANG menyebut "ON CONFLICT DO UPDATE" — itu cara
    # penghitung nomor bekerja. Yang diperiksa di sini kodenya saja; uji yang
    # menolak penyebutan kata akan menghukum penjelasan yang baik.
    pohon = ast.parse(teks)
    for simpul in ast.walk(pohon):
        if isinstance(simpul, ast.Constant) and isinstance(simpul.value, str):
            naik = simpul.value.upper()
            assert "UPDATE TIMBANGAN" not in naik, "migrasi mengisi data lama"
    assert "op.execute" not in teks, "migrasi menjalankan SQL bebas"
    # Dan alasannya memang tertulis, supaya yang berikutnya tak mengisinya.
    assert "tercetak di struk" in teks or "kunci karangan" in teks

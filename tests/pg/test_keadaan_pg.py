"""Penanda keadaan pos timbang — di Postgres, lewat HTTP, dua sesi.

Temuan QA P4-06 mengukur `/miniapp/keadaan` dan mendapat 404; kanal timbangan
sebenarnya ada sejak 11 Sep 2026 di `/timbangan/keadaan` (alamatnya ikut
awalan aplikasi, dan `app.js` memang bertanya ke sana). Yang belum ada:
ruas `versi` (syarat N-A-03) dan sumber perubahan selain tiket. Uji ini
menjaga perilakunya, bukan teks sumbernya: sesi B menyimpan, penanda sesi A
naik.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio

PREFIX = "/timbangan"


async def _akun(mesin, username: str, role: str) -> int:
    from app.timbangan.models import TimbanganAkun
    from hmu_identitas import sandi as S

    async with mesin() as db:
        t = TimbanganAkun(username=username, nama=username.title(), role=role,
                          password_hash=S.hash_sandi("rahasia123"), perangkat_kode=f"P{len(username)}")
        db.add(t)
        await db.commit()
        return t.id


def _masuk(klien, akun_id: int):
    """Satu perangkat = satu toples kuki. Klien fixture dipakai bersama, jadi
    tiap sesi membawa kukinya sendiri lewat header permintaan."""
    from app.timbangan import security

    return {"Cookie": f"{security.NAMA_COOKIE}={security.buat_token(akun_id)}"}


async def _penanda(klien, kepala) -> dict:
    r = await klien.get(f"{PREFIX}/keadaan", headers=kepala)
    assert r.status_code == 200, r.text
    return r.json()


async def _tiket_baru(mesin, akun_id: int) -> str:
    """Sesi B: petugas lain menyimpan timbang pertama lewat layanan."""
    from app.timbangan import logic, service
    from app.timbangan.models import TimbanganAkun

    async with mesin() as db:
        akun = await db.get(TimbanganAkun, akun_id)
        jenis = next(j for j in await service.daftar_jenis(db) if j.arah == logic.MASUK)
        trx = await service.simpan_timbang_pertama(db, akun=akun, data=service.InputTimbang(
            kunci=str(uuid4()), arah=jenis.arah, jenis_kode=jenis.kode, berat_kg=12_000,
            pihak_nama="Pak Uji", nomor_polisi="B 1 UJ", nama_sopir="Sopir Uji",
        ))
        return trx.kode


async def test_penanda_membawa_versi_aplikasi(mesin, klien):
    """N-A-03: ponsel tahu ia memegang versi lama dari kanal yang sama."""
    from app.timbangan.web import VERSI

    kepala = _masuk(klien, await _akun(mesin, "budi", "PETUGAS"))
    j = await _penanda(klien, kepala)
    assert j["versi"] == VERSI and "n" in j


async def test_sesi_b_menyimpan_penanda_sesi_a_naik(mesin, klien):
    """Tiket baru DAN timbang kedua (yang cuma mengubah baris) sama-sama
    menggerakkan penanda; tanpa ada yang berubah, penandanya diam."""
    from sqlalchemy import select

    from app.timbangan import service
    from app.timbangan.models import TimbanganAkun, TimbanganTransaksi

    a = _masuk(klien, await _akun(mesin, "budi", "PETUGAS"))
    sari = await _akun(mesin, "sari", "PETUGAS")

    n0 = (await _penanda(klien, a))["n"]
    assert (await _penanda(klien, a))["n"] == n0

    kode = await _tiket_baru(mesin, sari)
    n1 = (await _penanda(klien, a))["n"]
    assert n1 != n0

    async with mesin() as db:
        trx = (await db.execute(select(TimbanganTransaksi).where(TimbanganTransaksi.kode == kode))).scalar_one()
        jenis = trx.jenis_kode
        await service.simpan_timbang_kedua(
            db, akun=await db.get(TimbanganAkun, sari), kode=kode, berat_kg=4_000,
            muatan=[service.InputMuatan(jenis_kode=jenis, jumlah_karung=160, tara_per_karung_kg=0.5)])
    n2 = (await _penanda(klien, a))["n"]
    assert n2 != n1


async def test_pemeriksaan_admin_ikut_menggerakkan_penanda(mesin, klien):
    """Laporan menampilkan status pemeriksaan; admin yang membuka atau
    menutupnya di perangkat lain harus terlihat di layar yang sedang terbuka —
    padahal baris tiketnya sendiri tak tersentuh."""
    from sqlalchemy import select, text

    from app.timbangan.models import TimbanganTransaksi

    a = _masuk(klien, await _akun(mesin, "budi", "PETUGAS"))
    sari = await _akun(mesin, "sari", "PETUGAS")
    kode = await _tiket_baru(mesin, sari)
    n0 = (await _penanda(klien, a))["n"]

    async with mesin() as db:
        tid = (await db.execute(select(TimbanganTransaksi.id)
                                .where(TimbanganTransaksi.kode == kode))).scalar_one()
        await db.execute(text("insert into timbangan_pemeriksaan (transaksi_id, status) "
                              "values (:t, 'DIBUKA')"), {"t": tid})
        await db.commit()
    assert (await _penanda(klien, a))["n"] != n0

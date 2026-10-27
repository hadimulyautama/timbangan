"""R-T-01 — simpan partai di Pos Timbang, di Postgres sungguhan.

Insiden 15 September 2026: Elfira beberapa kali mendapat "internal server
error" saat menyimpan timbangan partai. Tiga baris yang bertabrakan:

    routes/pos.py    kunci=str(uuid4())          → 36 karakter
    service.py       kunci_baris=f"{kunci}#{i}"  → 38 karakter
    models.py        String(36)

Postgres menolak (StringDataRightTruncationError). Galat itu DBAPIError, dan
rute hanya menangkap (LayananError, ValidasiError) — jadi ia jadi layar
hitam, dan timbangannya TIDAK tersimpan.

Kenapa suite tak pernah menangkapnya: uji timbangan berjalan di SQLite, dan
SQLite TIDAK menegakkan batas panjang VARCHAR. Uji di sini WAJIB Postgres
(`UJI_PG_URL`), dan dibuktikan GAGAL pada kode 884f389 sebelum diperbaiki.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

PREFIX = "/timbangan"


async def _petugas(mesin):
    from app.timbangan.models import TimbanganAkun
    from hmu_identitas import sandi as S

    async with mesin() as db:
        a = TimbanganAkun(username="elfira", nama="Elfira", role="PETUGAS",
                          password_hash=S.hash_sandi("rahasia123"), perangkat_kode="P1")
        db.add(a)
        await db.commit()
        await db.refresh(a)
        return a


async def _tiket_partai(mesin, akun) -> tuple[int, str]:
    """Tiket partai terbuka, lewat layanan yang sama dengan borangnya."""
    from app.timbangan import logic, service
    from app.timbangan.models import CARA_PARTAI
    from app.timbangan.service import InputTimbang

    async with mesin() as db:
        from app.models import Supplier
        pihak = Supplier(nama_supplier="Pemasok Sintetis Partai", kledo_contact_id=990001)
        db.add(pihak)
        await db.flush()
        trx = await service.simpan_timbang_pertama(
            db, akun=akun,
            data=InputTimbang(kode="TRX-RT01-001", arah=logic.MASUK, jenis_kode="GABAH_BASAH",
                              berat_kg=12.5, cara_timbang=CARA_PARTAI,
                              supplier_id=pihak.id, perangkat_kode="P1"),
        )
        return trx.id, trx.kode


async def test_tambah_karung_dengan_kunci_borang_tersimpan(mesin):
    """Persis yang ditekan Elfira: borang membawa kunci uuid4 (36), layanan
    menyusun `kunci#0` (38). Harus tersimpan, bukan ditolak basis data."""
    from app.timbangan import service

    akun = await _petugas(mesin)
    _, kode = await _tiket_partai(mesin, akun)
    kunci = str(uuid4())
    async with mesin() as db:
        trx = await service.tambah_penimbangan(
            db, akun=akun, kode=kode, berat=[70.0, 65.5], kunci=kunci, ip="127.0.0.1")
        assert float(trx.timbang1_kg) == 12.5 + 70.0 + 65.5
    async with mesin() as db:
        baris = (await db.execute(text(
            "SELECT kunci_baris FROM timbangan_penimbangan ORDER BY urutan"))).scalars().all()
    assert baris[1:] == [f"{kunci}#0", f"{kunci}#1"]
    assert all(len(k) == 38 for k in baris[1:])


async def test_kiriman_ulang_dengan_kunci_yang_sama_tak_menambah_lagi(mesin):
    """Alasan kuncinya TIDAK boleh dipotong jadi 36: kunci terpotong berhenti
    unik antar baris satu kiriman, dan T-10 (karung yang sama dua kali) hidup
    lagi. Dengan kolom 64, kiriman ulang tetap terdeteksi dari awalannya."""
    from app.timbangan import service

    akun = await _petugas(mesin)
    _, kode = await _tiket_partai(mesin, akun)
    kunci = str(uuid4())
    for _ in range(2):
        async with mesin() as db:
            trx = await service.tambah_penimbangan(
                db, akun=akun, kode=kode, berat=[70.0], kunci=kunci, ip="127.0.0.1")
    assert float(trx.timbang1_kg) == 12.5 + 70.0, "kiriman kedua tak boleh menambah"


async def test_galat_basis_data_tak_jadi_layar_hitam(mesin, klien):
    """Kunci yang bahkan tak muat di 64 pun tak boleh berakhir sebagai 500.
    Petugas harus membaca bahwa timbangannya TIDAK tersimpan, di borang yang
    sama — bukan menebak dari halaman hitam."""
    from app.timbangan import security

    akun = await _petugas(mesin)
    tid, _ = await _tiket_partai(mesin, akun)
    kepala = {"Cookie": f"{security.NAMA_COOKIE}={security.buat_token(akun.id)}"}
    r = await klien.post(f"{PREFIX}/partai/{tid}", headers=kepala,
                         data={"berat_kg": ["70"], "aksi": "sementara", "kunci": "x" * 70})
    assert r.status_code == 303, r.text
    assert r.headers["location"].startswith(f"{PREFIX}/partai/{tid}")
    assert "err=" in r.headers["location"]
    async with mesin() as db:
        n = (await db.execute(text("SELECT count(*) FROM timbangan_penimbangan"))).scalar_one()
    assert n == 1, "yang gagal tak boleh tersimpan separuh"
    # Kalimat yang dibaca petugas menyebut nasib timbangannya.
    r2 = await klien.get(r.headers["location"], headers=kepala)
    assert "TIDAK tersimpan" in r2.text


async def test_migrasi_0038_aman_dari_36_maupun_dari_64(mesin):
    """Pemilik mungkin sudah menjalankan ALTER TABLE penambal di produksi.
    Migrasinya harus aman di kedua keadaan: kolom masih 36, atau sudah 64."""
    import importlib.util
    import pathlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    berkas = (pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
              / "0038_kunci_baris_64.py")
    spec = importlib.util.spec_from_file_location(berkas.stem, berkas)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    engine = mesin.kw["bind"]
    akun = await _petugas(mesin)
    tid, _ = await _tiket_partai(mesin, akun)

    def _lebar(conn):
        return conn.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'timbangan_penimbangan' AND column_name = 'kunci_baris'"
        )).scalar_one()

    def _upgrade(conn):
        with Operations.context(MigrationContext.configure(conn)):
            m.upgrade()

    async with engine.begin() as conn:
        # Keadaan 1: kolom masih 36 (skema produksi sebelum ditambal).
        await conn.execute(text(
            "ALTER TABLE timbangan_penimbangan ALTER COLUMN kunci_baris TYPE varchar(36)"))
        assert await conn.run_sync(_lebar) == 36
        await conn.run_sync(_upgrade)
        assert await conn.run_sync(_lebar) == 64
        # Keadaan 2: sudah 64 (penambal manual sudah jalan) — tetap aman.
        await conn.run_sync(_upgrade)
        assert await conn.run_sync(_lebar) == 64
        # Nilai 38 karakter yang sudah ada tak menghalangi migrasi ulang.
        await conn.execute(text(
            "INSERT INTO timbangan_penimbangan (transaksi_id, urutan, berat_kg, kunci_baris) "
            "VALUES (:t, 2, 70, :k)"), {"t": tid, "k": str(uuid4()) + "#0"})
        await conn.run_sync(_upgrade)
        assert await conn.run_sync(_lebar) == 64

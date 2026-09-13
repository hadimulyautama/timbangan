"""Pos timbang memakai identitas bersama (`hmu_identitas`, Tahap 2).

Yang dijaga: akun bersama (tabel `produksi_akun`) bisa masuk ke pos timbang
dan profil `timbangan_akun`-nya tersinkron; akun lama yang BELUM ditautkan
tetap masuk dengan sandinya sendiri (tak ada hari tanpa sistem yang jalan);
petugas yang sedang bertugas tak terputus saat akunnya ditautkan; satu
saklar nonaktif dan satu versi sesi dari paket memutus sesi di sini juga
(QA X-11, T-19); pengelolaan pengguna untuk profil tertaut tinggal kode
perangkat — peran, sandi, status, nama milik identitas bersama.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app import database
from app.database import Base
from app.timbangan import security as sec, service
from app.timbangan.models import ROLE_ADMIN, ROLE_PETUGAS, ROLE_SUPERADMIN, TimbanganAkun
from app.timbangan.web import PREFIX, pasang
from hmu_core import User, Warehouse
from hmu_identitas import masuk, peran as P, sandi as S
from hmu_identitas.model import Akun

SANDI_BERSAMA = "bersama123"
SANDI_LAMA = "lama123456"


@pytest_asyncio.fixture
async def mesin(monkeypatch):
    m = create_async_engine("sqlite+aiosqlite://")
    async with m.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Sesi = async_sessionmaker(m, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", Sesi)
    monkeypatch.setattr(sec, "_KUNCI_SEMENTARA", b"k" * 32, raising=False)
    async with Sesi() as db:
        await service.pastikan_jenis(db)
        db.add(Warehouse(nama_gudang="Gudang 2 — Penyosohan"))
        await db.commit()
    yield Sesi
    await m.dispose()


@pytest_asyncio.fixture
async def klien(mesin):
    aplikasi = FastAPI()
    pasang(aplikasi)
    async with AsyncClient(transport=ASGITransport(app=aplikasi), base_url="http://uji") as c:
        yield c


async def akun_bersama(Sesi, *, nama="Purwadi", role=P.OPERATOR, username="purwadi",
                       gudang=True, profil: dict | None = None) -> tuple[int, int, int | None]:
    """(akun_id, user_id, timbangan_akun_id) — profil dibuat bila `profil` diberi."""
    async with Sesi() as db:
        wid = (await db.execute(select(Warehouse.id))).scalars().first() if gudang else None
        u = User(nama=nama, role=role, status="aktif", default_warehouse_id=wid)
        db.add(u)
        await db.flush()
        a = Akun(user_id=u.id, username=username, password_hash=S.hash_sandi(SANDI_BERSAMA),
                 status="aktif", mode_perangkat="bersama")
        db.add(a)
        await db.flush()
        tid = None
        if profil is not None:
            t = TimbanganAkun(username=username, nama=profil.get("nama", "Nama Lama"),
                              role=profil.get("role", ROLE_ADMIN), akun_id=a.id,
                              password_hash=profil.get("password_hash"),
                              perangkat_kode=profil.get("perangkat_kode", "P3"))
            db.add(t)
            await db.flush()
            tid = t.id
        await db.commit()
        return a.id, u.id, tid


async def akun_lama(Sesi, *, username="sari", role=ROLE_PETUGAS, kode="P2") -> int:
    async with Sesi() as db:
        t = TimbanganAkun(username=username, nama=username.title(), role=role,
                          password_hash=S.hash_sandi(SANDI_LAMA), perangkat_kode=kode)
        db.add(t)
        await db.commit()
        return t.id


async def masuk_http(c, username, sandi):
    return await c.post(f"{PREFIX}/masuk", data={"username": username, "sandi": sandi, "tujuan": ""})


def token_lama(tid: int, versi: int = 1) -> str:
    """Token bentuk LAMA: sub = timbangan_akun.id, tanpa tanda akun bersama."""
    return sec.buat_token(tid, versi=versi)


# ── Masuk ────────────────────────────────────────────────────────────────

async def test_akun_bersama_masuk_dan_profilnya_tersinkron(mesin, klien):
    aid, uid, tid = await akun_bersama(mesin, profil={"nama": "Pur", "role": ROLE_ADMIN})
    r = await masuk_http(klien, "Purwadi", SANDI_BERSAMA)
    assert r.status_code == 303 and r.headers["location"] == f"{PREFIX}/"
    assert (await klien.get(f"{PREFIX}/")).status_code == 200
    async with mesin() as db:
        t = await db.get(TimbanganAkun, tid)
        assert t.nama == "Purwadi" and t.role == ROLE_PETUGAS and t.perangkat_kode == "P3"


async def test_akun_lama_belum_tertaut_masih_masuk_dengan_sandinya(mesin, klien):
    await akun_lama(mesin)
    r = await masuk_http(klien, "sari", SANDI_LAMA)
    assert r.status_code == 303
    assert (await klien.get(f"{PREFIX}/")).status_code == 200


async def test_profil_tertaut_tak_lagi_menerima_sandi_lama_timbangan(mesin, klien):
    await akun_bersama(mesin, profil={"password_hash": S.hash_sandi(SANDI_LAMA)})
    r = await masuk_http(klien, "purwadi", SANDI_LAMA)
    assert r.status_code == 200 and "Nama pengguna atau kata sandi salah" in r.text
    assert (await masuk_http(klien, "purwadi", SANDI_BERSAMA)).status_code == 303


async def test_akun_bersama_tanpa_profil_dibuatkan_saat_masuk(mesin, klien):
    aid, uid, _ = await akun_bersama(mesin, nama="Elfira", role=P.ADMIN, username="elfira", gudang=False)
    assert (await masuk_http(klien, "elfira", SANDI_BERSAMA)).status_code == 303
    async with mesin() as db:
        t = (await db.execute(select(TimbanganAkun).where(TimbanganAkun.akun_id == aid))).scalars().one()
        assert t.nama == "Elfira" and t.role == ROLE_ADMIN and t.perangkat_kode is None
        assert t.password_hash is None
    assert (await klien.get(f"{PREFIX}/laporan")).status_code == 200  # admin


async def test_nonaktif_di_master_ditolak_saat_masuk(mesin, klien):
    aid, uid, _ = await akun_bersama(mesin, profil={})
    async with mesin() as db:
        await masuk.nonaktifkan(db, uid)
    r = await masuk_http(klien, "purwadi", SANDI_BERSAMA)
    assert r.status_code == 200 and "dinonaktifkan" in r.text


# ── Sesi ─────────────────────────────────────────────────────────────────

async def test_petugas_bertugas_tak_terputus_saat_akunnya_ditautkan(mesin, klien):
    """Token LAMA (sub = timbangan_akun.id) untuk profil yang baru ditautkan
    tetap diterima sampai kedaluwarsa atau ia masuk lagi."""
    aid, uid, tid = await akun_bersama(mesin, profil={"password_hash": S.hash_sandi(SANDI_LAMA)})
    klien.cookies.set(sec.NAMA_COOKIE, token_lama(tid), path=PREFIX)
    assert (await klien.get(f"{PREFIX}/")).status_code == 200


async def test_satu_saklar_nonaktif_memutus_token_baru_dan_lama(mesin, klien):
    aid, uid, tid = await akun_bersama(mesin, profil={})
    await masuk_http(klien, "purwadi", SANDI_BERSAMA)
    assert (await klien.get(f"{PREFIX}/")).status_code == 200
    async with mesin() as db:
        await masuk.nonaktifkan(db, uid)
    r = await klien.get(f"{PREFIX}/")
    assert r.status_code == 303 and "/masuk" in r.headers["location"]
    klien.cookies.clear()
    klien.cookies.set(sec.NAMA_COOKIE, token_lama(tid), path=PREFIX)
    r = await klien.get(f"{PREFIX}/")
    assert r.status_code == 303 and "/masuk" in r.headers["location"]


async def test_versi_bersama_naik_memutus_sesi_di_sini(mesin, klien):
    """Keluar-semua / ganti sandi / reset di Pos Produksi memutus pos timbang."""
    aid, uid, tid = await akun_bersama(mesin, profil={})
    await masuk_http(klien, "purwadi", SANDI_BERSAMA)
    assert (await klien.get(f"{PREFIX}/")).status_code == 200
    async with mesin() as db:
        await masuk.naikkan_versi(db, aid)
    r = await klien.get(f"{PREFIX}/")
    assert r.status_code == 303 and "/masuk" in r.headers["location"]


async def test_keluar_di_pos_timbang_menaikkan_versi_bersama(mesin, klien):
    aid, uid, tid = await akun_bersama(mesin, profil={})
    await masuk_http(klien, "purwadi", SANDI_BERSAMA)
    r = await klien.post(f"{PREFIX}/keluar")
    assert r.status_code == 303
    async with mesin() as db:
        assert (await db.get(Akun, aid)).token_version == 2


# ── Pengelolaan ──────────────────────────────────────────────────────────

async def test_profil_tertaut_hanya_kode_perangkat_yang_boleh_diubah_di_sini(mesin):
    aid, uid, tid = await akun_bersama(mesin, profil={"perangkat_kode": "P3"})
    bos = await akun_lama(mesin, username="bos", role=ROLE_SUPERADMIN, kode="P9")
    async with mesin() as db:
        admin = await db.get(TimbanganAkun, bos)
        orang = await db.get(TimbanganAkun, tid)
        for ubahan in ({"role": ROLE_SUPERADMIN}, {"sandi_baru": "x" * 8}, {"nama": "Lain"},
                       {"username": "lain"}):
            with pytest.raises(service.LayananError):
                await service.ubah_akun(db, admin=admin, orang=orang, **ubahan)
        with pytest.raises(service.LayananError):
            await service.ubah_status_akun(db, admin=admin, orang=orang)
        assert await service.ubah_akun(db, admin=admin, orang=orang, perangkat_kode="P4") == ["kode perangkat"]
        assert orang.perangkat_kode == "P4"


async def test_akun_saya_tertaut_ganti_sandi_lewat_identitas_bersama(mesin, klien):
    aid, uid, tid = await akun_bersama(mesin, profil={})
    await masuk_http(klien, "purwadi", SANDI_BERSAMA)
    r = await klien.post(f"{PREFIX}/akun", data={"nama": "", "username": "",
                                                 "sandi_lama": SANDI_BERSAMA, "sandi_baru": "barubaru1"})
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    # Sesi ini diperbarui (cookie baru), dan sandi baru berlaku di mana pun.
    assert (await klien.get(f"{PREFIX}/")).status_code == 200
    async with mesin() as db:
        assert S.cek_sandi("barubaru1", (await db.get(Akun, aid)).password_hash)


async def test_tambah_profil_untuk_akun_bersama_lewat_layar_pengguna(mesin, klien):
    aid, uid, _ = await akun_bersama(mesin, nama="Dany", username="dany")
    bos = await akun_lama(mesin, username="bos", role=ROLE_SUPERADMIN, kode="P9")
    await masuk_http(klien, "bos", SANDI_LAMA)
    r = await klien.post(f"{PREFIX}/pengguna", data={"username": "dany", "perangkat_kode": "P5"})
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    async with mesin() as db:
        t = (await db.execute(select(TimbanganAkun).where(TimbanganAkun.akun_id == aid))).scalars().one()
        assert t.nama == "Dany" and t.role == ROLE_PETUGAS and t.perangkat_kode == "P5"
    r = await klien.post(f"{PREFIX}/pengguna", data={"username": "tidakada", "perangkat_kode": "P6"})
    assert "Pos Produksi" in r.headers["location"] or "Meja" in r.headers["location"]


async def test_super_admin_bersama_menutup_jaring_pengaman(mesin):
    """Jaring "belum ada Super Admin → Admin diterima" menghitung akun
    bersama juga — kalau tidak, Admin lama tetap bisa mengangkat dirinya."""
    async with mesin() as db:
        assert not await sec.ada_super_aktif(db)
    await akun_bersama(mesin, nama="Wahid", role=P.SUPERADMIN, username="wahid", gudang=False,
                       profil={"role": ROLE_SUPERADMIN})
    async with mesin() as db:
        assert await sec.ada_super_aktif(db)

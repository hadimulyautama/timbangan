"""Penautan akun pos timbang ke akun bersama: rencana, terapkan, lepas."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.timbangan import identitas_tautan as it
from app.timbangan.models import ROLE_ADMIN, ROLE_PETUGAS, ROLE_SUPERADMIN, TimbanganAkun
from hmu_core import User
from hmu_identitas import peran as P, sandi as S
from hmu_identitas.model import Akun


@pytest_asyncio.fixture
async def Sesi():
    m = create_async_engine("sqlite+aiosqlite://")
    async with m.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(m, expire_on_commit=False)
    await m.dispose()


async def _isi(Sesi):
    """Empat keadaan yang mungkin ada di pabrik."""
    async with Sesi() as db:
        # (a) user_id sudah menunjuk orang yang punya akun bersama
        u1 = User(nama="Wahid", role=P.SUPERADMIN, status="aktif"); db.add(u1); await db.flush()
        a1 = Akun(user_id=u1.id, username="wahid", password_hash=S.hash_sandi("produksi1")); db.add(a1)
        db.add(TimbanganAkun(username="wahid", nama="Wahid N", role=ROLE_ADMIN, user_id=u1.id,
                             password_hash=S.hash_sandi("timbang1"), perangkat_kode="P0"))
        # (b) nama pengguna sama, user_id kosong
        u2 = User(nama="Elfira", role=P.ADMIN, status="aktif"); db.add(u2); await db.flush()
        db.add(Akun(user_id=u2.id, username="elfira", password_hash=S.hash_sandi("produksi2")))
        db.add(TimbanganAkun(username="elfira", nama="Elfira", role=ROLE_PETUGAS,
                             password_hash=S.hash_sandi("timbang2"), perangkat_kode="P1"))
        # (c) orang ada di users (nama sama) tapi belum punya akun bersama
        u3 = User(nama="Purwadi", role=P.OPERATOR, status="aktif"); db.add(u3)
        db.add(TimbanganAkun(username="purwadi", nama="purwadi", role=ROLE_PETUGAS,
                             password_hash=S.hash_sandi("timbang3"), perangkat_kode="P2"))
        # (d) tak ada padanan sama sekali
        db.add(TimbanganAkun(username="marno", nama="Marno", role=ROLE_PETUGAS,
                             password_hash=S.hash_sandi("timbang4"), perangkat_kode="P3"))
        await db.commit()


async def test_rencana_membaca_saja_dan_menyebut_tindakannya(Sesi):
    await _isi(Sesi)
    async with Sesi() as db:
        daftar = await it.rencana(db)
        assert {l.username: l.tindakan for l in daftar} == {
            "wahid": it.TAUT, "elfira": it.TAUT, "purwadi": it.BUAT_AKUN, "marno": it.BUAT_ORANG}
        assert all(t.akun_id is None for t in (await db.execute(select(TimbanganAkun))).scalars())
        teks = it.cetak(daftar)
        assert "taut 2 · buat akun 1 · buat orang 1 · KONFLIK 0" in teks
        assert "sandi Pos Produksi" in teks  # dijelaskan, bukan diam-diam


async def test_terapkan_menautkan_tanpa_menaikkan_versi_dan_bisa_dilepas(Sesi):
    await _isi(Sesi)
    async with Sesi() as db:
        dikerjakan = await it.terapkan(db)
        assert len(dikerjakan) == 4
    async with Sesi() as db:
        profil = {t.username: t for t in (await db.execute(select(TimbanganAkun))).scalars()}
        assert all(t.akun_id is not None for t in profil.values())
        assert all(t.token_version == 1 for t in profil.values())        # yang bertugas tetap bertugas
        assert all(t.password_hash for t in profil.values())             # sandi lama masih ada → bisa mundur
        # Peran pos timbang mengikuti users.role
        assert profil["wahid"].role == ROLE_SUPERADMIN and profil["elfira"].role == ROLE_ADMIN
        # (c) akun bersama dibuat untuk orang yang sudah ada; sandi = sandi timbangan
        a3 = (await db.execute(select(Akun).where(Akun.username == "purwadi"))).scalars().one()
        assert a3.nama == "Purwadi" and S.cek_sandi("timbang3", a3.password_hash)
        assert (await db.execute(select(User).where(User.nama == "Purwadi"))).scalars().one().id == a3.user_id
        # (d) orang baru + akun baru, peran dipetakan
        a4 = (await db.execute(select(Akun).where(Akun.username == "marno"))).scalars().one()
        assert a4.peran == P.OPERATOR and S.cek_sandi("timbang4", a4.password_hash)
        # Menjalankan lagi: tak ada yang tersisa
        assert await it.terapkan(db) == []
        assert all(l.tindakan == it.SUDAH for l in await it.rencana(db))
    async with Sesi() as db:
        assert await it.lepas(db) == 4
    async with Sesi() as db:
        assert all(t.akun_id is None for t in (await db.execute(select(TimbanganAkun))).scalars())


async def test_konflik_tak_disentuh(Sesi):
    async with Sesi() as db:
        u1 = User(nama="Eka", role=P.ADMIN, status="aktif"); db.add(u1); await db.flush()
        db.add(Akun(user_id=u1.id, username="eka", password_hash=S.hash_sandi("x1x1x1x1")))
        u2 = User(nama="Eka Lain", role=P.OPERATOR, status="aktif"); db.add(u2); await db.flush()
        db.add(Akun(user_id=u2.id, username="ekalain", password_hash=S.hash_sandi("x2x2x2x2")))
        # user_id menunjuk Eka Lain, nama pengguna sama dengan akun Eka
        db.add(TimbanganAkun(username="eka", nama="Eka", role=ROLE_PETUGAS, user_id=u2.id,
                             password_hash=S.hash_sandi("timbang"), perangkat_kode="P5"))
        await db.commit()
    async with Sesi() as db:
        daftar = await it.rencana(db)
        assert daftar[0].tindakan == it.KONFLIK and "putuskan" in daftar[0].keterangan
        assert await it.terapkan(db, daftar) == []
        assert (await db.execute(select(TimbanganAkun))).scalars().one().akun_id is None

"""Versi kode yang sedang berjalan terlihat di Pengaturan Pos Timbang.

Lewat HTTP dengan SQLite: tabel `alembic_version_timbangan` dibuat oleh uji
ini sendiri (skema uji dibangun dari metadata, jadi tabel versinya tak ada),
diisi head, lalu DITURUNKAN satu revisi untuk memicu peringatan.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app import database
from app.database import Base
from app.timbangan import skema, versi
from app.timbangan.models import ROLE_ADMIN, ROLE_PETUGAS, TimbanganAkun
from app.timbangan.security import hash_sandi
from app.timbangan.web import PREFIX, VERSI, pasang

AKAR = pathlib.Path(__file__).resolve().parents[2]
SANDI = "rahasia123"
TABEL = skema.TABEL_VERSI


def _turun_satu(head: str) -> str:
    berkas = AKAR / "migrations" / "versions" / f"{head}.py"
    spec = importlib.util.spec_from_file_location(head, berkas)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.down_revision


@pytest_asyncio.fixture
async def sesi(monkeypatch):
    mesin = create_async_engine("sqlite+aiosqlite://")
    async with mesin.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            f"CREATE TABLE {TABEL} (version_num VARCHAR(64) NOT NULL PRIMARY KEY)"))
        await conn.execute(text(f"INSERT INTO {TABEL} VALUES (:r)"),
                           {"r": skema._head_dari_berkas()})
    Sesi = async_sessionmaker(mesin, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", Sesi)
    async with Sesi() as db:
        db.add_all([
            TimbanganAkun(username="budi", nama="Budi", role=ROLE_PETUGAS,
                          password_hash=hash_sandi(SANDI), perangkat_kode="P1"),
            TimbanganAkun(username="wahid", nama="Wahid", role=ROLE_ADMIN,
                          password_hash=hash_sandi(SANDI), perangkat_kode="P0"),
        ])
        await db.commit()
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeefcafe")
    versi.komit.cache_clear()
    yield Sesi
    versi.komit.cache_clear()
    await mesin.dispose()


@pytest_asyncio.fixture
async def klien(sesi):
    aplikasi = FastAPI()
    pasang(aplikasi)
    async with AsyncClient(transport=ASGITransport(app=aplikasi),
                           base_url="http://uji", follow_redirects=True) as c:
        yield c


async def _masuk(klien, siapa):
    r = await klien.post(f"{PREFIX}/masuk", data={
        "username": siapa, "sandi": SANDI, "perangkat": "P1", "tujuan": ""})
    assert r.status_code == 200, r.text


async def test_baris_versi_muncul_di_pengaturan(klien):
    head = skema._head_dari_berkas()
    for siapa in ("budi", "wahid"):
        await _masuk(klien, siapa)
        html = (await klien.get(f"{PREFIX}/pengaturan")).text
        assert 'data-uji="baris-versi"' in html
        assert f"Versi {VERSI} · deadbee · migrasi {head}" in " ".join(html.split()), siapa
        assert 'role="alert"' not in html


async def test_peringatan_bila_alembic_version_turun_satu_revisi(klien, sesi):
    head = skema._head_dari_berkas()
    turun = _turun_satu(head)
    assert turun and turun != head
    async with sesi() as db:
        await db.execute(text(f"UPDATE {TABEL} SET version_num = :r"), {"r": turun})
        await db.commit()

    await _masuk(klien, "wahid")                      # admin
    html = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert 'data-uji="skema-tertinggal"' in html
    assert "alembic upgrade head" in html
    assert turun in html and f"(kode: {head})" in html

    await _masuk(klien, "budi")                       # petugas: tak perlu tahu
    html = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert 'data-uji="skema-tertinggal"' not in html
    assert 'data-uji="baris-versi"' in html


def test_revisi_tak_dikenal_berarti_kode_lama():
    head = skema._head_dari_berkas()
    assert versi.banding("9999_masa_depan", head) == versi.KODE_LAMA
    assert versi.banding(None, head) == versi.TAK_TERBACA
    assert versi.banding(head, head) == versi.SELARAS


def test_hanya_hash_commit_yang_dibaca_dari_lingkungan():
    import re

    sumber = (AKAR / "app/timbangan/versi.py").read_text()
    assert re.findall(r"os\.environ[^\n]*", sumber) == [
        'os.environ.get("RAILWAY_GIT_COMMIT_SHA"))']
    docker = (AKAR / "Dockerfile").read_text()
    assert "ARG RAILWAY_GIT_COMMIT_SHA" in docker and "> /app/KOMIT" in docker

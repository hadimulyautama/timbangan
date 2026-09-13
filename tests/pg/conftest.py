"""Uji pos timbang di Postgres sungguhan — hanya bila `UJI_PG_URL` disetel
(loopback, nama basis data `uji_*`). Skema dari metadata (hmu_core +
hmu_identitas + timbangan_*); kesepadanan migrasi-dengan-model dijaga
`tests/timbangan/test_skema.py`.

    UJI_PG_URL=postgresql+asyncpg://postgres:uji@127.0.0.1:55434/uji_timbangan \\
        .venv/bin/python -m pytest -q tests/pg
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio


def _url() -> str | None:
    url = os.environ.get("UJI_PG_URL", "").strip()
    if not url:
        return None
    if not ("127.0.0.1" in url or "localhost" in url):
        pytest.fail(f"UJI_PG_URL bukan loopback: {url.rsplit('@', 1)[-1]}")
    nama = url.rsplit("/", 1)[-1].split("?")[0]
    if not nama.startswith("uji_"):
        pytest.fail(f"nama basis data uji wajib berawalan 'uji_', bukan '{nama}'")
    return url


@pytest_asyncio.fixture
async def mesin(monkeypatch):
    url = _url()
    if url is None:
        pytest.skip("UJI_PG_URL kosong — uji Postgres dilewati")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models  # noqa: F401
    from app import database
    from app.database import Base
    from app.timbangan import security as sec, service
    from hmu_core import Warehouse

    m = create_async_engine(url)
    async with m.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Sesi = async_sessionmaker(m, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", Sesi)
    monkeypatch.setattr(sec, "_KUNCI_SEMENTARA", b"k" * 32, raising=False)
    async with Sesi() as db:
        await service.pastikan_jenis(db)
        db.add(Warehouse(nama_gudang="Gudang 2 — Penyosohan"))
        await db.commit()
    try:
        yield Sesi
    finally:
        async with m.begin() as conn:
            await conn.execute(text("""
                DO $$ DECLARE t text;
                BEGIN
                  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
                            AND tablename NOT LIKE 'alembic\\_version%' ESCAPE '\\'
                  LOOP EXECUTE format('TRUNCATE TABLE %I RESTART IDENTITY CASCADE', t); END LOOP;
                END $$;"""))
        await m.dispose()


@pytest_asyncio.fixture
async def klien(mesin):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.timbangan.web import pasang

    aplikasi = FastAPI()
    pasang(aplikasi)
    async with AsyncClient(transport=ASGITransport(app=aplikasi), base_url="http://uji") as c:
        yield c

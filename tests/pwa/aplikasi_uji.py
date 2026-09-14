"""Pos timbang di atas Postgres uji (`UJI_PG_URL`), dijalankan uvicorn oleh uji Playwright.

Postgres, bukan SQLite: penanda keadaan memakai `extract(epoch …)` yang tak
dikenal SQLite, dan suite timbangan yang berjalan di SQLite memang tak pernah
melihat endpoint itu hidup (temuan QA putaran 4). Tabel dikosongkan saat
server berhenti supaya uji Postgres lain tak menemukan sisa."""
from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.database import Base
from app.timbangan import service, web
from app.timbangan.models import ROLE_ADMIN, TimbanganAkun
from app.timbangan.security import hash_sandi

SANDI = "rahasia123"
mesin = create_async_engine(os.environ["UJI_PG_URL"])
Sesi = async_sessionmaker(mesin, expire_on_commit=False)
database.SessionLocal = Sesi


async def _siapkan() -> None:
    import app.models  # noqa: F401
    async with mesin.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Sesi() as db:
        await service.pastikan_jenis(db)
        db.add(TimbanganAkun(username="wahid", nama="Wahid", role=ROLE_ADMIN,
                             password_hash=hash_sandi(SANDI), perangkat_kode="P0"))
        await db.commit()


from contextlib import asynccontextmanager


@asynccontextmanager
async def _hidup(_: FastAPI):
    await _siapkan()
    yield
    from sqlalchemy import text
    async with mesin.begin() as conn:
        await conn.execute(text("""
            DO $$ DECLARE t text;
            BEGIN
              FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
                        AND tablename NOT LIKE 'alembic\\_version%' ESCAPE '\\'
              LOOP EXECUTE format('TRUNCATE TABLE %I RESTART IDENTITY CASCADE', t); END LOOP;
            END $$;"""))
    await mesin.dispose()


app = FastAPI(lifespan=_hidup)
web.pasang(app)


class VersiIn(BaseModel):
    versi: str


@app.post("/uji/versi")
async def ubah_versi(b: VersiIn) -> dict:
    """Server mengaku memegang versi lain — dibaca /timbangan/keadaan."""
    web.VERSI = b.versi
    return {"versi": web.VERSI}

"""Permintaan lebih banyak dari koneksi tidak boleh menunggu koneksi kedua."""
import asyncio
import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from tests.pg.test_batas_laporan_pg import isi
from app.timbangan.main import app
from app.timbangan.security import buat_token,NAMA_COOKIE

pytestmark=pytest.mark.asyncio

async def test_pool_dua_koneksi_melayani_enam_permintaan(mesin,monkeypatch):
    from app import database
    data=await isi(mesin,20)
    engine=create_async_engine(mesin.kw['bind'].url,pool_size=2,max_overflow=0,pool_timeout=2)
    monkeypatch.setattr(database,'SessionLocal',async_sessionmaker(engine,expire_on_commit=False))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={NAMA_COOKIE:buat_token(data['akun'][1].id)}) as c:
            responses=await asyncio.wait_for(asyncio.gather(*(c.get('/timbangan/tiket') for _ in range(6))),5)
            assert all(r.status_code==200 for r in responses)
    finally:await engine.dispose()

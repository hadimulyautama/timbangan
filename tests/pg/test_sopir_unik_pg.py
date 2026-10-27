"""Dua petugas serentak tetap mendapat satu entri nama sopir."""
import asyncio

from sqlalchemy import func, select

from app.timbangan.models import TimbanganSopir, TimbanganSopirAlias
from app.timbangan.sopir import nama_utama


async def test_dua_sesi_memakai_nama_yang_sama(mesin):
    async def simpan(nama):
        async with mesin() as db:
            hasil = await nama_utama(db, nama)
            await db.commit()
            return hasil
    hasil = await asyncio.gather(simpan("Didik Pamungkas"), simpan(" didik  PAMUNGKAS "))
    assert hasil[0] == hasil[1]
    async with mesin() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganSopir)) == 1


async def test_alias_dan_nama_utama_serentak_tidak_membuat_sopir_baru(mesin):
    async with mesin() as db:
        await nama_utama(db, "Didik Pamungkas")
        utama = await db.scalar(select(TimbanganSopir))
        db.add(TimbanganSopirAlias(kunci_nama="didik", nama="DIDIK", sopir_id=utama.id))
        await db.commit()

    async def simpan(nama):
        async with mesin() as db:
            hasil = await nama_utama(db, nama)
            await db.commit()
            return hasil

    hasil = await asyncio.gather(simpan("DIDIK"), simpan(" didik "), simpan("Didik Pamungkas"))
    assert hasil == ["Didik Pamungkas"] * 3
    async with mesin() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganSopir)) == 1

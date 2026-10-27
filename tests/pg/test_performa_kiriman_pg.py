"""Regresi kiriman ulang biasa: dua perangkat tidak boleh berlomba membuat tiket."""
import asyncio
from uuid import uuid4

from sqlalchemy import func, select

from app.models import Supplier
from app.timbangan import service
from app.timbangan.models import TimbanganAkun, TimbanganKendaraan, TimbanganTransaksi
from app.timbangan.security import NAMA_COOKIE, buat_token


async def benih(mesin):
    async with mesin() as db:
        akun = TimbanganAkun(username="uji_serentak", nama="Petugas Sintetis", role="PETUGAS",
                             perangkat_kode="U1", password_hash="x")
        supplier = Supplier(nama_supplier="Pemasok Sintetis", kledo_contact_id=9001)
        db.add_all([akun, supplier])
        await db.commit()
        return akun.id, supplier.id


async def test_sepuluh_replay_form_biasa_semuanya_mengonfirmasi_satu_tiket(mesin, klien):
    aid, sid = await benih(mesin)
    data = {"kunci": str(uuid4()), "berat_kg": "15000", "supplier_id": str(sid),
            "nomor_polisi": "B 1234 UJ", "nama_sopir": "Didik Sintetis"}
    headers = {"Cookie": NAMA_COOKIE + "=" + buat_token(aid)}
    respons = await asyncio.gather(*(klien.post(
        "/timbangan/timbang/GABAH_KERING", data=data, headers=headers
    ) for _ in range(10)))
    assert all(r.status_code == 303 and "/transaksi/" in r.headers.get("location", "")
               and "err=" not in r.headers["location"] for r in respons)
    assert len({r.headers["location"] for r in respons}) == 1
    async with mesin() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi)) == 1
        assert await db.scalar(select(func.count()).select_from(TimbanganKendaraan)) == 1


async def test_kunci_sama_isi_berbeda_serentak_tidak_menimpa(mesin, klien):
    aid, sid = await benih(mesin)
    data = {"kunci": str(uuid4()), "supplier_id": str(sid),
            "nomor_polisi": "B 1234 UJ", "nama_sopir": "Didik Sintetis"}
    headers = {"Cookie": NAMA_COOKIE + "=" + buat_token(aid)}
    respons = await asyncio.gather(*(klien.post(
        "/timbangan/timbang/GABAH_KERING", data={**data, "berat_kg": str(kg)}, headers=headers
    ) for kg in (15000, 16000)))
    assert sum("?ok=" in r.headers.get("location", "") for r in respons) == 1
    assert sum("?err=" in r.headers.get("location", "") for r in respons) == 1
    async with mesin() as db:
        rows = list((await db.scalars(select(TimbanganTransaksi))).all())
        assert len(rows) == 1 and float(rows[0].timbang1_kg) in (15000, 16000)


async def test_master_kendaraan_baru_serentak_tetap_satu(mesin):
    async def satu():
        async with mesin() as db:
            kendaraan = await service.kendaraan_dari_nopol(db, "B 1234 UJ")
            await db.commit()
            return kendaraan.id
    ids = await asyncio.gather(*(satu() for _ in range(10)))
    assert len(set(ids)) == 1

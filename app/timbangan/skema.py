"""Apakah skema chain TIMBANGAN selaras dengan kode yang sedang berjalan?

Temuan QA X-04, dan di sinilah akibatnya paling jelas: X-03 membuat migrasi
0027–0029 terlewat diam-diam, sehingga SETIAP kueri tiket gagal karena kolom
yang tak pernah dibuat — sementara /health tetap menjawab "ok". Pos timbang
menyala, tak bisa dipakai, dan tak ada satu tanda pun yang menyebut sebabnya.
"""
from __future__ import annotations

import logging
import pathlib

from sqlalchemy import text

from app.timbangan.db import sesi_db

log = logging.getLogger("timbangan.skema")

TABEL_VERSI = "alembic_version_timbangan"


def _head_dari_berkas() -> str | None:
    akar = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
    try:
        berkas = sorted(p.stem for p in akar.glob("00*.py"))
        return berkas[-1] if berkas else None
    except Exception:  # noqa: BLE001
        return None


async def keadaan() -> dict:
    head = _head_dari_berkas()
    try:
        async with sesi_db() as db:
            revisi = (await db.execute(
                text(f"SELECT version_num FROM {TABEL_VERSI}")
            )).scalars().first()
    except Exception as e:  # noqa: BLE001
        log.warning("Revisi skema timbangan tak terbaca: %s", e)
        return {"revisi": None, "head": head, "selaras": False,
                "galat": type(e).__name__}
    return {"revisi": revisi, "head": head,
            "selaras": bool(revisi and head and revisi == head)}

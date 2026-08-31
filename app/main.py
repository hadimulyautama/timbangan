"""Titik masuk aplikasi Pos Timbang.

Seluruh isinya satu baris kerja: `pasang(app)`. Modulnya memang dirancang
begitu sejak awal — mandiri, satu baris untuk menyematkan atau melepas — dan
justru itulah yang membuat pemisahannya dari repo penggilingan menjadi murah.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from app.timbangan.web import pasang

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(
    title="Pos Timbang · PT Hadi Mulya Utama",
    docs_url=None, redoc_url=None, openapi_url=None,
)
pasang(app)


@app.get("/health")
async def health():
    return {"status": "ok", "modul": "timbangan"}


@app.get("/")
async def akar():
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/timbangan/")


@app.on_event("startup")
async def semai():
    """Isi master komoditas dan akun Admin pertama bila belum ada.

    Keduanya hanya MENAMBAH yang belum ada; aturan yang sudah disetel dari
    layar tidak pernah ditimpa nilai bawaan kode.
    """
    from app.database import SessionLocal
    from app.timbangan import service

    async with SessionLocal() as db:
        ditambah = await service.pastikan_jenis(db)
        if ditambah:
            logging.info("Master komoditas: %s jenis ditambahkan", ditambah)
        if await service.pastikan_admin(db):
            logging.info("Akun Admin pertama dibuat dari environment")

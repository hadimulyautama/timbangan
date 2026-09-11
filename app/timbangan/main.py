"""Titik masuk aplikasi Pos Timbang.

Sengaja TIDAK memuat bot Telegram, poller, maupun modul produksi — deploy pos
timbang tidak boleh sanggup menjatuhkan bot yang sedang melayani manajemen,
dan sebaliknya. Sejak 31 Agustus 2026 pemisahan itu bukan lagi soal service
saja melainkan repo: keduanya tidak lagi saling memicu rilis.

Migrasi TIDAK dijalankan dari sini melainkan oleh entrypoint image
(`docker/entrypoint.sh` → `scripts/siapkan_skema.py`), sebelum server menyala.
Dulu migrasi memang dilewati sama sekali karena riwayatnya milik service lain;
sekarang repo ini memiliki rangkaiannya sendiri dengan tabel versi terpisah.

Yang tetap dikerjakan di sini adalah menyemai master komoditas dan akun Admin
pertama — aman dijalankan berulang: hanya menambah yang belum ada, tidak
pernah menimpa aturan yang sudah disetel dari layar.

Jalankan:  uvicorn app.timbangan.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.timbangan.web import PREFIX, pasang

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
)
log = logging.getLogger("timbangan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.timbangan import service
    from app.timbangan.db import sesi_db

    try:
        async with sesi_db() as db:
            ditambah = await service.pastikan_jenis(db)
            if ditambah:
                log.info("Master komoditas: %d baris ditambahkan", ditambah)
            if await service.pastikan_admin(db):
                log.info("Akun admin awal dibuat")
    except Exception:
        # Penyemaian gagal tidak boleh menahan service menyala — halaman
        # tetap dapat dilayani, dan aturan bawaan dari kode tetap berlaku.
        log.exception("Penyemaian awal gagal (lanjut jalan)")
    yield


app = FastAPI(title="Pos Timbang — PT Hadi Mulya Utama", lifespan=lifespan)
pasang(app)


@app.get("/")
async def akar():
    return RedirectResponse(f"{PREFIX}/")


@app.get("/health")
async def health() -> dict:
    """Kesehatan, termasuk apakah SKEMA-nya selaras dengan kode ini.

    X-03 membuat migrasi 0027–0029 terlewat diam-diam, sehingga setiap kueri
    tiket gagal karena kolom yang tak pernah dibuat — sementara jawaban ini
    tetap "ok". Pos timbang menyala, tak bisa dipakai, dan tak ada satu tanda
    pun yang menyebut sebabnya. Temuan QA X-04.
    """
    from app.timbangan.skema import keadaan

    skema = await keadaan()
    return {
        "status": "ok" if skema["selaras"] else "skema-tidak-selaras",
        "skema": skema,
        "modul": "timbangan",
    }

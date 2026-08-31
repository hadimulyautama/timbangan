"""Konfigurasi fondasi — hanya yang benar-benar milik lingkungan.

Sengaja sangat kecil. Setelan operasional Timbangan tidak di sini melainkan
di `app/timbangan/config.py` dan tabel `timbangan_config`; aturan komoditas
di tabel `timbangan_jenis`. Pemisahan itu sudah ada sejak modul ini masih
menumpang di repo penggilingan, dan dipertahankan apa adanya.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    #: Postgres yang SAMA dengan sistem penggilingan — lihat README §Database.
    database_url: str = os.getenv("DATABASE_URL", "").replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    app_timezone: str = os.getenv("APP_TIMEZONE", "Asia/Jakarta")


settings = Settings()

"""Konfigurasi fondasi — hanya yang benar-benar milik lingkungan.

Sengaja sangat kecil. Setelan operasional Timbangan tidak di sini melainkan
di `app/timbangan/config.py` dan tabel `timbangan_config`; aturan komoditas
di tabel `timbangan_jenis`. Pemisahan itu sudah ada sejak modul ini masih
menumpang di repo penggilingan, dan dipertahankan apa adanya.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _url_asyncpg(mentah: str) -> str:
    """Bentuk URL yang diberikan penyedia → bentuk yang dipahami asyncpg.

    Railway dan kebanyakan penyedia memberi `postgresql://` atau `postgres://`
    (driver sinkron), sedangkan aplikasi ini butuh `postgresql+asyncpg://`.
    Parameter `sslmode` juga dibuang: itu milik psycopg2; asyncpg memakai
    `ssl` dan akan menolak koneksi bila menemuinya.

    Disalin apa adanya dari konfigurasi repo penggilingan. Bentuk URL yang
    tidak ditangani hanya akan gagal saat menyambung — di produksi, bukan di
    uji — jadi tidak ada gunanya menyederhanakannya di sini.
    """
    if mentah.startswith("postgres://"):
        mentah = "postgresql+asyncpg://" + mentah[len("postgres://"):]
    elif mentah.startswith("postgresql://"):
        mentah = "postgresql+asyncpg://" + mentah[len("postgresql://"):]
    if mentah.startswith("postgresql+asyncpg://") and "sslmode=" in mentah:
        pisah = mentah.split("?", 1)
        if len(pisah) == 2:
            sisa = "&".join(
                b for b in pisah[1].split("&") if not b.startswith("sslmode=")
            )
            mentah = pisah[0] + (f"?{sisa}" if sisa else "")
    return mentah


@dataclass(frozen=True)
class Settings:
    #: Postgres yang SAMA dengan sistem penggilingan — lihat README.
    database_url: str = _url_asyncpg(os.getenv("DATABASE_URL", ""))
    app_timezone: str = os.getenv("APP_TIMEZONE", "Asia/Jakarta")

    # ── Seam Timbangan → Produksi (pemicu sinkron kontak Kledo) ──
    #
    # Timbangan TIDAK PERNAH memegang KLEDO_API_KEY — kunci itu luas (bisa
    # membaca seluruh keuangan perusahaan lewat Kledo) dan modul ini sengaja
    # price-blind (lihat aturan di atas). Yang dipunyai di sini hanya alamat
    # & token untuk MEMICU sinkron yang berjalan di produksi; lihat
    # `app/timbangan/klien_produksi.py`.
    produksi_api_url: str = os.getenv("PRODUKSI_API_URL", "")
    produksi_api_token: str = os.getenv("PRODUKSI_API_TOKEN", "")  # = INTERNAL_API_TOKEN di sisi produksi
    produksi_api_timeout: float = float(os.getenv("PRODUKSI_API_TIMEOUT", "120"))
    produksi_web_url: str = os.getenv(
        "PRODUKSI_WEB_URL", "https://penggilingan-beras-production.up.railway.app"
    ).rstrip("/")


settings = Settings()

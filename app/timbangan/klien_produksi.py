"""Klien HTTP ke API internal PRODUKSI — memicu sinkron kontak Kledo.

Timbangan tidak pernah memegang `KLEDO_API_KEY` sendiri (lihat `app/config.py`
dan alasan keamanannya di sana). Yang dipunyai modul ini hanya dua rute kecil
di sisi produksi: mulai satu putaran, dan baca keadaannya. Sinkron sungguhan —
mengambil ~600 kontak Kledo, menaut/membuat baris `suppliers`/`pelanggan` —
berjalan di PRODUKSI. Timbangan tidak menulis apa pun sendiri: begitu produksi
selesai menulis, timbangan membacanya langsung dari Postgres yang sama.

Konfigurasi (env), lewat `app/config.py`:
  PRODUKSI_API_URL    alamat service produksi, mis. https://xxx.up.railway.app
  PRODUKSI_API_TOKEN  harus sama dengan INTERNAL_API_TOKEN di sisi produksi.

Semua fungsi FAIL-SOFT: bila belum dikonfigurasi / produksi sedang tak
terjangkau, lempar `ProduksiTakTersedia` dengan pesan siap-tampil, bukan
traceback. Pola ini disalin dari `kantor/app/kantor/klien_produksi.py` — klien
serupa yang sudah ada dan terbukti, bukan dirancang ulang dari nol.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("timbangan.klien_produksi")


class ProduksiTakTersedia(Exception):
    """Service produksi belum dikonfigurasi / tak bisa dihubungi."""


def terkonfigurasi() -> bool:
    return bool(settings.produksi_api_url and settings.produksi_api_token)


async def _minta(metode: str, path: str) -> dict:
    if not terkonfigurasi():
        raise ProduksiTakTersedia(
            "Sambungan ke sistem produksi belum diatur (PRODUKSI_API_URL/TOKEN)."
        )
    url = settings.produksi_api_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=settings.produksi_api_timeout) as c:
            r = await c.request(
                metode, url, headers={"X-Internal-Token": settings.produksi_api_token},
            )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        kode = e.response.status_code
        log.warning("API produksi menolak %s (%s)", path, kode)
        if kode in (403, 404):
            raise ProduksiTakTersedia(
                "Sistem produksi menolak permintaan (token/API internal belum aktif)."
            ) from e
        raise ProduksiTakTersedia("Sistem produksi sedang bermasalah.") from e
    except httpx.HTTPError as e:
        log.warning("API produksi tak terjangkau %s", path, exc_info=True)
        raise ProduksiTakTersedia("Sistem produksi sedang tak bisa dihubungi.") from e


async def mulai_sinkron_kontak() -> bool:
    """Minta produksi memulai satu putaran sinkron kontak Kledo di latar.

    Balasannya datang SEGERA — produksi tak menunggu ~600 kontak selesai
    diambil sebelum membalas. `True` berarti putaran baru benar-benar
    dimulai; `False` berarti sudah ada yang berjalan (ditolak dengan tenang,
    bukan ditolak sebagai galat — menekan tombol saat sudah berjalan bukan
    kesalahan pemakai).
    """
    data = await _minta("POST", "/internal/kledo-kontak/sinkron")
    return bool(data.get("dimulai"))


async def status_sinkron_kontak() -> dict:
    """Keadaan sekarang: terkonfigurasi, sedang berjalan, hasil/gagal terakhir."""
    return await _minta("GET", "/internal/kledo-kontak/status")

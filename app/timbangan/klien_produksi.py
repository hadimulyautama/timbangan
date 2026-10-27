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


class ProduksiDilarang(ProduksiTakTersedia):
    """Izin layanan/akun ditolak; tidak ditampilkan sebagai rincian kosong."""


def terkonfigurasi() -> bool:
    return bool(settings.produksi_api_url and settings.produksi_api_token)


async def _minta(metode: str, path: str, *, operator_akun_id: int | None = None, body: dict | None = None) -> dict:
    if not terkonfigurasi():
        raise ProduksiTakTersedia(
            "Sambungan ke sistem produksi belum diatur (PRODUKSI_API_URL/TOKEN)."
        )
    url = settings.produksi_api_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=settings.produksi_api_timeout) as c:
            headers = {"X-Internal-Token": settings.produksi_api_token}
            if operator_akun_id is not None:
                headers["X-Operator-Akun"] = str(int(operator_akun_id))
            r = await c.request(metode, url, headers=headers, **({'json':body} if body is not None else {}))
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        kode = e.response.status_code
        log.warning("API produksi menolak %s (%s)", path, kode)
        if kode == 409:
            try:
                detail = e.response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            raise ProduksiTakTersedia(str(detail or "Data pengiriman belum cocok.")) from e
        if kode == 403:
            raise ProduksiDilarang('Akses rincian PadiFlow ditolak. Periksa izin akun tertaut dan sambungan layanan.') from e
        if kode == 404:
            raise ProduksiTakTersedia(
                "Sistem produksi menolak permintaan (token/API internal belum aktif)."
            ) from e
        raise ProduksiTakTersedia("Sistem produksi sedang bermasalah.") from e
    except (httpx.HTTPError, ValueError) as e:
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


async def muatan_pengiriman(tiket_id: int) -> dict:
    """Baca daftar muatan nyata pada perintah Produksi untuk tiket keluar."""
    return await _minta("GET", f"/internal/pengiriman/tiket/{int(tiket_id)}/muatan")


async def selesaikan_pengiriman(tiket_id: int, operator_akun_id: int, *, sidik_sumber: str | None = None) -> dict:
    """Minta Produksi menautkan tiket dan memverifikasi transaksi keluar."""
    return await _minta(
        "POST", f"/internal/pengiriman/tiket/{int(tiket_id)}/verifikasi",
        operator_akun_id=operator_akun_id,
        **({"body":{"sidik_sumber":sidik_sumber}} if sidik_sumber else {}),
    )


async def muatan_retur(tiket_id: int) -> dict:
    """Jumlah karung dan tara per kemasan yang dicatat saat bongkar di Produksi."""
    return await _minta("GET", f"/internal/retur/tiket/{int(tiket_id)}/muatan")


async def detail_retur(tiket_id: int, operator_akun_id: int) -> dict:
    """Status/rincian baca saja, bukan pemicu pemeriksaan atau penerimaan."""
    return await _minta('GET', f'/internal/retur/tiket/{int(tiket_id)}/detail',
                        operator_akun_id=operator_akun_id)

"""Pembatas percobaan masuk Pos Timbang — per nama pengguna DAN alamat IP.

RANCANGAN §10 menuntut pembatasan percobaan dan audit login gagal. Sampai
11 September 2026 tak ada satu pun dari keduanya: seluruh daftar sandi bisa
dicoba satu per satu, dan tak ada baris di mana pun yang mencatatnya.
Temuan QA T-19.

Di memori, bukan di basis data: layanan ini satu replika, jadi satu proses
melihat seluruh percobaan. Hitungan yang hilang saat restart bukan kerugian —
penebak yang sabar menunggu deploy sudah tertahan oleh hal lain.

Pasangan nama+IP, bukan salah satunya: mengunci berdasarkan nama saja memberi
penyerang cara mengunci petugas lain, dan berdasarkan IP saja mengunci seluruh
gudang yang keluar lewat satu sambungan.
"""
from __future__ import annotations

import time
from collections import defaultdict

BATAS_GAGAL = 5
JEDA_DETIK = 300
UMUR_DETIK = 900

_gagal: dict[tuple[str, str], list[float]] = defaultdict(list)


def _kunci(username: str, ip: str) -> tuple[str, str]:
    return ((username or "").strip().lower(), (ip or "").strip())


def _bersih(waktu: list[float], sekarang: float) -> list[float]:
    return [t for t in waktu if sekarang - t < UMUR_DETIK]


def boleh_coba(username: str, ip: str) -> float | None:
    """None bila boleh mencoba; selain itu sisa detik penahanan."""
    k = _kunci(username, ip)
    kini = time.monotonic()
    waktu = _bersih(_gagal.get(k, []), kini)
    _gagal[k] = waktu
    if len(waktu) < BATAS_GAGAL:
        return None
    sisa = JEDA_DETIK - (kini - waktu[-1])
    return sisa if sisa > 0 else None


def catat_gagal(username: str, ip: str) -> None:
    k = _kunci(username, ip)
    kini = time.monotonic()
    _gagal[k] = _bersih(_gagal.get(k, []), kini) + [kini]


def catat_berhasil(username: str, ip: str) -> None:
    """Masuk yang berhasil menghapus hitungannya — petugas yang salah ketik
    empat kali lalu berhasil tak boleh terkunci oleh salah ketik berikutnya."""
    _gagal.pop(_kunci(username, ip), None)


def bersihkan() -> None:
    """Kosongkan hitungan. Dipakai uji; tak dipanggil aplikasi."""
    _gagal.clear()

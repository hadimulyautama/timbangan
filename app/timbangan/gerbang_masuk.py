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
from collections import OrderedDict

BATAS_GAGAL = 5
JEDA_DETIK = 300
UMUR_DETIK = 900

MAKS_KUNCI = 10_000
_gagal: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
_terakhir_bersih = 0.0


def _pangkas(kini: float) -> None:
    global _terakhir_bersih
    if kini - _terakhir_bersih < 60:
        return
    for k, nilai in list(_gagal.items()):
        hidup = _bersih(nilai, kini)
        if hidup:
            _gagal[k] = hidup
        else:
            _gagal.pop(k, None)
    _terakhir_bersih = kini


def _kunci(username: str, ip: str) -> tuple[str, str]:
    return ((username or "").strip().lower(), (ip or "").strip())


def _bersih(waktu: list[float], sekarang: float) -> list[float]:
    return [t for t in waktu if sekarang - t < UMUR_DETIK]


def boleh_coba(username: str, ip: str) -> float | None:
    """None bila boleh mencoba; selain itu sisa detik penahanan."""
    k = _kunci(username, ip)
    kini = time.monotonic()
    _pangkas(kini)
    waktu = _bersih(_gagal.get(k, []), kini)
    if waktu:
        _gagal[k] = waktu
        _gagal.move_to_end(k)
    else:
        _gagal.pop(k, None)
    if len(waktu) < BATAS_GAGAL:
        return None
    sisa = JEDA_DETIK - (kini - waktu[-1])
    return sisa if sisa > 0 else None


def catat_gagal(username: str, ip: str) -> None:
    k = _kunci(username, ip)
    kini = time.monotonic()
    _pangkas(kini)
    if k not in _gagal and len(_gagal) >= MAKS_KUNCI:
        # Batas memori tetap; pasangan yang baru dipakai dipertahankan.
        _gagal.popitem(last=False)
    _gagal[k] = (_bersih(_gagal.get(k, []), kini) + [kini])[-BATAS_GAGAL:]
    _gagal.move_to_end(k)


def catat_berhasil(username: str, ip: str) -> None:
    """Masuk yang berhasil menghapus hitungannya — petugas yang salah ketik
    empat kali lalu berhasil tak boleh terkunci oleh salah ketik berikutnya."""
    _gagal.pop(_kunci(username, ip), None)


def bersihkan() -> None:
    """Kosongkan hitungan. Dipakai uji; tak dipanggil aplikasi."""
    _gagal.clear()
    _generasi_console.clear()
    global _terakhir_bersih
    _terakhir_bersih = 0.0


_generasi_console={}

def pakai_generasi(username: str, versi: int) -> None:
    username=(username or '').strip().lower()
    lama=_generasi_console.get(username,0)
    if lama!=versi:
        for key in list(_gagal):
            if key[0]==username:_gagal.pop(key,None)
    if len(_generasi_console)>4096:_generasi_console.clear()
    _generasi_console[username]=versi

"""Buat gambar layar pembuka iOS (`apple-touch-startup-image`).

Android mengambil warna & ikon layar pembuka dari `manifest.json`. iOS TIDAK:
ia hanya mau memakai gambar jadi, satu berkas per ukuran layar, dicocokkan
lewat media query. Bila tidak ada, aplikasi yang dibuka dari layar depan
menampilkan layar kosong — dan pada perangkat bermode gelap, kosong itu HITAM.
Itulah kilatan gelap sebelum layar pembuka kita muncul.

Jalankan ulang bila ikon atau warna latar berubah:

    .venv/bin/python scripts/buat_gambar_pembuka.py

Hasilnya ditulis ke `app/timbangan/static/pembuka/` dan ditaut dari base.html.
"""
from __future__ import annotations

import pathlib

from PIL import Image

AKAR = pathlib.Path(__file__).resolve().parents[1]
STATIK = AKAR / "app" / "timbangan" / "static"
KELUAR = STATIK / "pembuka"

#: Sama dengan latar terang di teraflow.css — layar pembuka iOS dan layar pembuka
#: di dalam aplikasi harus sewarna, kalau tidak pergantiannya terlihat berkedip.
LATAR = (241, 245, 250)

#: Selebar lambang di app.css (132 px), dikali kerapatan piksel perangkat.
LAMBANG_CSS = 132

#: Ukuran layar iPhone yang masih dipakai, dalam piksel CSS + kerapatannya.
#: Portrait saja — manifest mengunci orientasinya.
PERANGKAT = [
    (320, 568, 2),   # SE generasi 1
    (375, 667, 2),   # SE 2 & 3, 8
    (414, 736, 3),   # 8 Plus
    (375, 812, 3),   # X, XS, 11 Pro, 12 mini, 13 mini
    (414, 896, 2),   # XR, 11
    (414, 896, 3),   # XS Max, 11 Pro Max
    (390, 844, 3),   # 12, 13, 14
    (428, 926, 3),   # 12 Pro Max, 13 Pro Max, 14 Plus
    (393, 852, 3),   # 14 Pro, 15, 15 Pro, 16
    (430, 932, 3),   # 14 Pro Max, 15 Plus, 15 Pro Max
    (402, 874, 3),   # 16 Pro
    (440, 956, 3),   # 16 Pro Max
    (744, 1133, 2),  # iPad mini
    (820, 1180, 2),  # iPad 10
    (834, 1194, 2),  # iPad Pro 11
    (1024, 1366, 2), # iPad Pro 12.9
]


def buat() -> list[tuple[int, int, int]]:
    ikon = Image.open(STATIK / "ikon-512.png").convert("RGBA")
    KELUAR.mkdir(parents=True, exist_ok=True)

    for lebar, tinggi, rapat in PERANGKAT:
        px_l, px_t = lebar * rapat, tinggi * rapat
        kanvas = Image.new("RGB", (px_l, px_t), LATAR)

        sisi = LAMBANG_CSS * rapat
        lambang = ikon.resize((sisi, sisi), Image.LANCZOS)
        # Ditaruh di tengah persis — sama seperti layar pembuka di dalam
        # aplikasi, supaya pergantian keduanya tidak terlihat melompat.
        kanvas.paste(lambang, ((px_l - sisi) // 2, (px_t - sisi) // 2), lambang)

        kanvas.save(KELUAR / f"{px_l}x{px_t}.png", optimize=True)
    return PERANGKAT


def tag_html() -> str:
    """Cetak baris <link> untuk ditempel ke base.html."""
    baris = []
    for lebar, tinggi, rapat in PERANGKAT:
        baris.append(
            f'  <link rel="apple-touch-startup-image"\n'
            f'        media="(device-width: {lebar}px) and (device-height: {tinggi}px)'
            f' and (-webkit-device-pixel-ratio: {rapat}) and (orientation: portrait)"\n'
            f'        href="{{{{ PREFIX }}}}/static/pembuka/{lebar * rapat}x{tinggi * rapat}.png'
            f'?v={{{{ VERSI }}}}">'
        )
    return "\n".join(baris)


if __name__ == "__main__":
    dibuat = buat()
    print(f"{len(dibuat)} gambar pembuka ditulis ke {KELUAR}")
    print()
    print(tag_html())

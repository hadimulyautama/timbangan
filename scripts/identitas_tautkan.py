#!/usr/bin/env python3
"""Tautkan akun pos timbang ke akun bersama (Tahap 2). Baca dulu, baru ubah.

    python -m scripts.identitas_tautkan              # rencana saja (baca saja)
    python -m scripts.identitas_tautkan --terapkan   # jalankan rencana
    python -m scripts.identitas_tautkan --lepas      # mundur: lepaskan semua tautan

Pilihan: `--lewati admin,uji` (akun yang TIDAK ditautkan — akun generik
bukan orang), `--nama elfira="Elfira Geya Ananda"` (nama lengkap di master
saat orangnya dibuat; boleh berulang).

Butuh DATABASE_URL. Aturannya di `app/timbangan/identitas_tautan.py`.
"""
from __future__ import annotations

import asyncio
import sys

from app.timbangan import identitas_tautan as it
from app.timbangan.db import sesi_db


def _pilihan(argv: list[str]) -> tuple[set[str], dict[str, str]]:
    lewati: set[str] = set()
    nama: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i] == "--lewati" and i + 1 < len(argv):
            lewati |= {x for x in argv[i + 1].split(",") if x}
            i += 2
        elif argv[i] == "--nama" and i + 1 < len(argv):
            k, _, v = argv[i + 1].partition("=")
            nama[k] = v.strip("\"'")
            i += 2
        else:
            i += 1
    return lewati, nama


async def _jalan(argv: list[str]) -> int:
    lewati, nama = _pilihan(argv)
    async with sesi_db() as db:
        if "--lepas" in argv:
            n = await it.lepas(db)
            print(f"{n} tautan dilepas — pintu lama berlaku lagi untuk semuanya.")
            return 0
        daftar = await it.rencana(db, lewati=lewati, nama=nama)
        print(it.cetak(daftar))
        if "--terapkan" not in argv:
            print("\n(baca saja — tambahkan --terapkan untuk menjalankan)")
            return 0
        dikerjakan = await it.terapkan(db, daftar)
        print(f"\n{len(dikerjakan)} akun ditautkan.")
        for l in dikerjakan:
            for c in l.catatan:
                if "sandi acak" in c:
                    print(f"  ! {l.username}: {c} — setel ulang sandinya di Pos Produksi / Meja")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_jalan(sys.argv[1:])))

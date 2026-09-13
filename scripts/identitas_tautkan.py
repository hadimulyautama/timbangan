#!/usr/bin/env python3
"""Tautkan akun pos timbang ke akun bersama (Tahap 2). Baca dulu, baru ubah.

    python -m scripts.identitas_tautkan              # rencana saja (baca saja)
    python -m scripts.identitas_tautkan --terapkan   # jalankan rencana
    python -m scripts.identitas_tautkan --lepas      # mundur: lepaskan semua tautan

Butuh DATABASE_URL. Aturannya di `app/timbangan/identitas_tautan.py`.
"""
from __future__ import annotations

import asyncio
import sys

from app.timbangan import identitas_tautan as it
from app.timbangan.db import sesi_db


async def _jalan(argv: list[str]) -> int:
    async with sesi_db() as db:
        if "--lepas" in argv:
            n = await it.lepas(db)
            print(f"{n} tautan dilepas — pintu lama berlaku lagi untuk semuanya.")
            return 0
        daftar = await it.rencana(db)
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

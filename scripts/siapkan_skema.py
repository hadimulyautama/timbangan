#!/usr/bin/env python3
"""Selaraskan riwayat migrasi dengan keadaan database yang sebenarnya.

Dijalankan entrypoint sebelum server menyala. Ada tiga keadaan, dan
membedakannya penting — dua di antaranya terlihat mirip tetapi butuh
perlakuan berlawanan:

  1. `alembic_version_timbangan` sudah berisi  → `upgrade head` biasa.
  2. Tabel versi kosong TAPI `timbangan_transaksi` sudah ada → skema ini
     dibuat sewaktu modulnya masih ikut repo penggilingan. Yang benar adalah
     `stamp head`: mengakui skema yang ada, bukan membuatnya lagi. Tanpa ini
     deploy pertama akan mencoba CREATE TABLE atas tabel yang sudah berisi
     data produksi, lalu gagal.
  3. Keduanya kosong → database baru, `upgrade head` dari nol.

Keadaan 2 hanya mungkin terjadi sekali seumur database. Ia tetap ditulis di
sini, bukan dijalankan manual sekali lalu dilupakan, supaya database uji coba
atau salinan pemulihan kelak tidak menabrak lubang yang sama.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

from sqlalchemy import text

from app.database import dapatkan_engine

TABEL_VERSI = "alembic_version_timbangan"
TABEL_PENANDA = "timbangan_transaksi"


async def periksa() -> str:
    async with dapatkan_engine().connect() as conn:
        async def ada(nama: str) -> bool:
            return bool((await conn.execute(
                text("SELECT to_regclass(:n)"), {"n": nama}
            )).scalar())

        if await ada(TABEL_VERSI):
            terisi = (await conn.execute(
                text(f"SELECT count(*) FROM {TABEL_VERSI}")
            )).scalar_one()
            if terisi:
                return "upgrade"
        return "stamp" if await ada(TABEL_PENANDA) else "upgrade"


def jalankan(perintah: list[str]) -> int:
    print(f"[skema] {' '.join(perintah)}", flush=True)
    return subprocess.call(perintah)


def main() -> None:
    langkah = asyncio.run(periksa())
    if langkah == "stamp":
        print(
            "[skema] Tabel timbangan sudah ada tetapi riwayat migrasinya belum "
            "tercatat di repo ini — skema warisan dari repo penggilingan. "
            "Mengakuinya dengan stamp, BUKAN membuat ulang.",
            flush=True,
        )
        sys.exit(jalankan(["alembic", "stamp", "head"]))
    sys.exit(jalankan(["alembic", "upgrade", "head"]))


if __name__ == "__main__":
    main()

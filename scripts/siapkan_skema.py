#!/usr/bin/env python3
"""Selaraskan riwayat migrasi dengan keadaan database yang sebenarnya.

Dijalankan entrypoint sebelum server menyala. Ada tiga keadaan, dan
membedakannya penting — dua di antaranya terlihat mirip tetapi butuh
perlakuan berlawanan:

  1. `alembic_version_timbangan` sudah berisi  → `upgrade head` biasa.
  2. Tabel versi kosong TAPI `timbangan_transaksi` sudah ada → skema ini
     dibuat sewaktu modulnya masih ikut repo penggilingan. Yang benar adalah
     `stamp` SAMPAI BATAS WARISANNYA lalu `upgrade head`: mengakui yang sudah
     ada, lalu membuat yang belum. Tanpa stamp, deploy pertama mencoba CREATE
     TABLE atas tabel yang sudah berisi data produksi lalu gagal; tanpa
     upgrade sesudahnya, migrasi 0027–0029 terlewat diam-diam dan setiap kueri
     tiket gagal karena kolom yang tak pernah dibuat (temuan QA X-03).
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

#: Revisi TERAKHIR yang dibuat oleh chain penggilingan (migrasi 0022–0026 di
#: repo produksi). Skema warisan berhenti di sini; 0027 dan sesudahnya adalah
#: milik repo ini sendiri dan harus benar-benar dijalankan.
REVISI_WARISAN = "0026_timbangan_hapus_pengawas"


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
            f"Mengakuinya dengan stamp {REVISI_WARISAN}, BUKAN membuat ulang.",
            flush=True,
        )
        # ── Stamp SAMPAI BATAS WARISANNYA, bukan sampai HEAD ──
        #
        # Yang dibuat chain penggilingan hanyalah sampai 0026. `stamp head`
        # karenanya mengaku sudah menjalankan 0027–0029 juga — padahal
        # kolom-kolomnya tak pernah dibuat. Akibatnya setiap kueri tiket gagal
        # ("pelanggan_id tidak ada") sementara /health tetap menjawab ok:
        # pos timbang menyala, tak bisa dipakai, dan tak ada satu tanda pun
        # yang menyebut sebabnya. Temuan QA X-03.
        #
        # Stamp lalu upgrade: yang warisan diakui, yang belum ada dibuat.
        kode = jalankan(["alembic", "stamp", REVISI_WARISAN])
        if kode != 0:
            sys.exit(kode)
    sys.exit(jalankan(["alembic", "upgrade", "head"]))


if __name__ == "__main__":
    main()

"""Menomori ulang tiket lama: TRX- → awalan menurut arah barang.

    DATABASE_URL=... python scripts/ganti_awalan_kode.py [--terapkan]

Sampai 4 September 2026 seluruh tiket berawalan TRX-, apa pun peristiwanya.
Selembar bukti di tangan karenanya tidak memberitahu apa-apa: orang harus
membuka sistem hanya untuk tahu apakah yang dipegangnya pembelian, pengiriman,
atau retur. Sejak awalan dibedakan per arah, tiket BARU sudah benar — skrip
ini merapikan yang lama supaya satu rekap tidak berisi dua cara menomori.

APA YANG DIUBAH

  · `timbangan_transaksi.kode`
  · `timbangan_audit.entitas_id` untuk entitas='transaksi' — kalau ini
    tertinggal, jejak audit tiket yang dinomori ulang jadi menunjuk nomor
    yang sudah tidak ada, dan justru bagian yang seharusnya bisa dipercaya
    yang rusak.

APA YANG TIDAK DIUBAH

  · Tanggal, perangkat, dan NOMOR URUT dipertahankan apa adanya bila masih
    bebas — TRX-20260901-P1-007 menjadi MSK-20260901-P1-007. Yang berpindah
    hanya awalannya, sehingga nomor lama masih bisa dikenali orang yang
    memegang kertasnya.
  · Bila nomor urut itu sudah dipakai tiket baru pada hari, perangkat, dan
    awalan yang sama, barulah nomor terdekat yang masih bebas dipakai. Ini
    bukan kerapian: `kode` bersifat unik, dan menabraknya akan menggagalkan
    seluruh penomoran ulang, bukan hanya satu baris.

CATATAN PENTING SEBELUM MENJALANKAN

Nomor tiket sudah tercetak di bukti NCR yang dipegang supplier dan pelanggan,
dan mungkin sudah dirujuk nota. Setelah skrip ini jalan, kertas lama menyebut
nomor yang tidak lagi ada di sistem. Jejaknya tetap ada di audit (nomor lama
tercatat sebagai nilai sebelum), tetapi orang yang mencari "TRX-…" di kolom
pencarian tidak akan menemukannya.
"""
import asyncio
import json
import re
import sys

from sqlalchemy import select

from app import database
from app.timbangan.models import TimbanganAudit, TimbanganTransaksi
from app.timbangan.service import AWALAN_KODE

TERAPKAN = "--terapkan" in sys.argv

#: TRX-YYYYMMDD-<perangkat>-<urutan>
POLA = re.compile(r"^TRX-(\d{8})-([A-Z0-9]{1,8})-(\d+)$")


def _kode_baru(kode: str, arah: str, terpakai: set[str]) -> str | None:
    """Nomor pengganti, atau None bila baris ini memang tidak perlu diubah."""
    cocok = POLA.match(kode)
    if not cocok:
        return None
    awalan = AWALAN_KODE.get(arah)
    if not awalan:
        return None
    hari, perangkat, urut = cocok.groups()
    lebar = len(urut)

    calon = f"{awalan}-{hari}-{perangkat}-{urut}"
    if calon not in terpakai:
        return calon
    # Nomor urutnya sudah diambil tiket baru — cari yang terdekat masih bebas.
    n = int(urut)
    while True:
        n += 1
        calon = f"{awalan}-{hari}-{perangkat}-{n:0{lebar}d}"
        if calon not in terpakai:
            return calon


async def utama():
    async with database.SessionLocal() as db:
        semua = list((await db.execute(
            select(TimbanganTransaksi).order_by(TimbanganTransaksi.id)
        )).scalars())
        terpakai = {t.kode for t in semua}

        rencana: list[tuple[TimbanganTransaksi, str]] = []
        for trx in semua:
            baru = _kode_baru(trx.kode, trx.arah, terpakai)
            if baru is None:
                continue
            terpakai.discard(trx.kode)
            terpakai.add(baru)
            rencana.append((trx, baru))

        sisa = [t for t in semua
                if t.kode.startswith("TRX-")
                and t not in {r[0] for r in rencana}]

        print(f"{len(semua)} transaksi diperiksa, "
              f"{len(rencana)} akan dinomori ulang.")
        per_awalan: dict[str, int] = {}
        for _, baru in rencana:
            per_awalan[baru[:3]] = per_awalan.get(baru[:3], 0) + 1
        for awalan, jumlah in sorted(per_awalan.items()):
            print(f"    {awalan}- : {jumlah}")
        for trx, baru in rencana[:10]:
            print(f"    contoh  {trx.kode} → {baru}   ({trx.arah})")
        if len(rencana) > 10:
            print(f"    … dan {len(rencana) - 10} lainnya")
        if sisa:
            print(f"\n{len(sisa)} tiket TRX- DIBIARKAN — bentuk nomornya tidak "
                  "dikenali atau arahnya tidak punya awalan:")
            for trx in sisa[:10]:
                print(f"    {trx.kode}  ({trx.arah})")

        if not rencana:
            return
        if not TERAPKAN:
            print("\n(uji coba — tidak ada yang ditulis)")
            return

        # Audit ditulis dengan nomor BARU sebagai entitas_id, dan nomor lama
        # disimpan sebagai nilai sebelum — supaya tiket yang dicari lewat
        # nomor barunya tetap memperlihatkan bahwa ia pernah bernomor lain.
        for trx, baru in rencana:
            lama = trx.kode
            jejak = list((await db.execute(
                select(TimbanganAudit).where(
                    TimbanganAudit.entitas == "transaksi",
                    TimbanganAudit.entitas_id == lama,
                )
            )).scalars())
            for baris in jejak:
                baris.entitas_id = baru
            trx.kode = baru
            db.add(TimbanganAudit(
                akun_id=None, akun_nama="perbaikan sistem",
                aksi="GANTI_AWALAN_KODE",
                entitas="transaksi", entitas_id=baru,
                ringkasan=f"Nomor tiket dinomori ulang menurut arah barang "
                          f"({trx.arah}); {len(jejak)} baris audit ikut "
                          f"dialihkan",
                nilai_sebelum=json.dumps({"kode": lama}, ensure_ascii=False),
                nilai_sesudah=json.dumps({"kode": baru}, ensure_ascii=False),
            ))
        await db.commit()
        print(f"\n{len(rencana)} tiket dinomori ulang dan tercatat di audit.")


asyncio.run(utama())

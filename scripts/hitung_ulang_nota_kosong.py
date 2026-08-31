"""Hitung ulang transaksi yang tertuduh karena notanya kosong. SUDAH DIJALANKAN.

Dijalankan sekali di produksi pada 31 Agustus 2026 atas 1 transaksi, setelah
perbaikan kodenya live. Disimpan sebagai catatan apa yang pernah dikerjakan
terhadap data produksi; jejak auditnya menunjuk ke sini.

    DATABASE_URL=... python scripts/hitung_ulang_nota_kosong.py [--terapkan]


Memakai `logic.hitung()` yang sama dengan aplikasinya, bukan menambal angka
lewat SQL — supaya hasilnya persis sama dengan yang akan dihitung aplikasi
bila transaksi itu dikoreksi lewat layar.

Lembar pemeriksaan yang terlanjur terbuka TIDAK ikut ditutup di sini.
Menutupnya adalah keputusan manusia menurut rancangan aplikasi ini, dan
mesin tidak boleh menyimpulkan atas nama Admin.

    --terapkan   benar-benar menulis.
"""
import asyncio
import json
import sys

from sqlalchemy import select

from app import database
from app.timbangan import logic, service, setelan
from app.timbangan.models import TimbanganAudit, TimbanganTransaksi

TERAPKAN = "--terapkan" in sys.argv


async def utama():
    async with database.SessionLocal() as db:
        semua = list((await db.execute(
            select(TimbanganTransaksi).where(
                TimbanganTransaksi.status_tiket == "SELESAI"
            ).order_by(TimbanganTransaksi.id)
        )).scalars())
        kapasitas = (await setelan.semua(db))["kapasitas_jembatan_kg"]

        berubah = []
        for trx in semua:
            await db.refresh(trx, ["muatan"])
            aturan = await service.aturan_untuk(db, trx.jenis_kode)
            baru = logic.hitung(
                aturan=aturan,
                berat_bermuatan_kg=float(trx.berat_bermuatan_kg),
                berat_kosong_kg=(float(trx.berat_kosong_kg)
                                 if trx.berat_kosong_kg is not None else None),
                muatan=service._baris_logic(trx.muatan),
                tara_lain_kg=float(trx.tara_lain_kg or 0),
                kapasitas_kg=kapasitas,
            )
            if (baru.status != trx.status_kontrol
                    or abs(baru.selisih_kg - float(trx.selisih_kg or 0)) > 0.001):
                berubah.append((trx, baru))

        if not berubah:
            print("Tidak ada transaksi yang berubah hasilnya.")
            return

        print(f"{len(berubah)} transaksi berubah:\n")
        for trx, baru in berubah:
            print(f"{trx.kode}  ({trx.jenis_kode})")
            print(f"    status  : {trx.status_kontrol} → {baru.status}")
            print(f"    selisih : {float(trx.selisih_kg or 0):+.0f} kg "
                  f"→ {baru.selisih_kg:+.0f} kg")
            print(f"    barang  : {float(trx.berat_barang_kg or 0):.0f} kg "
                  f"→ {baru.berat_barang_kg:.0f} kg")
            print(f"    catatan : {baru.keterangan}")

        if not TERAPKAN:
            print("\n(uji coba — tidak ada yang ditulis)")
            return

        for trx, baru in berubah:
            sebelum = {"status_kontrol": trx.status_kontrol,
                       "selisih_kg": float(trx.selisih_kg or 0)}
            service._terapkan_hasil(trx, baru)
            # Penanda pelaku disamakan dengan perbaikan zona waktu, supaya
            # halaman audit menandainya "sistem" dan bukan "akun dihapus".
            db.add(TimbanganAudit(
                akun_id=None, akun_nama="perbaikan sistem",
                aksi="HITUNG_ULANG_NOTA_KOSONG",
                entitas="transaksi", entitas_id=trx.kode,
                ringkasan="Dihitung ulang: nota kosong dulu dianggap nota "
                          "bernilai nol, sehingga seluruh muatan terhitung "
                          "sebagai selisih",
                nilai_sebelum=json.dumps(sebelum, ensure_ascii=False),
                nilai_sesudah=json.dumps(
                    {"status_kontrol": baru.status,
                     "selisih_kg": baru.selisih_kg}, ensure_ascii=False),
            ))
        await db.commit()
        print(f"\n{len(berubah)} transaksi dihitung ulang dan tercatat di audit.")

asyncio.run(utama())

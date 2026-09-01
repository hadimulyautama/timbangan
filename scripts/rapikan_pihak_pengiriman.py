"""Rapikan pengiriman lama yang lawan transaksinya tersimpan sebagai supplier.
SUDAH DIJALANKAN.

Dijalankan sekali di produksi pada 1 September 2026 atas 1 transaksi. Disimpan
sebagai catatan apa yang pernah dikerjakan terhadap data produksi.

    DATABASE_URL=... python scripts/rapikan_pihak_pengiriman.py [--terapkan]


Sebelum ada tabel `pelanggan`, kedua arah memakai `supplier_id`. Setelah
pemisahan, pengiriman yang masih menunjuk baris supplier akan tampil dengan
nama yang benar tetapi lewat tabel yang keliru — dan setiap kueri yang membaca
`pelanggan_id` untuk pengiriman akan menemukannya kosong.

Namanya TIDAK dicocokkan ke kontak pelanggan Kledo. Pada satu-satunya baris
yang ada, yang tertunjuk adalah "Vendor Lain-Lain" — kontak penampung, bukan
pelanggan mana pun; mencocokkannya berarti mengarang. Namanya dipindahkan ke
kolom teks bebas, sehingga catatannya tetap menyebut apa yang dulu diketik
tanpa berpura-pura menunjuk pelanggan yang tidak ada.

    --terapkan   benar-benar menulis.
"""
import asyncio
import sys

from sqlalchemy import text
from app.database import dapatkan_engine

TERAPKAN = "--terapkan" in sys.argv

async def utama():
    async with dapatkan_engine().begin() as c:
        kolom = (await c.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'timbangan_transaksi' "
            "AND column_name = 'pelanggan_id'"))).scalar()
        print("kolom pelanggan_id:", "ADA" if kolom else "TIDAK ADA")
        print("jumlah pelanggan  :", (await c.execute(text(
            "SELECT count(*) FROM pelanggan"))).scalar())
        print()

        baris = (await c.execute(text("""
            SELECT t.id, t.kode, s.nama_supplier, t.pihak_nama
            FROM timbangan_transaksi t JOIN suppliers s ON s.id = t.supplier_id
            WHERE t.arah = 'KELUAR' ORDER BY t.id
        """))).all()
        if not baris:
            print("Tidak ada pengiriman yang menunjuk baris supplier.")
            return
        print(f"{len(baris)} pengiriman perlu dirapikan:")
        for r in baris:
            print(f"   {r.kode}  supplier '{r.nama_supplier}' "
                  f"→ teks bebas (pihak_nama sekarang: {r.pihak_nama or '—'})")
        if not TERAPKAN:
            print("\n(uji coba — tidak ada yang ditulis)")
            return
        hasil = await c.execute(text("""
            UPDATE timbangan_transaksi t
               SET pihak_nama = COALESCE(t.pihak_nama, s.nama_supplier),
                   supplier_id = NULL
              FROM suppliers s
             WHERE s.id = t.supplier_id AND t.arah = 'KELUAR'
        """))
        for r in baris:
            await c.execute(text("""
                INSERT INTO timbangan_audit
                    (waktu, akun_id, akun_nama, aksi, entitas, entitas_id,
                     ringkasan, nilai_sebelum, nilai_sesudah)
                VALUES (now(), NULL, 'perbaikan sistem', 'PINDAH_PIHAK',
                        'transaksi', :kode,
                        'Pengiriman tidak lagi menunjuk baris supplier; '
                        'namanya dipindahkan ke kolom teks bebas',
                        :sebelum, :sesudah)
            """), {"kode": r.kode,
                   "sebelum": f'{{"supplier": "{r.nama_supplier}"}}',
                   "sesudah": f'{{"pihak_nama": "{r.pihak_nama or r.nama_supplier}"}}'})
        print(f"\n{hasil.rowcount} baris dirapikan dan tercatat di audit.")

asyncio.run(utama())

"""Kembalikan jam timbang yang tergeser tujuh jam. SUDAH DIJALANKAN.

Dijalankan sekali di produksi pada 31 Agustus 2026 atas 9 transaksi, setelah
perbaikan kodenya live. Disimpan bukan untuk dijalankan lagi melainkan sebagai
catatan apa yang pernah dikerjakan terhadap data produksi — jejak auditnya
menunjuk ke sini.

    DATABASE_URL=... python scripts/perbaiki_jam_wib.py [--terapkan]


Dijalankan sekali. Aman diulang: syaratnya berhenti terpenuhi begitu barisnya
sudah benar, jadi menjalankannya dua kali tidak menggeser dua kali.

    --terapkan   benar-benar menulis. Tanpa itu, hanya memperlihatkan.

Yang disentuh HANYA `timbang1_waktu` dan `timbang2_waktu` — dua kolom yang
diisi dari isian operator. Jam sistem, jam cetak, dan jejak audit tidak
pernah lewat jalur itu dan karenanya sudah benar; justru jam sistem yang
dipakai di sini sebagai pembanding untuk mengenali baris yang tergeser.
"""
import asyncio
import sys

from sqlalchemy import text
from app.database import dapatkan_engine

TERAPKAN = "--terapkan" in sys.argv

# Baris yang tergeser: jam yang tercatat mendahului jam sistem lebih dari
# enam jam. Kemunduran yang sah (petugas mencatat terlambat) selalu
# BERTANDA NEGATIF — jam tercatat lebih AWAL dari jam sistem — jadi tidak
# mungkin ikut tersapu syarat ini.
SYARAT = """
    timbang1_waktu IS NOT NULL
    AND timbang1_waktu > timbang1_waktu_sistem + interval '6 hours'
"""


async def utama():
    async with dapatkan_engine().begin() as c:
        baris = (await c.execute(text(f"""
            SELECT id, kode, tanggal,
                   timbang1_waktu AT TIME ZONE 'Asia/Jakarta' AS t1,
                   timbang2_waktu AT TIME ZONE 'Asia/Jakarta' AS t2,
                   (timbang1_waktu - interval '7 hours')
                       AT TIME ZONE 'Asia/Jakarta' AS t1_baru,
                   (timbang2_waktu - interval '7 hours')
                       AT TIME ZONE 'Asia/Jakarta' AS t2_baru,
                   (COALESCE(timbang2_waktu, timbang1_waktu) - interval '7 hours')
                       AT TIME ZONE 'Asia/Jakarta' AS tgl_baru
            FROM timbangan_transaksi WHERE {SYARAT} ORDER BY id
        """))).all()

        if not baris:
            print("Tidak ada baris yang tergeser. Tidak ada yang diubah.")
            return

        print(f"{len(baris)} baris tergeser:\n")
        print(f"{'KODE':26}{'TIMBANG 1':>34}{'TIMBANG 2':>34}  TANGGAL")
        ganti_tanggal = 0
        for b in baris:
            t2 = f"{str(b.t2)[:16]} → {str(b.t2_baru)[:16]}" if b.t2 else "—"
            tgl = str(b.tgl_baru)[:10]
            tanda = ""
            if str(b.tanggal) != tgl:
                tanda = f"  {b.tanggal} → {tgl}"
                ganti_tanggal += 1
            print(f"{b.kode:26}{str(b.t1)[:16]} → {str(b.t1_baru)[:16]:>16}"
                  f"{t2:>34}{tanda}")
        print(f"\nTanggal transaksi berubah pada {ganti_tanggal} baris.")

        if not TERAPKAN:
            print("\n(uji coba — tidak ada yang ditulis; ulangi dengan --terapkan)")
            return

        hasil = await c.execute(text(f"""
            UPDATE timbangan_transaksi
               SET timbang1_waktu = timbang1_waktu - interval '7 hours',
                   timbang2_waktu = timbang2_waktu - interval '7 hours',
                   tanggal = ((COALESCE(timbang2_waktu, timbang1_waktu)
                               - interval '7 hours')
                              AT TIME ZONE 'Asia/Jakarta')::date
             WHERE {SYARAT}
        """))
        # Jejak audit tetap ditulis meski pelakunya bukan seorang pengguna.
        # Aplikasi ini menjanjikan setiap perubahan angka meninggalkan jejak;
        # perbaikan massal justru yang paling tidak boleh diam-diam.
        for b in baris:
            await c.execute(text("""
                INSERT INTO timbangan_audit
                    (waktu, akun_id, akun_nama, aksi, entitas, entitas_id,
                     ringkasan, nilai_sebelum, nilai_sesudah)
                VALUES (now(), NULL, 'perbaikan sistem', 'KOREKSI_ZONA_WAKTU',
                        'transaksi', :kode,
                        'Jam timbang dikembalikan 7 jam — dulu tersimpan '
                        'sebagai UTC padahal yang diketik WIB',
                        :sebelum, :sesudah)
            """), {
                "kode": b.kode,
                "sebelum": f'{{"timbang1_waktu": "{b.t1}", "timbang2_waktu": "{b.t2}"}}',
                "sesudah": f'{{"timbang1_waktu": "{b.t1_baru}", "timbang2_waktu": "{b.t2_baru}"}}',
            })
        print(f"\n{hasil.rowcount} baris diperbaiki, dan tercatat di jejak audit.")

asyncio.run(utama())

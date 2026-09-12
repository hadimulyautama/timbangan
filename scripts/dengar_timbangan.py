"""Dengarkan indikator timbangan dan tampilkan apa adanya.

Dipakai SEKALI di awal, untuk mengetahui bentuk kiriman indikator saat tombol
PRINT ditekan. Tanpa itu, penguraiannya cuma tebakan — dan angka berat adalah
hal terakhir yang boleh ditebak.

Indikator pos timbang HMU: BALANZA HERCULES-TS-BX1-20000, kapasitas 20.000 kg,
e = d = 10 kg, kelas III. Disetel mengirim hanya saat diminta, jadi tidak ada
yang muncul di layar sampai PRINT ditekan — sunyi itu normal.

Sengaja TANPA pustaka luar: hanya `stty` dan pustaka standar, supaya bisa
dijalankan apa adanya di MacBook maupun kelak di Raspberry Pi.

    python3 scripts/dengar_timbangan.py                 # cari port, baud 9600
    python3 scripts/dengar_timbangan.py --baud 4800
    python3 scripts/dengar_timbangan.py --port /dev/cu.usbserial-110
    python3 scripts/dengar_timbangan.py --simpan tangkapan.bin

Baud yang lazim pada indikator seperti ini: 9600, lalu 4800, 2400, 19200.
Bila PRINT ditekan tetapi yang muncul hanya sampah (mis. `FF FE FF`), baudnya
salah — coba angka berikutnya.
"""
from __future__ import annotations

import argparse
import glob
import subprocess
import sys
import time
from datetime import datetime

#: Nama port berbeda di macOS dan Linux; keduanya dicoba agar skrip yang sama
#: bisa dipakai di laptop maupun di Pi.
POLA_PORT = (
    "/dev/cu.usbserial*", "/dev/cu.usbmodem*", "/dev/cu.SLAB*", "/dev/cu.wchusb*",
    "/dev/ttyUSB*", "/dev/ttyACM*",
)


def cari_port() -> list[str]:
    ada: list[str] = []
    for pola in POLA_PORT:
        ada.extend(sorted(glob.glob(pola)))
    return ada


def siapkan(port: str, baud: int) -> None:
    """Setel port: 8 data bit, tanpa paritas, 1 stop bit, mentah."""
    bendera = "-f" if sys.platform == "darwin" else "-F"
    subprocess.run(
        ["stty", bendera, port, str(baud), "cs8", "-cstopb", "-parenb",
         "raw", "-echo", "-ixon", "-crtscts"],
        check=True,
    )


#: Jeda saat tak ada data, dan berapa kali menunggu sebelum menyerah.
#: 0,05 detik cukup pendek untuk tak melewatkan kiriman indikator, cukup
#: panjang untuk membuat gelung ini hampir tak memakai prosesor.
JEDA = 0.05
BATAS_KOSONG = 600            # ≈30 detik


def tampilkan(potongan: bytes) -> None:
    heks = " ".join(f"{b:02X}" for b in potongan)
    # Byte yang tak tercetak diganti titik supaya barisnya tetap sejajar.
    teks = "".join(chr(b) if 32 <= b < 127 else "." for b in potongan)
    jam = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{jam}] {len(potongan):3d} byte")
    print(f"           heks : {heks}")
    print(f"           teks : {teks}")
    print()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", help="Bila kosong, port pertama yang ditemukan.")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--simpan", help="Simpan byte mentahnya ke berkas ini.")
    a = p.parse_args()

    port = a.port
    if not port:
        ada = cari_port()
        if not ada:
            print("Tidak ada port serial yang terpasang.\n"
                  "Colokkan kabel konverter USB-nya, lalu ulangi.\n"
                  "Bila sudah tercolok tetapi tetap tidak terbaca, "
                  "kemungkinan besar pemacu (driver) chip-nya belum terpasang.",
                  file=sys.stderr)
            return 1
        port = ada[0]
        if len(ada) > 1:
            print(f"Beberapa port ditemukan: {', '.join(ada)}", file=sys.stderr)
            print(f"Memakai {port}. Pakai --port untuk memilih yang lain.\n",
                  file=sys.stderr)

    try:
        siapkan(port, a.baud)
    except subprocess.CalledProcessError:
        print(f"Gagal menyetel {port}. Pastikan tidak ada program lain "
              "yang sedang memakainya.", file=sys.stderr)
        return 1

    print(f"Mendengarkan {port} pada {a.baud} baud, 8N1.")
    print("Sekarang tekan tombol PRINT di indikator. Ctrl+C untuk berhenti.\n")

    simpan = open(a.simpan, "wb") if a.simpan else None
    jumlah = 0
    try:
        # buffering=0 supaya byte tampil begitu tiba, bukan menunggu penuh.
        with open(port, "rb", buffering=0) as serial:
            kosong = 0
            while True:
                potongan = serial.read(256)
                if not potongan:
                    # ── Jangan berputar sekencang-kencangnya ──
                    #
                    # Bila kabel USB dicabut, `read` kembali kosong SEKETIKA,
                    # terus-menerus — gelung ini lalu memakan satu inti
                    # prosesor penuh sampai seseorang menyadarinya. Di laptop
                    # itu terdengar dari kipasnya; di komputer pos timbang
                    # yang ditinggal menyala, tidak. Temuan QA T-28.
                    kosong += 1
                    if kosong >= BATAS_KOSONG:
                        print(f"\nTidak ada data selama {BATAS_KOSONG * JEDA:.0f} "
                              "detik. Kabelnya mungkin lepas — berhenti.")
                        break
                    time.sleep(JEDA)
                    continue
                kosong = 0
                jumlah += len(potongan)
                tampilkan(potongan)
                if simpan:
                    simpan.write(potongan)
                    simpan.flush()
    except KeyboardInterrupt:
        print(f"\nBerhenti. Total {jumlah} byte diterima.")
        if jumlah == 0:
            print("Tidak ada yang masuk sama sekali. Kemungkinan, berurutan "
                  "dari yang paling sering:\n"
                  "  1. baud salah — coba --baud 4800, lalu 2400, lalu 19200;\n"
                  "  2. indikator belum disetel mengirim ke port serialnya;\n"
                  "  3. kabelnya lurus padahal butuh null-modem (TX/RX tertukar).")
    finally:
        if simpan:
            simpan.close()
            print(f"Tersimpan di {a.simpan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

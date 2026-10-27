"""Isi bukti timbang — baris angka yang sama untuk semua bentuk cetakan.

Dipisahkan dari `pdf.py` sejak struk bisa keluar lewat dua jalan: digambar
sebagai PDF, dan dikirim sebagai perintah ePOS-Print ke printer thermal.
Keduanya HARUS menampilkan angka yang sama persis — kertas dari jalan yang
berbeda tetap kertas yang sama di mata pengirim barang. Karena itu isinya
disusun di sini sekali, dan hanya tata letaknya yang berbeda di masing-masing.

Modul ini sengaja tidak mengimpor reportlab: jalur ePOS tidak menggambar
apa pun, dan tidak pantas menyeret pustaka gambar hanya untuk membaca angka.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.timbangan import format as fmt


@dataclass
class Baris:
    label: str
    nilai: str
    jam: str = ""


def baris_angka(trx, arah_masuk: bool) -> list[Baris]:
    # Partai kecil: yang dicetak adalah RINCIANNYA, bukan satu angka bruto.
    # Orang yang menjual 60 kg dalam empat kali timbang membawa pulang kertas
    # yang bisa ia cocokkan sendiri; total tanpa rincian tak bisa diperiksa
    # siapa pun setelah barangnya tercampur di gudang.
    if getattr(trx, "partai", False):
        b = [Baris(f"Timbang {p.urutan}", f"{fmt.angka(p.berat_kg)} kg",
                   fmt.jam(p.waktu))
             for p in trx.penimbangan]
        b.append(Baris(f"Jumlah {len(trx.penimbangan)} kali timbang",
                       f"{fmt.angka(trx.netto_timbangan_kg)} kg"))
        if trx.jumlah_karung:
            per = float(trx.total_tara_kg or 0) / trx.jumlah_karung
            b.append(Baris(
                f"Tara karung  {trx.jumlah_karung} × {fmt.angka(per, 3)} kg",
                f"- {fmt.angka(trx.total_tara_kg, 2)} kg"))
        if trx.tara_lain_kg:
            b.append(Baris("Tara lain", f"- {fmt.angka(trx.tara_lain_kg, 2)} kg"))
        return b

    b = [Baris("Bruto — truk bermuatan",
               f"{fmt.angka(trx.berat_bermuatan_kg)} kg",
               fmt.jam(trx.timbang1_waktu if arah_masuk else trx.timbang2_waktu))]
    if trx.berat_kosong_kg is not None:
        b.append(Baris(
            f"Tara truk — {'setelah bongkar' if arah_masuk else 'sebelum muat'}",
            f"{fmt.angka(trx.berat_kosong_kg)} kg",
            fmt.jam(trx.timbang2_waktu if arah_masuk else trx.timbang1_waktu)))
    b.append(Baris("Netto timbangan", f"{fmt.angka(trx.netto_timbangan_kg)} kg"))
    if trx.jumlah_karung and (getattr(trx, 'pengiriman_snapshot', None) or getattr(trx, 'arah', None) == 'TRANSFER'):
        from decimal import Decimal
        kemasan = Decimal(str(trx.total_tara_kg or 0)) - Decimal(str(trx.tara_lain_kg or 0))
        b.append(Baris(f"Tara kemasan {trx.jumlah_karung} karung", f"- {fmt.angka(kemasan, 3)} kg"))
    elif trx.jumlah_karung:
        per = float(trx.total_tara_kg or 0) / trx.jumlah_karung
        b.append(Baris(
            f"Tara karung  {trx.jumlah_karung} × {fmt.angka(per, 3)} kg",
            f"- {fmt.angka(trx.total_tara_kg, 2)} kg"))
    if trx.tara_lain_kg:
        b.append(Baris("Tara lain", f"- {fmt.angka(trx.tara_lain_kg, 2)} kg"))
    return b

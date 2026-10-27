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
        b.extend(_baris_tara(trx))
        return b

    b = [Baris("Bruto — truk bermuatan",
               f"{fmt.angka(trx.berat_bermuatan_kg)} kg",
               fmt.jam(trx.timbang1_waktu if arah_masuk else trx.timbang2_waktu))]
    if trx.berat_kosong_kg is not None:
        kosong = Baris(
            f"Tara truk — {'setelah bongkar' if arah_masuk else 'sebelum muat'}",
            f"{fmt.angka(trx.berat_kosong_kg)} kg",
            fmt.jam(trx.timbang2_waktu if arah_masuk else trx.timbang1_waktu))
        # Urutan bacaan nyata: pengiriman/retur keluar kosong dahulu.
        b.insert(len(b) if arah_masuk else 0, kosong)
    b.append(Baris("Netto timbangan", f"{fmt.angka(trx.netto_timbangan_kg)} kg"))
    b.extend(_baris_tara(trx))
    return b


def _baris_tara(trx):
    """Pisahkan komponen total tersimpan; jangan tampilkan tara lain dua kali."""
    from decimal import Decimal
    if getattr(trx,'arah',None) in ('RETUR_MASUK','RETUR_KELUAR'):
        return []  # layanan retur tidak memotong tara, termasuk input lama
    total=getattr(trx,'total_tara_kg',None)
    lain=getattr(trx,'tara_lain_kg',None)
    if total is None:return [Baris('Tara kemasan / pengurang','Belum tersedia')]
    kemasan=Decimal(str(total))-Decimal(str(lain or 0))
    b=[]
    if trx.jumlah_karung or kemasan:
        b.append(Baris(f'Tara kemasan {trx.jumlah_karung or 0} karung',f'- {fmt.angka(kemasan,3)} kg'))
    if lain:b.append(Baris('Tara lain',f'- {fmt.angka(lain,2)} kg'))
    return b

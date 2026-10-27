"""Struk 80 mm sebagai perintah ePOS-Print, dikirim langsung ke printer.

**Mengapa ada dua jalur cetak.** `pdf.py` menggambar struk sebagai berkas
yang harus dibuka, lalu dicetak lewat dialog berbagi ponsel — tiga ketukan,
dan di iOS kadang PDF-nya memenuhi layar tanpa tombol kembali. Jalur ini
menggantinya dengan satu ketukan: perintahnya disusun di sini, browser hanya
meneruskannya ke printer di jaringan yang sama. PDF tetap ada, dan tetap
diperlukan — untuk dibagikan lewat WhatsApp, dan untuk printer mana pun yang
bukan Epson.

**Mengapa disusun di server, bukan di JavaScript.** Isi bukti timbang adalah
dokumen perusahaan: angkanya dipakai membayar orang. Menyusunnya di perangkat
berarti tiap ponsel memegang salinan aturannya sendiri, dan versi lama yang
tersimpan di cache akan diam-diam mencetak tata letak yang sudah dicabut.
Di sini ia satu berkas, punya uji, dan berubah bersama seluruh aplikasi.

**Batasan alat.** Font A pada kertas 80 mm memuat 48 kolom; huruf yang
dilebarkan (`dw`) memuat 24. Semua baris di bawah dipotong pada batas itu,
karena teks yang meluber tidak dibungkus melainkan berpindah baris di tengah
kata — dan pada struk, baris yang patah terbaca sebagai angka yang salah.
"""
from __future__ import annotations

import unicodedata
from xml.sax.saxutils import escape

from app.timbangan import format as fmt
from app.timbangan import logic
from app.timbangan.bukti import baris_angka
from app.timbangan.pengiriman import rincian_bukti

#: Font A, kertas 80 mm, kepala cetak 203 dpi.
KOLOM = 48
#: Kolom yang tersisa bila huruf dilebarkan dua kali.
KOLOM_LEBAR = 24

_XMLNS = "http://www.epson-pos.com/schemas/2011/03/epos-print"

#: Pengganti untuk huruf yang tidak ada di code page bawaan printer.
#: Ditulis eksplisit karena hasil `unicodedata` untuk ketiganya bukan yang
#: kita mau: "×" jadi kosong, bukan "x"; "—" jadi kosong, bukan "-".
_GANTI = {"×": "x", "—": "-", "–": "-", "·": "-", "…": "...",
          "“": '"', "”": '"', "‘": "'", "’": "'"}


def _polos(teks: str) -> str:
    """Turunkan teks ke ASCII yang pasti ada di printer.

    Nama pengirim bisa berisi apa saja — huruf beraksen dari salin-tempel,
    tanda kutip melengkung dari aplikasi catatan. Printer thermal memakai
    code page satu byte; huruf yang tidak dikenalnya keluar sebagai simbol
    acak, dan satu simbol acak di tengah nama membuat bukti terlihat palsu.
    """
    for asal, ganti in _GANTI.items():
        teks = teks.replace(asal, ganti)
    rata = unicodedata.normalize("NFKD", teks)
    return "".join(c for c in rata if 32 <= ord(c) < 127)


def _potong(teks: str, lebar: int) -> str:
    teks = _polos(teks)
    return teks if len(teks) <= lebar else teks[: lebar - 1] + "."


def _sisi(kiri: str, kanan: str, lebar: int = KOLOM) -> str:
    """Label di kiri, angka rata kanan, titik-titik di antaranya.

    Titik penyambung bukan hiasan: pada baris yang panjang, mata kehilangan
    jejak antara label dan angkanya, dan pengirim barang membaca struk ini
    sambil berdiri di samping truk.
    """
    import textwrap
    kanan = _polos(kanan)
    kiri = _polos(kiri)
    if len(kiri)+len(kanan)+2 > lebar:
        return '\n'.join(textwrap.wrap(kiri,lebar)+textwrap.wrap(kanan,lebar))
    antara = lebar - len(kiri) - len(kanan)
    return kiri + (" " if antara <= 1 else " " + "." * (antara - 2) + " ") + kanan


def _tengah(teks: str, lebar: int) -> str:
    """Teks di tengah sebuah KOLOM selebar `lebar`, berspasi di kedua sisi.

    Dipakai hanya untuk menyusun dua kolom berdampingan. Untuk baris yang
    memang berdiri sendiri, pakai `align="center"` milik printer — menengahkan
    di sini LALU menyuruh printer menengahkannya lagi menggeser teksnya ke
    kanan, karena spasi yang kita tambahkan ikut terhitung sebagai isi baris.
    """
    teks = _potong(teks, lebar)
    kiri = (lebar - len(teks)) // 2
    return " " * kiri + teks + " " * (lebar - kiri - len(teks))


def _teks(isi: str, *, align: str = "left", em: bool = False,
          dw: bool = False) -> str:
    """Satu baris cetak, dengan SELURUH gaya hurufnya ditulis apa adanya.

    Perhatikan bahwa tidak ada nilai yang boleh dihilangkan karena "toh
    bawaannya begitu". Di ePOS-Print, `dw` dan `em` bukan sifat satu baris
    melainkan SAKLAR pada alat: sekali dinyalakan ia menetap sampai ada yang
    mematikannya. Pernah terjadi — nama perusahaan dicetak lebar, lalu seluruh
    struk di bawahnya ikut lebar, dan kertas 48 kolom hanya memuat 24. Setiap
    barisnya patah di tengah kata, termasuk baris angka.

    Menuliskan status lengkap di tiap baris membuat kekeliruan itu mustahil
    terulang: tidak ada baris yang mewarisi apa pun dari baris sebelumnya.
    """
    kata = {True: "true", False: "false"}
    return (f'<text align="{align}" em="{kata[em]}" dw="{kata[dw]}"'
            f' dh="{kata[dw]}">{escape(isi)}&#10;</text>')


def _bungkus(perintah: list[str]) -> str:
    isi = "".join(perintah)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<s:Body><epos-print xmlns="{_XMLNS}">{isi}</epos-print>'
        "</s:Body></s:Envelope>"
    )


def struk_timbang(*, trx, aturan, pihak: str, petugas: str, muatan,
                  perusahaan: str, alamat: str, telepon: str,
                  arah_masuk: bool, tampilkan_selisih: bool,
                  cetakan_ke: int = 1) -> str:
    """Perintah cetak untuk satu bukti timbang, siap dikirim ke printer.

    Tandatangannya sengaja sama persis dengan `pdf.bukti_thermal`, sehingga
    rute cetak menyiapkan SATU kamus data lalu memilih jalurnya — bukan dua
    jalan pengumpulan data yang bisa berbeda diam-diam.
    """
    p: list[str] = []

    # Kepala. Nama perusahaan dilebarkan hanya bila memang muat; nama yang
    # terpotong lebih buruk daripada nama berukuran biasa.
    nama = _polos(perusahaan)
    if len(nama) <= KOLOM_LEBAR:
        p.append(_teks(nama, align="center", em=True, dw=True))
    else:
        p.append(_teks(_potong(nama, KOLOM), align="center", em=True))
    p.append(_teks(_potong(alamat, KOLOM), align="center"))
    p.append(_teks(_potong(telepon, KOLOM), align="center"))
    p.append(_teks("-" * KOLOM, align="left"))
    p.append(_teks("B U K T I   T I M B A N G", align="center", em=True))
    # ── Lembar kedua dan seterusnya mengaku sebagai lembar kedua ──
    #
    # Sampai 11 September 2026 cetak ulang identik dengan cetakan pertama, dan
    # dua lembar untuk satu truk tak bisa dibedakan. Begitu di antara keduanya
    # ada koreksi, keduanya memuat angka berbeda — dan yang memegangnya orang
    # di luar pabrik. Temuan QA T-11.
    #
    # Tandanya di ATAS nomor tiket, bukan di kaki: yang membacanya sering
    # hanya melihat kepala kertas.
    if cetakan_ke > 1:
        p.append(_teks(f"CETAKAN ULANG ke-{cetakan_ke}", align="center", em=True))
    revisi = int(getattr(trx, "jumlah_revisi", 0) or 0)
    if revisi:
        p.append(_teks(f"Revisi {revisi}", align="center"))
    p.append(_teks("-" * KOLOM, align="left"))

    p.append(_teks(_sisi("No.", trx.kode)))
    p.append(_teks(_sisi("Tanggal", trx.tanggal.strftime("%d-%m-%Y"))))
    p.append(_teks(_sisi("Pengirim" if arah_masuk else "Pihak", pihak or "-")))
    # Partai kecil datang dijinjing, bukan diangkut: kolom kendaraan dan sopir
    # tidak pernah terisi, dan mencetak "Nomor polisi -" membuat pembacanya
    # mengira ada data yang hilang.
    if not getattr(trx, "partai", False):
        p.append(_teks(_sisi("Nomor polisi", trx.nomor_polisi or "-")))
        if trx.nama_sopir:
            p.append(_teks(_sisi("Sopir", trx.nama_sopir)))
    p.append(_teks(_sisi("Barang", aturan.nama)))
    if muatan and muatan[0].nomor_acuan:
        p.append(_teks(_sisi("Nota" if arah_masuk else "Surat jalan",
                             muatan[0].nomor_acuan)))
    p.append(_teks("-" * KOLOM))

    for b in baris_angka(trx, arah_masuk):
        p.append(_teks(_sisi(b.label + (f" {b.jam}" if b.jam else ""), b.nilai)))

    p.append(_teks("=" * KOLOM))
    p.append(_teks(_sisi("BERAT BARANG",
                         f"{fmt.angka(trx.berat_barang_kg)} kg"), em=True))
    p.append(_teks("=" * KOLOM))

    if tampilkan_selisih:
        p.append(_teks(_sisi("Menurut dokumen",
                             f"{fmt.angka(trx.berat_acuan_kg)} kg")))
        p.append(_teks(_sisi("Selisih", fmt.kg_tanda(trx.selisih_kg, 2))))
        p.append(_teks("-" * KOLOM))

    if trx.catatan:
        import textwrap
        for line in textwrap.wrap(_polos(trx.catatan), KOLOM):
            p.append(_teks(line))
        p.append(_teks("-" * KOLOM))

    # Tanda tangan. Dua kolom berdampingan seperti pada PDF; garisnya dibuat
    # dari garis bawah supaya tetap ada ruang menulis di kertas 80 mm.
    #
    import textwrap
    for baris in rincian_bukti(trx, berat=tampilkan_selisih):
        for r in textwrap.wrap(baris, KOLOM):
            p.append(_teks(r))

    # Siapa yang menandatangani kolom kedua tergantung siapa yang datang.
    # Pada truk itu sopir — dialah yang menyaksikan jarum timbangan. Pada
    # partai kecil tidak ada sopir: petani membawa barangnya sendiri, dan
    # kolom "Sopir (saksi)" yang kosong membuat bukti tampak belum selesai.
    partai = getattr(trx, "partai", False)
    saksi_label = ("Pengirim" if arah_masuk else "Pihak") if partai \
        else "Sopir (saksi)"
    saksi_nama = pihak if partai else (trx.nama_sopir or "")

    lebar_ttd = KOLOM // 2 - 2
    p.append("<feed line=\"2\"/>")
    p.append(_teks(_tengah("Petugas pencetak", KOLOM // 2)
                   + _tengah(saksi_label, KOLOM // 2)))
    # 203dpi: ceil(20mm * 203/25.4) = 160 dots, di luar label/nama.
    p.append('<feed unit="160"/>')
    p.append(_teks(_tengah("_" * lebar_ttd, KOLOM // 2)
                   + _tengah("_" * lebar_ttd, KOLOM // 2)))
    # Nama panjang dibungkus di kolomnya sendiri, bukan dipangkas.
    kiri = textwrap.wrap(_polos(petugas or ''), lebar_ttd) or ['']
    kanan = textwrap.wrap(_polos(saksi_nama), lebar_ttd) or ['']
    for n in range(max(len(kiri),len(kanan))):
        p.append(_teks(_tengah(kiri[n] if n<len(kiri) else '', KOLOM//2)
                       + _tengah(kanan[n] if n<len(kanan) else '', KOLOM//2)))
    p.append("<feed line=\"1\"/>")
    p.append(_teks("Ditandatangani kedua pihak sebagai bukti", align="center"))

    p.append("<feed line=\"1\"/>")
    p.append('<cut type="feed"/>')
    return _bungkus(p)


def struk_uji(*, perusahaan: str) -> str:
    """Cetakan pendek untuk memastikan printer terjangkau dan kertasnya benar.

    Sengaja memuat penggaris 48 kolom: bila baris itu patah jadi dua, kertas
    yang terpasang bukan 80 mm — dan itulah salah satu dari dua kekeliruan
    pemasangan yang paling sering terjadi (yang satunya alamat printer salah).
    """
    p = [
        _teks(_potong(perusahaan, KOLOM_LEBAR), align="center",
              em=True, dw=True),
        _teks("Pos Timbang - uji printer", align="center"),
        _teks("-" * KOLOM, align="left"),
        _teks("123456789012345678901234567890123456789012345678"),
        _teks(_sisi("Lebar kertas", "80 mm / 48 kolom")),
        _teks(_sisi("Contoh berat", "12.345 kg"), em=True),
        _teks("-" * KOLOM),
        _teks("Bila penggaris di atas muat satu baris,", align="center"),
        _teks("printer sudah siap dipakai.", align="center"),
        '<feed line="1"/>',
        '<cut type="feed"/>',
    ]
    return _bungkus(p)


def tampilkan_selisih(trx, aturan) -> bool:
    """Bolehkah angka selisih ikut tercetak pada struk transaksi ini.

    Dua syarat, dan keduanya pernah dilanggar.

    `rahasia` menahan hasil kontrol gabah agar tidak sampai ke pengirim —
    SOP butir 8. Syarat kedua dulu terlewat: sebagian komoditas memang tidak
    punya dokumen sama sekali (jasa timbang, transfer internal), dan nota bisa
    saja belum diisi. Struknya lalu mencetak "Menurut dokumen 0 kg - Selisih
    0,00 kg" — angka yang terbaca seperti pernyataan, padahal tidak ada
    dokumen yang menyatakannya.

    Ditempatkan di sini, bukan di rute, supaya jalur PDF dan jalur ePOS
    memanggil satu keputusan yang sama — bukan dua salinan syarat yang bisa
    berbeda diam-diam setelah SOP direvisi.
    """
    ada_acuan = (aturan.acuan != logic.ACUAN_TIDAK_ADA
                 and float(trx.berat_acuan_kg or 0) > 0)
    return (not aturan.rahasia) and ada_acuan

"""Uji perintah cetak ePOS — struk yang keluar dari printer pos timbang.

Struk ini tidak pernah dilihat siapa pun sebelum tercetak: tidak ada pratinjau,
tidak ada berkas yang bisa dibuka dulu. Kertasnya keluar, lalu ditandatangani
pengirim barang. Karena itu yang diuji di sini bukan "XML-nya sah", melainkan
hal-hal yang membuat kertas itu bisa dipercaya: lebarnya, angkanya, dan apa
yang TIDAK boleh ikut tercetak.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from xml.etree import ElementTree

from app.timbangan import epos, logic


def _trx(**ubah):
    dasar = dict(
        kode="TRX-260902-P1-014",
        tanggal=date(2026, 9, 2),
        nomor_polisi="AD 1234 XY",
        nama_sopir="Suparno",
        catatan="",
        partai=False,
        penimbangan=[],
        berat_bermuatan_kg=12000,
        berat_kosong_kg=3760,
        netto_timbangan_kg=8240,
        berat_barang_kg=8240,
        berat_acuan_kg=8250,
        selisih_kg=-10,
        jumlah_karung=0,
        total_tara_kg=0,
        tara_lain_kg=0,
        timbang1_waktu=datetime(2026, 9, 2, 2, 15, tzinfo=timezone.utc),
        timbang2_waktu=datetime(2026, 9, 2, 3, 40, tzinfo=timezone.utc),
    )
    dasar.update(ubah)
    return SimpleNamespace(**dasar)


def _aturan(**ubah):
    dasar = dict(nama="Gabah kering panen", acuan=logic.ACUAN_NOTA, rahasia=False)
    dasar.update(ubah)
    return SimpleNamespace(**dasar)


def _cetak(trx=None, aturan=None, **ubah):
    isi = dict(
        trx=trx or _trx(), aturan=aturan or _aturan(),
        pihak="Karyo Tani", petugas="Rusdi Hartono", muatan=[],
        perusahaan="PT Hadi Mulya Utama", alamat="Masaran, Kab. Sragen",
        telepon="+62 851-7416-7950", arah_masuk=True, tampilkan_selisih=False,
    )
    isi.update(ubah)
    return epos.struk_timbang(**isi)


_RUANG = "{http://www.epson-pos.com/schemas/2011/03/epos-print}"


def _baris(xml: str) -> list[str]:
    """Teks yang benar-benar tercetak, baris demi baris."""
    akar = ElementTree.fromstring(xml)
    return [(el.text or "").rstrip("\n") for el in akar.iter(_RUANG + "text")]


def _baris_berlebar(xml: str) -> list[tuple[str, int]]:
    """Tiap baris beserta lebar kertas yang tersedia baginya.

    Huruf yang dilebarkan memakan dua kolom, jadi baris `dw` hanya punya
    separuh tempat — dan itu justru baris terpenting: nama perusahaan.
    """
    akar = ElementTree.fromstring(xml)
    return [((el.text or "").rstrip("\n"),
             epos.KOLOM_LEBAR if el.get("dw") == "true" else epos.KOLOM)
            for el in akar.iter(_RUANG + "text")]


# ─────────────── Lebar kertas ───────────────

def test_tidak_ada_baris_yang_melebihi_lebar_kertas():
    """Baris yang meluber tidak dibungkus printer — ia patah di tengah kata.

    Pada struk, baris yang patah terbaca sebagai angka yang salah: "8.240 kg"
    yang jatuh ke baris berikutnya menjadi "8.2" lalu "40 kg".
    """
    xml = _cetak(trx=_trx(
        nomor_polisi="AD 1234 XYZ", nama_sopir="Bambang Setyo Wibowo Nugroho",
    ), aturan=_aturan(nama="Beras premium kemasan karung 50 kg"),
        pihak="Koperasi Tani Makmur Sejahtera Masaran Sragen")
    for baris, muat in _baris_berlebar(xml):
        assert len(baris) <= muat, f"{len(baris)} > {muat} kolom: {baris!r}"


def test_nama_perusahaan_panjang_turun_ke_ukuran_biasa():
    """Huruf lebar hanya memuat separuh kolom; nama terpotong lebih buruk."""
    panjang = "PT Hadi Mulya Utama Sejahtera Abadi"
    xml = _cetak(perusahaan=panjang)
    assert 'dw="true"' not in xml
    assert panjang in _baris(xml)[0]

    xml = _cetak(perusahaan="PT Hadi Mulya Utama")
    assert 'dw="true"' in xml
    assert _baris(xml)[0] == "PT Hadi Mulya Utama"


# ─────────────── Kerahasiaan ───────────────

def test_selisih_tidak_tercetak_untuk_komoditas_rahasia():
    """SOP butir 8: hasil kontrol gabah tidak sampai ke pengirim."""
    assert epos.tampilkan_selisih(_trx(), _aturan(rahasia=True)) is False
    teks = "\n".join(_baris(_cetak(tampilkan_selisih=False)))
    assert "Selisih" not in teks
    assert "Menurut dokumen" not in teks


def test_selisih_tidak_tercetak_bila_tidak_ada_dokumen_pembanding():
    """Tanpa acuan, "Selisih 0,00 kg" terbaca sebagai pernyataan — padahal
    tidak ada dokumen yang menyatakannya."""
    assert epos.tampilkan_selisih(
        _trx(), _aturan(acuan=logic.ACUAN_TIDAK_ADA)) is False
    assert epos.tampilkan_selisih(_trx(berat_acuan_kg=0), _aturan()) is False
    assert epos.tampilkan_selisih(_trx(), _aturan()) is True


def test_selisih_tercetak_lengkap_dengan_tandanya():
    teks = "\n".join(_baris(_cetak(tampilkan_selisih=True)))
    assert "Menurut dokumen" in teks
    assert "-10,00 kg" in teks


# ─────────────── Partai kecil ───────────────

def test_partai_kecil_mencetak_rincian_bukan_hanya_jumlah():
    """Penjual 60 kg dalam empat kali timbang harus bisa mencocokkan sendiri."""
    trx = _trx(
        partai=True, nomor_polisi=None, nama_sopir=None,
        berat_bermuatan_kg=None, berat_kosong_kg=None,
        netto_timbangan_kg=60, berat_barang_kg=60,
        penimbangan=[
            SimpleNamespace(urutan=i, berat_kg=b,
                            waktu=datetime(2026, 9, 2, 2, i, tzinfo=timezone.utc))
            for i, b in enumerate([12, 18, 22, 8], start=1)
        ],
    )
    teks = "\n".join(_baris(_cetak(trx=trx)))
    for angka in ("12 kg", "18 kg", "22 kg", "8 kg"):
        assert angka in teks
    assert "Jumlah 4 kali timbang" in teks


def test_partai_kecil_tidak_menyebut_kendaraan():
    """Barangnya dijinjing. "Nomor polisi -" membuat pembacanya mengira ada
    data yang hilang."""
    trx = _trx(partai=True, nomor_polisi=None, nama_sopir=None,
               penimbangan=[SimpleNamespace(
                   urutan=1, berat_kg=60,
                   waktu=datetime(2026, 9, 2, 2, 0, tzinfo=timezone.utc))])
    teks = "\n".join(_baris(_cetak(trx=trx)))
    assert "Nomor polisi" not in teks
    assert "Sopir" not in teks
    # Yang menandatangani sebagai saksi adalah orang yang datang membawa
    # barangnya sendiri, bukan sopir yang tidak pernah ada.
    assert "Pengirim" in teks
    assert "Karyo Tani" in teks


# ─────────────── Huruf yang bisa dicetak alat ───────────────

def test_huruf_di_luar_kemampuan_printer_diturunkan_bukan_dibiarkan():
    """Code page satu byte: huruf asing keluar sebagai simbol acak, dan satu
    simbol acak di tengah nama membuat bukti terlihat palsu."""
    teks = "\n".join(_baris(_cetak(pihak="Café Sejahtera — “Mitra”")))
    assert "Cafe Sejahtera - \"Mitra\"" in teks
    assert all(ord(c) < 128 for c in teks)


def test_tanda_kali_pada_tara_karung_ikut_diturunkan():
    trx = _trx(jumlah_karung=100, total_tara_kg=10, berat_barang_kg=8230)
    teks = "\n".join(_baris(_cetak(trx=trx)))
    assert "Tara karung" in teks
    assert "×" not in teks and " x " in teks


# ─────────────── Bentuk perintah ───────────────

def test_perintah_selalu_diakhiri_pemotongan_kertas():
    """Tanpa potong, struk berikutnya menyambung ke struk sebelumnya."""
    assert _cetak().rstrip().endswith(
        "<cut type=\"feed\"/></epos-print></s:Body></s:Envelope>")


def test_isian_bebas_tidak_bisa_menyuntikkan_perintah_cetak():
    """Nama pihak diketik petugas; ia tidak boleh menjadi perintah alat."""
    xml = _cetak(pihak='</text><cut type="reserve"/><text>')
    assert xml.count("<cut") == 1
    assert "&lt;/text&gt;" in xml
    ElementTree.fromstring(xml)   # tetap XML yang sah


def test_struk_uji_memuat_penggaris_selebar_kertas():
    """Penggaris yang patah dua adalah tanda kertasnya bukan 80 mm — itu satu
    dari dua kekeliruan pemasangan yang paling sering terjadi."""
    baris = _baris(epos.struk_uji(perusahaan="PT Hadi Mulya Utama"))
    penggaris = [b for b in baris if re.fullmatch(r"\d{48}", b)]
    assert len(penggaris) == 1


def test_baris_tengah_tidak_ditengahkan_dua_kali():
    """Spasi yang kita tambahkan ikut terhitung isi baris, jadi printer
    menggesernya lagi ke kanan — teksnya berakhir tidak di tengah."""
    akar = ElementTree.fromstring(_cetak())
    for el in akar.iter(_RUANG + "text"):
        if el.get("align") == "center":
            isi = (el.text or "").rstrip("\n")
            assert isi == isi.strip(), f"berspasi sisi: {isi!r}"


def test_setiap_baris_menyebut_gaya_hurufnya_sendiri():
    """`dw` dan `em` adalah saklar pada alat, bukan sifat satu baris.

    Nama perusahaan pernah dicetak lebar tanpa dimatikan lagi; seluruh struk
    di bawahnya ikut lebar, dan kertas 48 kolom hanya memuat 24 — tiap baris
    patah di tengah kata, angka termasuk. Kertas itu tidak bisa dipakai.
    """
    for xml in (_cetak(), epos.struk_uji(perusahaan="PT Hadi Mulya Utama")):
        akar = ElementTree.fromstring(xml)
        for el in akar.iter(_RUANG + "text"):
            for sifat in ("align", "em", "dw"):
                assert el.get(sifat) is not None, \
                    f"{sifat} tidak disebut: {el.text!r}"


def test_hanya_nama_perusahaan_yang_dicetak_lebar():
    """Sisanya harus muat 48 kolom; huruf lebar hanya memuat 24."""
    akar = ElementTree.fromstring(_cetak())
    lebar = [(el.text or "").strip()
             for el in akar.iter(_RUANG + "text") if el.get("dw") == "true"]
    assert lebar == ["PT Hadi Mulya Utama"]

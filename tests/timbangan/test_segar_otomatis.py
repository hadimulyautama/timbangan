"""Layar yang menyegarkan diri — dan yang sengaja TIDAK.

Keluhan pemilik, 10 September 2026: petugas mencatat penimbangan dari HP-nya,
dan di layar orang lain yang membuka halaman sama tak terjadi apa-apa. Harus
mematikan aplikasi dulu baru terlihat.

Sebabnya bukan service worker — yang disimpannya hanya kerangka aplikasi, dan
tiap navigasi selalu ke jaringan. Sebabnya tak ada satu pun pemicu
penyegaran: halaman digambar sekali lalu diam selamanya, dan aplikasi
terpasang tak pernah dimuat ulang saat dibuka kembali dari latar belakang.

Yang dijaga berkas ini justru SISI SEBALIKNYA. Menyegarkan di sini berarti
memuat ulang halaman, dan reload membuang yang sedang diketik. Petugas
mengisi borang sambil truk menunggu di jembatan — satu reload yang menghapus
nomor polisi dan bobot yang baru diketik jauh lebih buruk daripada angka yang
telat semenit.
"""
from __future__ import annotations

import pathlib

AKAR = pathlib.Path(__file__).resolve().parents[2]
JS = (AKAR / "app/timbangan/static/app.js").read_text()
TPL = AKAR / "app/timbangan/templates"

#: Layar BACA — boleh menyegarkan diri.
BACA = ("beranda", "daftar", "monitoring", "laporan")

#: Layar KERJA — tak boleh, apa pun alasannya. Di sinilah truk menunggu.
KERJA = ("timbang1", "timbang2", "tara", "koreksi", "partai", "pilih_jenis",
         "masuk", "pengguna", "pengguna_ubah", "aturan", "pengaturan",
         "printer", "cetak_pilih", "akun_saya")


def test_ada_pemicu_penyegaran():
    """Tiga pemicu, dan ketiganya perlu."""
    assert "addEventListener('visibilitychange'" in JS, "kembali ke depan"
    assert "addEventListener('pageshow'" in JS, "simpanan maju-mundur peramban"
    assert "setInterval(periksa" in JS, "denyut untuk layar yang tergeletak"


def test_denyut_hanya_saat_terlihat():
    """Yang di latar belakang tak boleh menghabiskan baterai maupun kuota."""
    assert "visibilityState !== 'visible'" in JS
    assert "hentikanDenyut" in JS


def test_tak_pernah_membuang_ketikan():
    """Empat penjagaan, dan tiap satunya pernah jadi cara orang kehilangan
    pekerjaannya di aplikasi lain."""
    blok = JS[JS.index("function bolehSegar"):JS.index("function mulaiDenyut")]
    assert "kotor" in blok, "halaman yang sudah disentuh tak dijaga"
    assert "INPUT|SELECT|TEXTAREA" in blok, "kotak yang sedang dipegang tak dijaga"
    assert "adaAntrean()" in blok, "antrean luring tak dijaga"
    assert "visibilityState" in blok


def test_antrean_luring_menahan_penyegaran():
    """Antrean berisi = sinyal sedang buruk. Reload saat itu bisa mendarat di
    halaman luring, dan petugas kehilangan layarnya karena kami mencoba
    menolongnya. Ragu pun ditahan: `catch` menjawab TRUE."""
    blok = JS[JS.index("function adaAntrean"):JS.index("function bolehSegar")]
    assert "GUDANG" in blok
    assert "return true;" in blok, "kegagalan baca localStorage harus menahan"


def test_diperiksa_dua_kali():
    """Orangnya bisa mulai mengetik tepat selagi permintaannya di jalan."""
    blok = JS[JS.index("function periksa() {"):JS.index("function mulaiDenyut")]
    assert blok.count("bolehSegar()") >= 2


def test_tak_memuat_ulang_bila_tak_ada_yang_berubah():
    """Reload yang tak mengubah apa pun tetap terlihat: layar berkedip,
    gulungan kembali ke atas. Berkedip tiap menit tanpa alasan mengajari orang
    bahwa aplikasinya rewel."""
    blok = JS[JS.index("function periksa() {"):JS.index("function mulaiDenyut")]
    assert "innerHTML === lama" in blok
    assert blok.index("innerHTML === lama") < blok.index("location.reload()")


def test_opt_in_per_halaman():
    """Bawaannya DIAM. Halaman baru harus memutuskannya sendiri — kalau
    menyala secara bawaan, layar kerja berikutnya akan ikut menyala tanpa ada
    yang menyadarinya."""
    base = (TPL / "base.html").read_text()
    assert "{% block segar_otomatis %}{% endblock %}" in base
    assert "data-segar-otomatis" not in base, "jangan menyala secara bawaan"
    assert "badan.dataset.segarOtomatis" in JS


def test_layar_baca_menyala():
    for nama in BACA:
        isi = (TPL / f"{nama}.html").read_text()
        assert 'data-segar-otomatis="1"' in isi, nama


def test_layar_kerja_TIDAK_menyala():
    """Di sinilah truk menunggu di jembatan."""
    for nama in KERJA:
        berkas = TPL / f"{nama}.html"
        if not berkas.exists():
            continue
        assert "segar_otomatis" not in berkas.read_text(), (
            f"{nama} boleh menyegarkan diri — ketikan petugas bisa hilang")

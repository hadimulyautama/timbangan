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
# Pilih fungsi penyegaran, bukan validator field bernama sama.
SEBAR = JS[JS.index("function bolehSegar"): ]

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
    # Denyut kini jalur kedua: hanya bertanya bila kanal dorong tak hidup.
    assert "setInterval(function () { if (jalur !== 'sse') { periksa(); } }" in JS, "denyut untuk layar yang tergeletak"


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
    blok = SEBAR[SEBAR.index("function periksa() {"):SEBAR.index("function mulaiDenyut")]
    assert blok.count("bolehSegar()") >= 2


def test_tak_memuat_ulang_bila_tak_ada_yang_berubah():
    """Reload yang tak mengubah apa pun tetap terlihat: layar berkedip,
    gulungan kembali ke atas. Berkedip tiap menit tanpa alasan mengajari orang
    bahwa aplikasinya rewel."""
    blok = SEBAR[SEBAR.index("function periksa() {"):SEBAR.index("function mulaiDenyut")]
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


# ─────────────── Penanda keadaan: bertanya dulu, mengunduh belakangan ───────────────

def test_bertanya_dulu_sebelum_mengunduh_halaman():
    """Denyut yang mengunduh seluruh halaman hanya untuk menyimpulkan "tak ada
    yang berubah" membakar kuota petugas — dan petugas memakai kuotanya
    sendiri. Yang ditanya lebih dulu satu penanda pendek."""
    assert "tanyaPenanda" in JS
    blok = SEBAR[SEBAR.index("function periksa() {"):SEBAR.index("function periksaIsi")]
    assert "tanyaPenanda()" in blok
    assert "periksaIsi()" in blok
    # Halamannya TIDAK diambil di fungsi yang menanyakan penanda.
    assert "fetch(location.href" not in blok


def test_belum_tahu_diperlakukan_sebagai_mungkin_berubah():
    """`null` terjadi tepat sesudah aplikasi dibuka — dan di situlah justru
    yang paling mungkin basi, karena telepon bisa saja sejam di kantong.
    Menganggapnya "tak berubah" berarti mengulang keluhan yang sedang
    diperbaiki."""
    blok = SEBAR[SEBAR.index("function periksa() {"):SEBAR.index("function periksaIsi")]
    assert "p !== null && penanda !== null" in blok, (
        "penanda yang belum diketahui harus melanjutkan, bukan berhenti")


def test_gagal_bertanya_tak_memicu_muat_ulang():
    """Sesi habis menjawab halaman masuk, bukan JSON. Kalau itu ditafsirkan
    sebagai "ada perubahan", layarnya memuat ulang tanpa henti."""
    blok = SEBAR[SEBAR.index("function tanyaPenanda"):SEBAR.index("function periksa() {")]
    assert "r.ok ? r.json() : null" in blok
    assert ".catch(" in blok and "return null" in blok


def test_penandanya_ikut_perubahan_bukan_cuma_penambahan():
    """Tiket DIUBAH saat timbang kedua — bobot keluar diisi, statusnya
    berpindah — dan nomornya tak bergerak sedikit pun di situ."""
    src = (AKAR / "app/timbangan/routes/pos.py").read_text()
    blok = src[src.index('@router.get("/keadaan")'):src.index('@router.get("/")')]
    assert "max(id)" in blok and "max(updated_at)" in blok
    # Dari basis data, bukan jam perangkat: jam yang bergeser bisa membuat
    # satu perubahan terlewat selamanya.
    assert "extract(epoch" in blok

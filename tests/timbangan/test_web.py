"""Uji alur lewat HTTP: petugas benar-benar bisa menyelesaikan pekerjaannya.

Uji layanan membuktikan aturannya benar; uji ini membuktikan aturan itu
sampai ke layar — rute terdaftar, template tidak salah nama, formulir kembali
lagi ke server dengan nama kolom yang benar, dan halaman yang seharusnya
tertutup memang tertutup.
"""
from __future__ import annotations

import re

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app import database
from app.database import Base
from app.models import Supplier
from app.timbangan import service
from app.timbangan.models import (
    ROLE_ADMIN,
    ROLE_PETUGAS,
    ROLE_SUPERADMIN,
    TIKET_SELESAI,
    TIKET_TERBUKA,
    TimbanganAkun,
)
from app.timbangan.security import hash_sandi
from app.timbangan.web import PREFIX, pasang

SANDI = "rahasia123"
TELEPON_UJI = "+62 851-7416-7950"


@pytest_asyncio.fixture
async def app_uji(monkeypatch):
    """Satu aplikasi + satu DB SQLite sementara per uji."""
    mesin = create_async_engine("sqlite+aiosqlite://")
    async with mesin.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Sesi = async_sessionmaker(mesin, expire_on_commit=False)
    # Modul mengambil SessionLocal lewat `app.database`, bukan meng-import
    # objeknya — justru supaya bisa dialihkan seperti ini.
    monkeypatch.setattr(database, "SessionLocal", Sesi)

    async with Sesi() as db:
        await service.pastikan_jenis(db)
        db.add_all([
            TimbanganAkun(username="budi", nama="Budi", role=ROLE_PETUGAS,
                          password_hash=hash_sandi(SANDI), perangkat_kode="P1"),
            TimbanganAkun(username="miftah", nama="Miftah", role=ROLE_PETUGAS,
                          password_hash=hash_sandi(SANDI), perangkat_kode="P9"),
            TimbanganAkun(username="wahid", nama="Wahid", role=ROLE_ADMIN,
                          password_hash=hash_sandi(SANDI), perangkat_kode="P0"),
            Supplier(nama_supplier="H. Anton"),
        ])
        await db.commit()

    aplikasi = FastAPI()
    pasang(aplikasi)
    yield aplikasi
    await mesin.dispose()


@pytest_asyncio.fixture
async def klien(app_uji):
    async with AsyncClient(
        transport=ASGITransport(app=app_uji), base_url="http://uji",
        follow_redirects=True,
    ) as c:
        yield c


async def login(klien: AsyncClient, siapa: str = "budi") -> None:
    r = await klien.post(
        f"{PREFIX}/masuk",
        data={"username": siapa, "sandi": SANDI, "perangkat": "P1", "tujuan": ""},
    )
    assert r.status_code == 200, r.text


def kode_dari(html: str) -> str:
    cocok = re.search(r'name="kode" value="(TRX-[^"]+)"', html)
    assert cocok, "nomor transaksi tidak ada di formulir"
    return cocok.group(1)


# ─────────────────── Penjaga akses ───────────────────

async def test_belum_login_diarahkan_ke_halaman_masuk(klien):
    r = await klien.get(f"{PREFIX}/")
    assert r.status_code == 200
    assert "Kata sandi" in r.text


async def test_sandi_salah_tidak_membocorkan_yang_mana(klien):
    r = await klien.post(
        f"{PREFIX}/masuk",
        data={"username": "budi", "sandi": "salah", "perangkat": "", "tujuan": ""},
    )
    assert "Nama pengguna atau kata sandi salah" in r.text

    r = await klien.post(
        f"{PREFIX}/masuk",
        data={"username": "tidakada", "sandi": "apa saja", "perangkat": "",
              "tujuan": ""},
    )
    assert "Nama pengguna atau kata sandi salah" in r.text


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
@pytest.mark.parametrize(
    "jalur", ["/laporan", "/monitoring", "/ekspor.csv", "/transaksi"]
)
async def test_ringkasan_dan_catatan_hanya_untuk_admin(klien, siapa, jalur):
    """Keputusan Direksi: hanya Admin yang melihat rekapitulasi.

    Diuji dengan dua akun petugas yang berbeda, supaya yang dikunci adalah
    perannya — bukan kebetulan satu nama pengguna tertentu.
    """
    await login(klien, siapa)
    assert (await klien.get(PREFIX + jalur)).status_code == 403


async def test_petugas_tidak_bisa_membuka_halaman_admin(klien):
    await login(klien)
    assert (await klien.get(f"{PREFIX}/pengguna")).status_code == 403


async def test_admin_bisa_membuka_semuanya(klien):
    await login(klien, "wahid")
    for jalur in ("/laporan", "/monitoring", "/tara", "/pengguna",
                  "/aturan", "/pengaturan"):
        r = await klien.get(PREFIX + jalur)
        assert r.status_code == 200, f"{jalur} → {r.status_code}"


# ─────────────────── Halaman utama ───────────────────

async def test_beranda_menawarkan_tiga_arah(klien):
    await login(klien)
    r = await klien.get(f"{PREFIX}/")
    assert r.status_code == 200
    assert "Barang masuk" in r.text
    assert "Pengiriman" in r.text
    assert "Jasa timbang" in r.text


async def test_daftar_komoditas_berbeda_menurut_arah(klien):
    """Menir, bekatul, dan reject tidak pernah dibeli — jangan ditawarkan."""
    await login(klien)
    masuk = (await klien.get(f"{PREFIX}/pilih/MASUK")).text
    keluar = (await klien.get(f"{PREFIX}/pilih/KELUAR")).text

    assert "Gabah Basah" in masuk
    assert "Bekatul" not in masuk
    assert "Menir" not in masuk

    assert "Bekatul" in keluar
    assert "Gabah Basah" not in keluar


# ─────────────────── Alur lengkap ───────────────────

async def test_alur_lengkap_masuk_sampai_hasil(klien):
    await login(klien)

    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    kode = kode_dari(form)
    assert kode.startswith("TRX-") and "-P1-" in kode

    r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode, "berat_kg": "13.600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "ad 1234 xy", "nama_sopir": "Slamet",
        "nomor_acuan": "NOTA-01", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10.048",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "pihak_nama": "",
    })
    assert r.status_code == 200
    assert "Menunggu timbang kedua" in r.text
    assert "AD 1234 XY" in r.text

    # Tiket muncul di beranda dan di daftar tiket.
    assert "AD 1234 XY" in (await klien.get(f"{PREFIX}/")).text
    tiket = await klien.get(f"{PREFIX}/tiket")
    assert "AD 1234 XY" in tiket.text

    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
    })
    assert r.status_code == 200
    assert "PERLU PEMERIKSAAN" in r.text
    assert "10.000 kg" in r.text     # berat barang
    assert "-48 kg" in r.text        # selisih


async def test_angka_dengan_koma_maupun_titik_diterima(klien):
    """Petugas mengetik apa adanya; sistem yang menyesuaikan diri."""
    await login(klien)
    for berat, harapan in (("13.600", "13.600"), ("13600", "13.600"),
                           ("13600,7", "13.601")):
        form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
        r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
            "kode": kode_dari(form), "berat_kg": berat,
            "cara_timbang": "DUA_KALI", "supplier_id": "1",
            "nomor_polisi": "AD 1 A", "jumlah_karung": "10",
            "tara_per_karung_kg": "0,25", "berat_acuan_kg": "1000",
            "tara_lain_kg": "0", "waktu": "", "catatan": "",
            "nomor_acuan": "", "nama_sopir": "Slamet", "pihak_nama": "",
        })
        assert harapan in r.text, f"{berat} → tidak muncul {harapan}"


async def test_jasa_timbang_sekali_langsung_ada_hasil(klien):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/BEBAS")).text
    r = await klien.post(f"{PREFIX}/timbang/BEBAS", data={
        "kode": kode_dari(form), "berat_kg": "12850",
        "cara_timbang": "SEKALI", "pihak_nama": "CV Sumber Rejeki",
        "nomor_polisi": "AD 9 ZZ", "tara_lain_kg": "0", "supplier_id": "",
        "jumlah_karung": "0", "tara_per_karung_kg": "0", "berat_acuan_kg": "0",
        "waktu": "", "catatan": "", "nomor_acuan": "", "nama_sopir": "Slamet",
    })
    assert r.status_code == 200
    # Statusnya dipakai jasa timbang maupun transfer internal, jadi labelnya
    # menyebut sifatnya — bukan salah satu pemakainya.
    assert "TANPA KONTROL" in r.text
    assert "12.850 kg" in r.text


async def test_tutup_paksa_tiket_lewat_halaman(klien):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 7 QQ", "jumlah_karung": "10",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "1000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "",
        "nama_sopir": "Slamet", "pihak_nama": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))

    r = await klien.post(f"{PREFIX}/tiket/{trx_id}/tutup",
                         data={"alasan": "Mutu ditolak, truk kembali"})
    assert "ditutup beserta alasannya" in r.text
    # Kalimatnya bukan lagi soal truk: partai kecil datang tanpa kendaraan,
    # dan daftar ini menampung keduanya.
    assert "Tidak ada tiket yang sedang terbuka" in \
        (await klien.get(f"{PREFIX}/tiket")).text


# ─────────────────── Kerahasiaan pada bukti cetak ───────────────────

async def _selesaikan(klien, jenis: str, **beda) -> int:
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    data = {
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 5 BB", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "N-1",
        "nama_sopir": "Slamet", "pihak_nama": "",
    }
    data.update(beda)
    await klien.post(f"{PREFIX}/timbang/{jenis}", data=data)
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
    })
    return trx_id


def teks_pdf(isi: bytes) -> str:
    import io
    from pypdf import PdfReader
    return "\n".join(h.extract_text() or "" for h in PdfReader(io.BytesIO(isi)).pages)


def ukuran_pdf(isi: bytes) -> tuple[float, float]:
    """(lebar, tinggi) dalam milimeter."""
    import io
    from pypdf import PdfReader
    kotak = PdfReader(io.BytesIO(isi)).pages[0].mediabox
    return float(kotak.width) / 72 * 25.4, float(kotak.height) / 72 * 25.4


async def test_bukti_gabah_tidak_memuat_selisih(klien):
    """SOP butir 8: hasil kontrol gabah adalah data internal."""
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    r = await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/80mm")
    assert r.headers["content-type"] == "application/pdf"
    cetak = teks_pdf(r.content)
    assert "BERAT BARANG" in cetak
    assert "Selisih" not in cetak
    assert "Menurut dokumen" not in cetak


async def test_bukti_beras_pk_memuat_selisih(klien):
    """Sistem Tara butir 9: nota PK justru wajib diberikan ke pengirim."""
    await login(klien)
    trx_id = await _selesaikan(
        klien, "BERAS_PK", tara_per_karung_kg="0,085", berat_acuan_kg="9990"
    )
    cetak = teks_pdf(
        (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/80mm")).content)
    assert "Selisih" in cetak
    assert "Menurut dokumen" in cetak


async def test_bukti_memuat_petugas_dan_identitas_perusahaan(klien):
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    cetak = teks_pdf(
        (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/80mm")).content)
    assert "PT Hadi Mulya Utama" in cetak
    assert "Masaran, Kab. Sragen" in cetak
    assert "Budi" in cetak                      # petugas timbang
    assert TELEPON_UJI in cetak
    # Alamat surel sengaja tidak ikut dicetak — Direksi memutuskan bukti
    # timbang cukup memuat alamat dan nomor telepon.
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", cetak)


# ─────────────────── Tidak ada harga di mana pun ───────────────────

@pytest.mark.parametrize("jalur", [
    "/", "/pilih/MASUK", "/pilih/KELUAR", "/timbang/GABAH_BASAH",
    "/tiket", "/transaksi", "/aturan", "/pengaturan",
])
async def test_tidak_ada_kata_harga_di_layar_petugas(klien, jalur):
    """Operator pos timbang tidak boleh tahu harga — termasuk di tampilan."""
    await login(klien)
    teks = (await klien.get(PREFIX + jalur)).text.lower()
    for kata in ("harga", "rupiah", " rp", "potongan", "refaksi"):
        assert kata not in teks, f"{jalur} memuat '{kata}'"


# ─────────────────── Koreksi lewat halaman ───────────────────

async def test_koreksi_lewat_halaman_menghitung_ulang(klien):
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH", berat_acuan_kg="10048")

    rincian = (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    assert "PERLU PEMERIKSAAN" in rincian

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/koreksi", data={
        "alasan": "Salah ketik berat nota", "timbang1_kg": "", "timbang2_kg": "",
        "nomor_polisi": "", "nama_sopir": "Slamet", "supplier_id": "",
        "jumlah_karung": "120", "tara_per_karung_kg": "0,25",
        "berat_acuan_kg": "10010", "nomor_acuan": "N-1", "catatan": "",
    })
    assert "Koreksi tersimpan" in r.text
    assert "NORMAL" in r.text


async def test_koreksi_wajib_beralasan(klien):
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/koreksi", data={
        "alasan": "   ", "berat_acuan_kg": "9000",
    })
    assert "harus disertai alasan" in r.text


# ─────────────────── Ekspor ───────────────────

async def test_ekspor_csv_tanpa_kolom_uang(klien):
    await login(klien, "wahid")
    await _selesaikan(klien, "GABAH_BASAH")
    r = await klien.get(f"{PREFIX}/ekspor.csv")
    assert r.status_code == 200
    kepala = r.text.splitlines()[0].lower()
    for kata in ("harga", "rp", "nilai", "biaya", "potongan"):
        assert kata not in kepala
    assert "selisih_kg" in kepala


# ─────────────────── Pembacaan angka yang diketik petugas ───────────────────

@pytest.mark.parametrize("ketikan, harapan", [
    # Titik sebagai pemisah ribuan
    ("13.600", 13600.0),
    ("13600", 13600.0),
    ("1.234.567", 1234567.0),
    ("10.048", 10048.0),
    # Titik sebagai desimal — angka di depan titik nol
    ("0.250", 0.25),
    ("0.085", 0.085),
    ("0.05", 0.05),
    ("0.070", 0.07),
    # Koma selalu desimal
    ("0,25", 0.25),
    ("13.600,5", 13600.5),
    ("13600,7", 13600.7),
    # Bukan angka → nilai bawaan
    ("", 0.0),
    ("abc", 0.0),
])
def test_membaca_angka_yang_diketik(ketikan, harapan):
    """Regresi: tara '0.250' pernah terbaca 250 kg.

    Satu titik dengan tiga angka di belakangnya ambigu — '13.600' berarti tiga
    belas ribu enam ratus, '0.250' berarti seperempat kilogram. Angka di depan
    titik yang membedakan. Salah menebak membuat setiap transaksi gabah
    ditolak sebagai mustahil, karena taranya membengkak seribu kali lipat.
    """
    from app.timbangan.routes.pos import _angka
    assert _angka(ketikan) == pytest.approx(harapan)


async def test_tara_prasetel_bertahan_melintasi_dua_tahap(klien):
    """Nilai tara yang disodorkan sistem harus bisa dibaca ulang oleh sistem.

    Formulir tahap kedua mengisi ulang tara dari transaksi ('0.250'); bila
    pembacaannya berbeda dari saat menulisnya, penimbangan gagal di tahap
    terakhir — persis ketika truk sudah selesai bongkar.
    """
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert 'value="0.250"' in form          # disodorkan server apa adanya

    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13.600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1",
        "nomor_polisi": "AD 1234 XY", "nama_sopir": "Slamet",
        "nomor_acuan": "NOTA-01", "jumlah_karung": "120",
        "tara_per_karung_kg": "0.250",     # persis seperti yang disodorkan
        "berat_acuan_kg": "10.048", "tara_lain_kg": "0", "waktu": "",
        "catatan": "", "pihak_nama": "",
    })

    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    tahap2 = (await klien.get(f"{PREFIX}/tiket/{trx_id}")).text
    assert 'value="0.250"' in tahap2

    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "120",
        "tara_per_karung_kg": "0.250", "berat_acuan_kg": "10048",
        "nomor_acuan": "NOTA-01", "waktu": "", "catatan": "",
    })
    assert "Tara lebih besar" not in r.text
    assert "10.000 kg" in r.text        # berat barang, tara 30 kg bukan 30.000


# ─────────────────── Halaman pengaturan ───────────────────

async def test_pengaturan_mendaftar_parameter_beserta_nilainya(klien, app_uji):
    """Katalog harus menyebut nilai yang benar-benar berlaku, bukan contoh."""
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text

    # Admin melihatnya sebagai kotak isian berisi angka mentah.
    assert "Kapasitas jembatan timbang" in teks
    assert 'value="20000"' in teks
    assert "TIMBANGAN_KAPASITAS_KG" in teks
    assert "Transaksi terkunci setelah" in teks and 'value="24"' in teks
    assert "Tiket ditandai lama setelah" in teks and 'value="12"' in teks
    assert "Ukuran maksimum satu foto" in teks and 'value="4"' in teks
    assert TELEPON_UJI in teks
    from app.timbangan import logic
    assert f"{len(logic.JENIS_AWAL)} komoditas aktif" in teks


async def test_bukan_admin_melihat_nilai_terbaca_tanpa_kotak_isian(klien):
    """Petugas boleh tahu batas yang berlaku, tetapi tidak mengubahnya."""
    await login(klien)                       # budi — petugas
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert "20.000 kg" in teks               # pemisah ribuan, mudah dibaca
    assert 'name="nilai"' not in teks
    assert "Hanya Admin yang dapat mengubah bagian ini." in teks


async def test_pengaturan_tidak_pernah_menampilkan_kunci_sesi(klien):
    """Kunci penanda sesi hanya boleh dilaporkan ada atau tidak."""
    import os
    from app.timbangan.config import tsettings

    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert "Kunci penanda sesi" in teks
    if tsettings.secret_key:
        assert tsettings.secret_key not in teks
        assert "sudah diset" in teks
    else:
        assert "BELUM DISET" in teks


async def test_pengaturan_menyembunyikan_baris_di_luar_peran(klien):
    """Petugas melihat akunnya dan aturan; tidak melihat pintu admin."""
    await login(klien)                       # budi — petugas
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text

    assert "Akun ini" in teks
    assert "Aturan komoditas" in teks
    assert "Pengguna &amp; perangkat" not in teks
    assert "Tara standar" not in teks
    assert "Sesi &amp; keamanan" not in teks


async def test_pengaturan_memuat_tombol_keluar(klien):
    await login(klien)
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert f'action="{PREFIX}/keluar"' in teks
    assert ">Keluar<" in teks


async def test_keluar_dari_pengaturan_benar_benar_mengakhiri_sesi(klien):
    await login(klien)
    r = await klien.post(f"{PREFIX}/keluar")
    assert "Kata sandi" in r.text            # kembali ke halaman masuk
    # Membuka beranda lagi harus meminta login, bukan menampilkan isi.
    assert "Kata sandi" in (await klien.get(f"{PREFIX}/")).text


async def test_akun_kini_halaman_tersendiri_bukan_pengalihan(klien):
    """Dulu /akun hanya melempar ke Pengaturan; sekarang ia halamannya sendiri,
    karena di sinilah setiap peran mengurus namanya dan sandinya."""
    await login(klien)
    r = await klien.get(f"{PREFIX}/akun")
    assert str(r.url).endswith("/akun")
    assert "Akun saya" in r.text


# ─────────────────── Setelan operasional benar-benar berdampak ───────────────────

async def test_admin_menyetel_kapasitas_dan_langsung_berlaku(klien, app_uji):
    """Bukti bahwa setelan dipakai, bukan sekadar tersimpan.

    Kapasitas diturunkan ke 12 ton; truk 13,6 ton yang tadinya sah kini
    ditolak — tanpa menyalakan ulang service.
    """
    await _jadi_super(app_uji)
    await login(klien, "wahid")

    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 1 A", "jumlah_karung": "10",
        "tara_per_karung_kg": "0.250", "berat_acuan_kg": "1000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "",
        "nama_sopir": "Slamet", "pihak_nama": "",
    })
    assert "Melebihi kapasitas" not in r.text

    r = await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "kapasitas_jembatan_kg", "nilai": "12000", "aksi": "simpan",
    })
    assert "kini 12.000 kg" in r.text

    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert "12.000 kg" in form              # bantuan di layar ikut berubah
    r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 2 B", "jumlah_karung": "10",
        "tara_per_karung_kg": "0.250", "berat_acuan_kg": "1000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "",
        "nama_sopir": "Slamet", "pihak_nama": "",
    })
    assert "Melebihi kapasitas jembatan timbang (12000 kg)" in r.text


async def test_setelan_di_luar_batas_wajar_ditolak(klien):
    """Kapasitas yang salah ketik akan menolak setiap truk — jangan diterima."""
    await login(klien, "wahid")
    for nilai in ("0", "50", "999999", "abc", ""):
        r = await klien.post(f"{PREFIX}/pengaturan", data={
            "kunci": "kapasitas_jembatan_kg", "nilai": nilai, "aksi": "simpan",
        })
        assert "kini" not in r.text, f"{nilai!r} seharusnya ditolak"


async def test_kembalikan_bawaan_menghapus_setelan(klien, app_uji):
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "jam_kunci_otomatis", "nilai": "48", "aksi": "simpan",
    })
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert 'value="48"' in teks and "disetel dari layar" in teks

    r = await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "jam_kunci_otomatis", "aksi": "bawaan", "nilai": "",
    })
    assert "kembali ke bawaan 24 jam" in r.text
    assert 'value="24"' in (await klien.get(f"{PREFIX}/pengaturan")).text


async def test_bukan_admin_tidak_bisa_menyetel(klien):
    await login(klien)                       # budi — petugas
    r = await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "kapasitas_jembatan_kg", "nilai": "12000", "aksi": "simpan",
    })
    assert r.status_code == 403


async def test_perubahan_setelan_tercatat_di_audit(klien, app_uji):
    from sqlalchemy import select
    from app import database
    from app.timbangan.models import TimbanganAudit

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "maks_foto_mb", "nilai": "8", "aksi": "simpan",
    })
    async with database.SessionLocal() as db:
        jejak = (await db.execute(
            select(TimbanganAudit).where(TimbanganAudit.aksi == "UBAH_SETELAN")
        )).scalars().all()
    assert len(jejak) == 1
    assert "4" in jejak[0].nilai_sebelum and "8" in jejak[0].nilai_sesudah


# ─────────────── Menambah pengguna: Admin saja ───────────────
#
# Peran menentukan siapa boleh mengoreksi timbangan dan menutup pemeriksaan.
# Siapa pun yang bisa membuat akun, bisa memberi dirinya peran apa pun — jadi
# pintu ini dijaga paling ketat. Pengawas sengaja ikut diuji: ia peran yang
# paling dekat ke Admin, dan paling mungkin keliru diberi akses saat kode
# disalin-tempel di kemudian hari.

async def jumlah_akun(app_uji) -> int:
    from sqlalchemy import func, select
    from app import database

    async with database.SessionLocal() as db:
        return (await db.execute(select(func.count(TimbanganAkun.id)))).scalar_one()


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_bukan_admin_tidak_bisa_membuka_halaman_pengguna(klien, siapa):
    await login(klien, siapa)
    r = await klien.get(f"{PREFIX}/pengguna")
    assert r.status_code == 403
    assert "hanya untuk Super Admin" in r.text


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_bukan_admin_tidak_bisa_membuat_akun(klien, app_uji, siapa):
    """Ditolak, DAN tidak ada akun yang benar-benar terbuat."""
    sebelum = await jumlah_akun(app_uji)
    await login(klien, siapa)

    r = await klien.post(f"{PREFIX}/pengguna", data={
        "username": "penyusup", "nama": "Penyusup", "role": ROLE_ADMIN,
        "sandi": "rahasia123", "perangkat_kode": "PX",
    })
    assert r.status_code == 403
    assert await jumlah_akun(app_uji) == sebelum


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_bukan_admin_tidak_bisa_menonaktifkan_akun(klien, app_uji, siapa):
    from sqlalchemy import select
    from app import database

    await login(klien, siapa)
    r = await klien.post(f"{PREFIX}/pengguna/1/status")
    assert r.status_code == 403

    async with database.SessionLocal() as db:
        korban = (await db.execute(
            select(TimbanganAkun).where(TimbanganAkun.id == 1)
        )).scalars().one()
        assert korban.status == "aktif"      # tidak tersentuh


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_pengaturan_tidak_menawarkan_pintu_pengguna(klien, siapa):
    """Bukan hanya ditolak saat dibuka — tautannya pun tidak ditampilkan."""
    await login(klien, siapa)
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert "Pengguna &amp; perangkat" not in teks
    assert f"{PREFIX}/pengguna" not in teks


async def test_admin_bisa_membuat_akun(klien, app_uji):
    """Sisi lain dari aturan yang sama — Admin memang harus bisa."""
    sebelum = await jumlah_akun(app_uji)
    await login(klien, "wahid")

    r = await klien.post(f"{PREFIX}/pengguna", data={
        "username": "SARI", "nama": "Sari", "role": ROLE_PETUGAS,
        "sandi": "rahasia123", "perangkat_kode": "p2",
    })
    assert "Akun Sari dibuat" in r.text
    assert await jumlah_akun(app_uji) == sebelum + 1
    # Nama pengguna dijadikan huruf kecil, kode perangkat huruf besar.
    assert "sari" in r.text and "P2" in r.text


async def test_admin_tidak_bisa_menonaktifkan_akun_sendiri(klien):
    """Menutup pintu terakhir bagi diri sendiri harus dicegah."""
    from sqlalchemy import select
    from app import database

    await login(klien, "wahid")
    async with database.SessionLocal() as db:
        aku = (await db.execute(
            select(TimbanganAkun).where(TimbanganAkun.username == "wahid")
        )).scalars().one()

    r = await klien.post(f"{PREFIX}/pengguna/{aku.id}/status")
    assert "tidak bisa menonaktifkan akun sendiri" in r.text


# ─────────────── Daftar supplier: yang sering datang di atas ───────────────

async def test_supplier_sering_datang_didahulukan(klien, app_uji):
    """Daftar dari Kledo memuat ratusan vendor; petugas hanya butuh belasan.

    Yang pernah dipakai belakangan harus muncul di kelompok atas, supaya
    petugas tidak menggulir ratusan nama sambil truk menunggu.
    """
    from app import database
    from app.models import Supplier

    async with database.SessionLocal() as db:
        db.add_all([Supplier(nama_supplier=f"Vendor Karung {i}") for i in range(5)])
        await db.commit()

    await login(klien)
    # H. Anton (id 1) dipakai pada transaksi ini.
    await _selesaikan(klien, "GABAH_BASAH")

    teks = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert 'label="Sering datang"' in teks and 'label="Lainnya"' in teks
    sering = teks.split('label="Sering datang"')[1].split("</optgroup>")[0]
    assert "H. Anton" in sering
    assert "Vendor Karung 0" not in sering


async def test_supplier_belum_pernah_dipakai_tetap_bisa_dipilih(klien, app_uji):
    """Yang jarang datang tidak boleh hilang — hanya diturunkan urutannya."""
    from app import database
    from app.models import Supplier

    async with database.SessionLocal() as db:
        db.add(Supplier(nama_supplier="Pemasok Musiman"))
        await db.commit()

    await login(klien)
    teks = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert "Pemasok Musiman" in teks


# ─────────────── Jalan pulang selalu ada ───────────────

@pytest.mark.parametrize("jalur", [
    "/", "/tiket", "/transaksi", "/pengaturan", "/aturan",
    "/pilih/MASUK", "/timbang/GABAH_BASAH",
])
async def test_bilah_bawah_ada_di_setiap_halaman(klien, jalur):
    """Dari halaman mana pun, beranda cukup satu ketukan.

    Sebelumnya petugas harus menekan panah kembali berkali-kali — mahal saat
    truk sedang menunggu di jembatan.
    """
    await login(klien)
    teks = (await klien.get(PREFIX + jalur)).text
    assert 'class="bawah"' in teks
    assert f'href="{PREFIX}/"' in teks


async def test_halaman_masuk_tidak_memuat_bilah_bawah(klien):
    """Belum masuk berarti belum ada ke mana pun untuk pergi."""
    teks = (await klien.get(f"{PREFIX}/masuk")).text
    assert 'class="bawah"' not in teks


async def test_petugas_tidak_melihat_ringkasan_di_bilah(klien):
    await login(klien)
    teks = (await klien.get(f"{PREFIX}/")).text
    assert f'href="{PREFIX}/laporan"' not in teks


async def test_sesudah_menimbang_langsung_bisa_truk_berikutnya(klien):
    """Aksi utama sesudah selesai adalah truk berikutnya, bukan menggali menu."""
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    teks = (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    assert f'href="{PREFIX}/pilih/MASUK"' in teks
    assert "Timbang berikutnya" in teks


async def test_tanda_tiket_terbuka_terlihat_dari_halaman_lain(klien):
    """Truk yang menunggu adalah hal paling mendesak — harus terlihat di mana pun."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 3 CC", "jumlah_karung": "10",
        "tara_per_karung_kg": "0.250", "berat_acuan_kg": "1000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "",
        "nama_sopir": "Slamet", "pihak_nama": "",
    })
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert 'class="bawah__tanda"' in teks


async def test_bukti_pengiriman_tidak_memuat_selisih(klien):
    """Keputusan Direksi: sopir menerima berat barang, bukan angka selisih."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/BEKATUL")).text
    await klien.post(f"{PREFIX}/timbang/BEKATUL", data={
        "kode": kode_dari(form), "berat_kg": "6200", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 8 KK", "jumlah_karung": "240",
        "tara_per_karung_kg": "0.05", "berat_acuan_kg": "12000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "SJ-9",
        "nama_sopir": "Slamet", "pihak_nama": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "18220", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
    })

    cetak = teks_pdf(
        (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/80mm")).content)
    assert "BERAT BARANG" in cetak
    assert "Selisih" not in cetak
    assert "Menurut dokumen" not in cetak


async def test_bukti_gabah_tetap_dicetak_dengan_sopir_sebagai_saksi(klien):
    """Cetakan itu alat bukti: sopir menandatanganinya. Bukan arsip sampingan."""
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")

    rincian = (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    assert "Cetak bukti timbang" in rincian
    assert "Cetak untuk arsip" not in rincian

    cetak = teks_pdf(
        (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/80mm")).content)
    assert "Sopir (saksi)" in cetak
    assert "Petugas timbang" in cetak
    assert "Ditandatangani kedua pihak" in cetak
    assert "Selisih" not in cetak        # tetap rahasia, hanya beratnya


def test_semua_komoditas_dicetak_buktinya():
    """Keputusan Direksi: semuanya perlu, karena sopir jadi saksi."""
    from app.timbangan import logic
    tanpa = [a.nama for a in logic.JENIS_AWAL if not a.cetak_bukti]
    assert tanpa == []


# ─────────────── Supplier: mengetik, bukan menggulir ───────────────

async def test_supplier_ditandai_agar_bisa_dicari(klien, app_uji):
    """Daftar ikut Kledo — ratusan nama. Kolomnya harus bisa diketik.

    Yang diuji di sini adalah kontraknya: `<select>` tetap dirender server
    (jadi tetap berfungsi bila JavaScript gagal dimuat) DAN diberi penanda
    `data-cari` yang dipakai app.js untuk menaikkannya jadi kolom pencarian.
    """
    from app import database
    from app.models import Supplier

    async with database.SessionLocal() as db:
        db.add_all([Supplier(nama_supplier=f"Vendor Karung {i:03d}")
                    for i in range(20)])
        await db.commit()

    await login(klien)
    teks = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert 'name="supplier_id"' in teks
    assert "data-cari=" in teks
    # Seluruh pilihan tetap ada di halaman, supaya penyaringan bekerja
    # tanpa memanggil server — penting saat sinyal hilang.
    assert "Vendor Karung 019" in teks
    assert "H. Anton" in teks


async def test_kolom_koreksi_juga_bisa_dicari(klien):
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    teks = (await klien.get(f"{PREFIX}/transaksi/{trx_id}/koreksi")).text
    assert "data-cari=" in teks


# ─────────────── Syarat pemasangan di layar depan ───────────────
#
# Safari iOS mengabaikan ikon SVG DAN ikon di dalam manifest. Tanpa
# apple-touch-icon PNG, "Tambahkan ke Layar Utama" memakai potret halaman
# sebagai ikon. Ini pernah terlewat sampai ditanyakan.

async def test_halaman_memuat_apple_touch_icon_png(klien):
    await login(klien)
    teks = (await klien.get(f"{PREFIX}/")).text
    assert 'rel="apple-touch-icon"' in teks
    assert "ikon-180.png" in teks
    assert 'name="apple-mobile-web-app-capable" content="yes"' in teks
    assert 'name="apple-mobile-web-app-title"' in teks


@pytest.mark.parametrize("berkas, tipe", [
    ("ikon-180.png", "image/png"),
    ("ikon-192.png", "image/png"),
    ("ikon-512.png", "image/png"),
    ("ikon.svg", "image/svg+xml"),
    ("manifest.json", "application/json"),
])
async def test_berkas_ikon_benar_benar_terlayani(klien, berkas, tipe):
    r = await klien.get(f"{PREFIX}/static/{berkas}")
    assert r.status_code == 200
    assert tipe in r.headers.get("content-type", "")


async def test_manifest_memuat_ikon_png_untuk_android(klien):
    """Chrome butuh 192 dan 512 PNG untuk menawarkan pemasangan."""
    m = (await klien.get(f"{PREFIX}/static/manifest.json")).json()
    ukuran = {i["sizes"] for i in m["icons"] if i["type"] == "image/png"}
    assert {"192x192", "512x512"} <= ukuran
    assert any(i.get("purpose") == "maskable" for i in m["icons"])
    assert m["display"] == "standalone"
    assert m["start_url"].startswith(PREFIX)


# ─────────────── Penyaring tanggal tidak boleh meluber ───────────────
#
# Pernah rusak di ponsel: kolom "SAMPAI" tembus keluar kartu. Penyebabnya
# kolom grid `1fr` yang menolak menyusut di bawah lebar isinya, sementara
# tanggal bawaan iOS ("Aug 30, 2026") jauh lebih lebar daripada angka biasa.

def test_gaya_penyaring_mengizinkan_kolom_menyusut():
    import pathlib

    css = (pathlib.Path(__file__).resolve().parents[2]
           / "app/timbangan/static/app.css").read_text()

    # Tanpa min-width:0, item grid/flex tidak akan pernah menyusut.
    grup = [b for b in css.splitlines() if b.startswith(".grup {")][0]
    assert "min-width: 0" in grup

    # minmax(0, 1fr) — bukan 1fr — barulah kolomnya boleh mengecil.
    assert "minmax(0, 1fr)" in css
    assert '.fld[type="date"]' in css


@pytest.mark.parametrize("berkas", ["daftar.html", "laporan.html"])
def test_penyaring_memakai_grid_yang_menyusut(berkas):
    import pathlib

    html = (pathlib.Path(__file__).resolve().parents[2]
            / "app/timbangan/templates" / berkas).read_text()
    assert "saring" in html, f"{berkas} tidak memakai kelas .saring"
    assert "grid-template-columns:1fr 1fr" not in html, (
        f"{berkas} kembali memakai kolom yang tidak bisa menyusut"
    )


# ─────────────── Dua ukuran bukti: 80 mm dan setengah NCR ───────────────

async def test_pemilih_menawarkan_dua_ukuran(klien):
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    teks = (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak")).text

    assert "Struk 80 mm" in teks
    assert "215 × 165 mm" in teks
    assert f"/transaksi/{trx_id}/cetak/80mm" in teks
    assert f"/transaksi/{trx_id}/cetak/ncr" in teks


async def test_lembar_ncr_berukuran_setengah_folio(klien):
    """Ukurannya harus PASTI, bukan bergantung pilihan kertas di dialog."""
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    r = await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/ncr")

    assert r.headers["content-type"] == "application/pdf"
    lebar, tinggi = ukuran_pdf(r.content)
    assert round(lebar) == 215 and round(tinggi) == 165

    teks = teks_pdf(r.content)
    assert "BERAT BARANG" in teks
    assert "Lembar 1" in teks and "Arsip pos timbang" in teks


@pytest.mark.parametrize("jenis, beda", [
    ("GABAH_BASAH", {}),
    ("BERAS_PK", {"tara_per_karung_kg": "0,085", "berat_acuan_kg": "9990"}),
])
async def test_lembar_ncr_tidak_pernah_memuat_selisih(klien, jenis, beda):
    """Berlaku untuk SEMUA komoditas — termasuk beras PK.

    Berbeda dari struk 80 mm, yang mengikuti aturan per komoditas. Lembar NCR
    diperlakukan sebagai salinan untuk pihak luar, jadi hasil kontrol internal
    tidak pernah ikut keluar.
    """
    await login(klien)
    trx_id = await _selesaikan(klien, jenis, **beda)
    ncr = teks_pdf(
        (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/ncr")).content)

    assert "Selisih" not in ncr
    assert "Menurut dokumen" not in ncr


async def test_struk_80mm_tetap_mengikuti_aturan_komoditas(klien):
    """Yang lama tidak berubah: PK tetap memuat selisih, gabah tidak."""
    await login(klien)

    gabah = await _selesaikan(klien, "GABAH_BASAH")
    assert "Selisih" not in teks_pdf(
        (await klien.get(f"{PREFIX}/transaksi/{gabah}/cetak/80mm")).content)

    pk = await _selesaikan(
        klien, "BERAS_PK", tara_per_karung_kg="0,085", berat_acuan_kg="9990"
    )
    assert "Selisih" in teks_pdf(
        (await klien.get(f"{PREFIX}/transaksi/{pk}/cetak/80mm")).content)


async def test_riwayat_cetak_mencatat_formatnya(klien, app_uji):
    from sqlalchemy import select
    from app import database
    from app.timbangan.models import TimbanganCetak

    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")

    await klien.post(f"{PREFIX}/transaksi/{trx_id}/cetak",
                     data={"alasan": "", "format": "NCR"})
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/cetak",
                     data={"alasan": "Kertas tersangkut", "format": "80MM"})

    async with database.SessionLocal() as db:
        baris = list((await db.execute(
            select(TimbanganCetak).order_by(TimbanganCetak.urutan)
        )).scalars())
    assert [c.format for c in baris] == ["NCR", "80MM"]
    assert [c.ulang for c in baris] == [False, True]


async def test_format_asing_jatuh_ke_80mm(klien, app_uji):
    """Nilai yang tidak dikenal tidak boleh tersimpan apa adanya."""
    from sqlalchemy import select
    from app import database
    from app.timbangan.models import TimbanganCetak

    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/cetak",
                     data={"alasan": "", "format": "A4-PALSU"})

    async with database.SessionLocal() as db:
        c = (await db.execute(select(TimbanganCetak))).scalars().one()
    assert c.format == "80MM"


# ─────────────── Navigasi: bilah bawah di ponsel, sidebar di desktop ───────────────

def test_navigasi_berubah_bentuk_lewat_css_saja():
    """Satu markup, dua bentuk — bukan dua daftar tautan yang bisa menyimpang."""
    import pathlib

    akar = pathlib.Path(__file__).resolve().parents[2]
    css = (akar / "app/timbangan/static/app.css").read_text()
    html = (akar / "app/timbangan/templates/base.html").read_text()

    # Hanya SATU elemen navigasi di markup.
    assert html.count('<nav class="bawah">') == 1

    # Di layar lebar ia jadi sidebar, dan isi halaman bergeser menghindarinya.
    assert "@media (min-width: 900px)" in css
    sidebar = css.split("@media (min-width: 900px)")[1]
    assert "flex-direction: column" in sidebar
    assert "padding-left: var(--sidebar)" in sidebar


def test_rangka_desktop_terang_dan_sejajar():
    """Bilah atas terang, dan lebarnya sama persis dengan kolom isi.

    Dua hal yang mudah rusak: `.isi` memakai margin auto pada item flex, yang
    MEMBATALKAN stretch — tanpa `width: 100%` kolomnya menyusut mengikuti isi
    dan tidak lagi sejajar dengan bilah di atasnya.
    """
    import pathlib, re

    css = (pathlib.Path(__file__).resolve().parents[2]
           / "app/timbangan/static/app.css").read_text()
    desktop = css.split("@media (min-width: 900px)")[1]

    # Bar terang, bukan gelap seperti di ponsel.
    assert "background: var(--putih)" in desktop

    # Keduanya dibatasi pada lebar yang SAMA, dan keduanya width:100%.
    aturan = re.search(r"\.isi, \.bar__dalam \{([^}]*)\}", desktop).group(1)
    assert "width: 100%" in aturan
    assert "max-width: 820px" in aturan
    assert ".bingkai.lebar .isi, .bingkai.lebar .bar__dalam" in desktop


async def test_kepala_sidebar_ada_di_markup(klien):
    """Tersembunyi di ponsel lewat CSS, bukan lewat cabang di template."""
    await login(klien)
    teks = (await klien.get(f"{PREFIX}/")).text
    assert 'class="bawah__kepala"' in teks


# ─────────────── Mengubah pengguna ───────────────

async def akun_oleh(app_uji, username: str):
    from sqlalchemy import select
    from app import database

    async with database.SessionLocal() as db:
        return (await db.execute(
            select(TimbanganAkun).where(TimbanganAkun.username == username)
        )).scalars().one()


async def test_admin_bisa_mengubah_nama_peran_dan_perangkat(klien, app_uji):
    budi = await akun_oleh(app_uji, "budi")
    await login(klien, "wahid")

    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Budi Santoso", "username": "budi",
        "role": ROLE_ADMIN, "perangkat_kode": "p7", "sandi_baru": "",
    })
    assert "diubah" in r.text

    baru = await akun_oleh(app_uji, "budi")
    assert baru.nama == "Budi Santoso"
    assert baru.role == ROLE_ADMIN
    assert baru.perangkat_kode == "P7"          # dijadikan huruf besar


async def test_sandi_kosong_berarti_tidak_diubah(klien, app_uji):
    """Membetulkan ejaan nama tidak boleh diam-diam menghapus sandi orang."""
    sebelum = (await akun_oleh(app_uji, "budi")).password_hash
    await login(klien, "wahid")

    budi = await akun_oleh(app_uji, "budi")
    await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Budi B", "username": "budi", "role": ROLE_PETUGAS,
        "perangkat_kode": "P1", "sandi_baru": "",
    })
    assert (await akun_oleh(app_uji, "budi")).password_hash == sebelum


async def test_sandi_baru_benar_benar_dipakai_untuk_masuk(klien, app_uji):
    budi = await akun_oleh(app_uji, "budi")
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Budi", "username": "budi", "role": ROLE_PETUGAS,
        "perangkat_kode": "P1", "sandi_baru": "sandibaru9",
    })
    await klien.post(f"{PREFIX}/keluar")

    gagal = await klien.post(f"{PREFIX}/masuk", data={
        "username": "budi", "sandi": SANDI, "perangkat": "", "tujuan": ""})
    assert "Nama pengguna atau kata sandi salah" in gagal.text

    berhasil = await klien.post(f"{PREFIX}/masuk", data={
        "username": "budi", "sandi": "sandibaru9", "perangkat": "", "tujuan": ""})
    assert "Barang masuk" in berhasil.text


async def test_sandi_tidak_pernah_masuk_jejak_audit(klien, app_uji):
    from sqlalchemy import select
    from app import database
    from app.timbangan.models import TimbanganAudit

    budi = await akun_oleh(app_uji, "budi")
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Budi", "username": "budi", "role": ROLE_PETUGAS,
        "perangkat_kode": "P1", "sandi_baru": "rahasiabaru7",
    })
    async with database.SessionLocal() as db:
        jejak = (await db.execute(
            select(TimbanganAudit).where(TimbanganAudit.aksi == "UBAH_AKUN")
        )).scalars().one()
    semua = f"{jejak.ringkasan}{jejak.nilai_sebelum}{jejak.nilai_sesudah}"
    assert "rahasiabaru7" not in semua
    assert "diganti" in semua              # faktanya dicatat, isinya tidak


async def test_nama_pengguna_kembar_ditolak(klien, app_uji):
    budi = await akun_oleh(app_uji, "budi")
    await login(klien, "wahid")
    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Budi", "username": "wahid", "role": ROLE_PETUGAS,
        "perangkat_kode": "P1", "sandi_baru": "",
    })
    assert "sudah dipakai" in r.text
    assert (await akun_oleh(app_uji, "budi")).username == "budi"


async def test_admin_terakhir_tidak_bisa_menurunkan_perannya(klien, app_uji):
    """Kalau bisa, tidak akan ada lagi yang mampu mengelola pengguna."""
    wahid = await akun_oleh(app_uji, "wahid")
    await login(klien, "wahid")

    r = await klien.post(f"{PREFIX}/pengguna/{wahid.id}", data={
        "nama": "Wahid", "username": "wahid", "role": ROLE_PETUGAS,
        "perangkat_kode": "P0", "sandi_baru": "",
    })
    assert "satu-satunya Admin" in r.text
    assert (await akun_oleh(app_uji, "wahid")).role == ROLE_ADMIN


async def test_boleh_turun_peran_setelah_ada_admin_lain(klien, app_uji):
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengguna", data={
        "username": "admin2", "nama": "Admin Dua", "role": ROLE_ADMIN,
        "sandi": "rahasia123", "perangkat_kode": "P8",
    })
    wahid = await akun_oleh(app_uji, "wahid")
    r = await klien.post(f"{PREFIX}/pengguna/{wahid.id}", data={
        "nama": "Wahid", "username": "wahid", "role": ROLE_PETUGAS,
        "perangkat_kode": "P0", "sandi_baru": "",
    })
    # Turun peran sendiri langsung mencabut akses ke halaman pengguna, jadi
    # ia diantar ke Pengaturan beserta alasannya — bukan ke layar 403 kosong.
    assert r.status_code == 200
    assert "tidak lagi terbuka" in r.text
    assert (await akun_oleh(app_uji, "wahid")).role == ROLE_PETUGAS


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_bukan_admin_tidak_bisa_mengubah_akun(klien, app_uji, siapa):
    budi = await akun_oleh(app_uji, "budi")
    await login(klien, siapa)

    assert (await klien.get(f"{PREFIX}/pengguna/{budi.id}")).status_code == 403
    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Disusupi", "username": "budi", "role": ROLE_ADMIN,
        "perangkat_kode": "", "sandi_baru": "",
    })
    assert r.status_code == 403
    assert (await akun_oleh(app_uji, "budi")).nama == "Budi"


async def test_daftar_pengguna_barisnya_menunjuk_halaman_ubah(klien, app_uji):
    budi = await akun_oleh(app_uji, "budi")
    await login(klien, "wahid")
    r = await klien.get(f"{PREFIX}/pengguna")
    assert f'data-buka="{PREFIX}/pengguna/{budi.id}"' in r.text


async def test_halaman_ubah_menampilkan_nilai_sekarang(klien, app_uji):
    budi = await akun_oleh(app_uji, "budi")
    await login(klien, "wahid")
    r = await klien.get(f"{PREFIX}/pengguna/{budi.id}")
    assert r.status_code == 200
    assert 'value="budi"' in r.text
    assert "Nonaktifkan akun ini" in r.text


async def test_admin_tidak_bisa_menonaktifkan_akunnya_sendiri(klien, app_uji):
    wahid = await akun_oleh(app_uji, "wahid")
    await login(klien, "wahid")
    r = await klien.get(f"{PREFIX}/pengguna/{wahid.id}")
    assert "Nonaktifkan akun ini" not in r.text     # tombolnya tidak ada…

    r = await klien.post(f"{PREFIX}/pengguna/{wahid.id}/status")   # …dan
    assert "akun sendiri" in r.text                                # ditolak
    assert (await akun_oleh(app_uji, "wahid")).status == "aktif"


# ─────────────── Akun saya (semua peran) ───────────────

@pytest.mark.parametrize("siapa", ["budi", "miftah", "wahid"])
async def test_semua_peran_bisa_membuka_akun_sendiri(klien, siapa):
    await login(klien, siapa)
    r = await klien.get(f"{PREFIX}/akun")
    assert r.status_code == 200
    assert "Ganti sandi" in r.text


async def test_petugas_bisa_membetulkan_nama_dan_username_sendiri(klien, app_uji):
    await login(klien, "budi")
    r = await klien.post(f"{PREFIX}/akun", data={
        "nama": "Budi Santoso", "username": "budis",
        "sandi_lama": "", "sandi_baru": "",
    })
    assert "diubah" in r.text
    orang = await akun_oleh(app_uji, "budis")
    assert orang.nama == "Budi Santoso"


async def test_petugas_tidak_bisa_menaikkan_perannya_lewat_akun_sendiri(
    klien, app_uji
):
    """Formulirnya memang tidak punya kolom peran — pastikan mengirimkannya
    sendiri pun tidak berpengaruh."""
    await login(klien, "budi")
    await klien.post(f"{PREFIX}/akun", data={
        "nama": "Budi", "username": "budi", "sandi_lama": "", "sandi_baru": "",
        "role": ROLE_ADMIN, "perangkat_kode": "P0",
    })
    orang = await akun_oleh(app_uji, "budi")
    assert orang.role == ROLE_PETUGAS
    assert orang.perangkat_kode == "P1"


async def test_ganti_sandi_sendiri_menuntut_sandi_sekarang(klien, app_uji):
    """Perangkat pos dipakai bergantian dan tetap masuk sepanjang shift."""
    sebelum = (await akun_oleh(app_uji, "budi")).password_hash
    await login(klien, "budi")

    r = await klien.post(f"{PREFIX}/akun", data={
        "nama": "Budi", "username": "budi",
        "sandi_lama": "", "sandi_baru": "sandibaru9",
    })
    assert "sandi Anda yang sekarang" in r.text

    r = await klien.post(f"{PREFIX}/akun", data={
        "nama": "Budi", "username": "budi",
        "sandi_lama": "salahsekali", "sandi_baru": "sandibaru9",
    })
    assert "tidak cocok" in r.text
    assert (await akun_oleh(app_uji, "budi")).password_hash == sebelum

    r = await klien.post(f"{PREFIX}/akun", data={
        "nama": "Budi", "username": "budi",
        "sandi_lama": SANDI, "sandi_baru": "sandibaru9",
    })
    assert "diubah" in r.text
    assert (await akun_oleh(app_uji, "budi")).password_hash != sebelum


async def test_petugas_tidak_bisa_mengubah_akun_orang_lain_lewat_akun_saya(
    klien, app_uji
):
    """Rutenya tidak menerima id sama sekali — yang diubah selalu diri sendiri."""
    await login(klien, "budi")
    await klien.post(f"{PREFIX}/akun", data={
        "nama": "Bukan Miftah", "username": "budi",
        "sandi_lama": "", "sandi_baru": "", "akun_id": "2",
    })
    assert (await akun_oleh(app_uji, "miftah")).nama == "Miftah"


# ─────────────── Catatan orang lain ───────────────

async def test_petugas_tetap_bisa_membuka_hasil_timbangannya_sendiri(klien):
    """Justru ke halaman inilah ia dikembalikan selesai menimbang, dan dari
    sini pula notanya dicetak — menutupnya akan mematikan alur kerja."""
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    r = await klien.get(f"{PREFIX}/transaksi/{trx_id}")
    assert r.status_code == 200
    assert f"/transaksi/{trx_id}/cetak" in r.text


@pytest.mark.parametrize("siapa", ["sari", "miftah"])
async def test_catatan_orang_lain_tertutup_meski_nomornya_ditebak(
    klien, app_uji, siapa
):
    """Menutup daftar saja tidak cukup: nomor transaksi di URL berurutan."""
    from app import database
    from app.timbangan.models import ROLE_PETUGAS, TimbanganAkun
    from app.timbangan.security import hash_sandi

    async with database.SessionLocal() as db:
        db.add(TimbanganAkun(
            username="sari", nama="Sari", role=ROLE_PETUGAS,
            password_hash=hash_sandi(SANDI), perangkat_kode="P2",
        ))
        await db.commit()

    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, siapa)
    for jalur in (
        f"/transaksi/{trx_id}",
        f"/transaksi/{trx_id}/cetak",
        f"/transaksi/{trx_id}/cetak/ncr",
        f"/transaksi/{trx_id}/cetak/80mm",
    ):
        r = await klien.get(PREFIX + jalur)
        assert r.status_code == 403, jalur
        assert "bukan hasil timbangan Anda" in r.text


async def test_admin_tetap_bisa_membuka_catatan_siapa_pun(klien):
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, "wahid")
    assert (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).status_code == 200
    assert (await klien.get(f"{PREFIX}/transaksi")).status_code == 200


async def test_beranda_petugas_hanya_memuat_timbangannya_sendiri(klien, app_uji):
    """Kalau tidak, berandanya penuh tautan yang berujung 'akses ditolak'."""
    await login(klien, "budi")
    kode_budi = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, "miftah")
    beranda = (await klien.get(f"{PREFIX}/")).text
    assert f"/transaksi/{kode_budi}" not in beranda
    assert "Timbangan saya hari ini" in beranda

    await klien.post(f"{PREFIX}/keluar")
    await login(klien, "wahid")
    assert f"/transaksi/{kode_budi}" in (await klien.get(f"{PREFIX}/")).text


# ─────────────── Menghapus pengguna ───────────────

async def test_akun_belum_terpakai_bisa_dihapus(klien, app_uji):
    from sqlalchemy import select

    from app import database

    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengguna", data={
        "username": "salahketik", "nama": "Salah Ketik", "role": ROLE_PETUGAS,
        "sandi": "rahasia123", "perangkat_kode": "P8",
    })
    orang = await akun_oleh(app_uji, "salahketik")

    r = await klien.post(f"{PREFIX}/pengguna/{orang.id}/hapus",
                         data={"ketik_username": "salahketik"})
    assert "dihapus" in r.text

    async with database.SessionLocal() as db:
        sisa = (await db.execute(
            select(TimbanganAkun).where(TimbanganAkun.username == "salahketik")
        )).scalars().first()
    assert sisa is None


async def test_menghapus_menuntut_nama_penggunanya_diketik(klien, app_uji):
    """Kotak "yakin?" dijawab refleks; mengetik nama tidak bisa."""
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengguna", data={
        "username": "coba", "nama": "Coba", "role": ROLE_PETUGAS,
        "sandi": "rahasia123", "perangkat_kode": "",
    })
    orang = await akun_oleh(app_uji, "coba")

    for salah in ("", "cob", "Coba Salah"):
        r = await klien.post(f"{PREFIX}/pengguna/{orang.id}/hapus",
                             data={"ketik_username": salah})
        assert "ketik nama penggunanya persis: coba" in r.text
    assert await akun_oleh(app_uji, "coba") is not None


async def test_akun_yang_sudah_menimbang_tidak_bisa_dihapus(klien, app_uji):
    """Namanya melekat pada catatan timbang — menghapusnya memalsukan catatan."""
    await login(klien, "budi")
    await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    budi = await akun_oleh(app_uji, "budi")
    await login(klien, "wahid")
    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}/hapus",
                         data={"ketik_username": "budi"})
    assert "riwayat kerja" in r.text
    assert "Nonaktifkan saja" in r.text
    assert await akun_oleh(app_uji, "budi") is not None


async def test_jejak_audit_tetap_terbaca_setelah_akunnya_dihapus(klien, app_uji):
    """Penunjuknya dilepas, tapi `akun_nama` sudah tersimpan sejak awal."""
    from sqlalchemy import select

    from app import database
    from app.timbangan.models import TimbanganAudit

    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengguna", data={
        "username": "sebentar", "nama": "Sebentar Saja", "role": ROLE_PETUGAS,
        "sandi": "rahasia123", "perangkat_kode": "",
    })
    orang = await akun_oleh(app_uji, "sebentar")
    orang_id = orang.id
    await klien.post(f"{PREFIX}/pengguna/{orang_id}/hapus",
                     data={"ketik_username": "sebentar"})

    async with database.SessionLocal() as db:
        jejak = list((await db.execute(
            select(TimbanganAudit).where(TimbanganAudit.aksi == "HAPUS_AKUN")
        )).scalars())
    assert len(jejak) == 1
    assert "sebentar" in jejak[0].ringkasan
    assert jejak[0].akun_nama == "Wahid"          # pelakunya tetap tercatat


async def test_admin_tidak_bisa_menghapus_akunnya_sendiri(klien, app_uji):
    wahid = await akun_oleh(app_uji, "wahid")
    await login(klien, "wahid")
    r = await klien.post(f"{PREFIX}/pengguna/{wahid.id}/hapus",
                         data={"ketik_username": "wahid"})
    assert "akun sendiri" in r.text
    assert await akun_oleh(app_uji, "wahid") is not None


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_bukan_admin_tidak_bisa_menghapus_akun(klien, app_uji, siapa):
    budi = await akun_oleh(app_uji, "budi")
    await login(klien, siapa)
    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}/hapus",
                         data={"ketik_username": "budi"})
    assert r.status_code == 403
    assert await akun_oleh(app_uji, "budi") is not None


# ─────────────── Kode perangkat lepas dari layar masuk ───────────────

async def test_layar_masuk_tidak_lagi_meminta_kode_perangkat(klien):
    r = await klien.get(f"{PREFIX}/masuk")
    assert 'name="perangkat"' not in r.text
    assert "Kode perangkat" not in r.text


async def test_masuk_tidak_bisa_mengambil_alih_kode_perangkat_orang_lain(
    klien, app_uji
):
    """Dulu siapa pun bisa mengetik kode milik perangkat lain saat masuk, dan
    deret nomor transaksi ikut berpindah — persis bentrokan yang hendak
    dicegah kode itu."""
    await klien.post(f"{PREFIX}/masuk", data={
        "username": "budi", "sandi": SANDI, "perangkat": "P9", "tujuan": "",
    })
    assert (await akun_oleh(app_uji, "budi")).perangkat_kode == "P1"
    assert (await akun_oleh(app_uji, "miftah")).perangkat_kode == "P9"


# ─────────────── Barang masuk: jumlah karung sebelum diselesaikan ───────────

async def _tiket_terbuka(klien, jenis: str, **beda) -> int:
    """Timbang pertama saja — tiketnya sengaja dibiarkan terbuka."""
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    data = {
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 5 BB", "jumlah_karung": "",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "N-1",
        "nama_sopir": "Slamet", "pihak_nama": "",
    }
    data.update(beda)
    await klien.post(f"{PREFIX}/timbang/{jenis}", data=data)
    tiket = await klien.get(f"{PREFIX}/tiket")
    return int(re.search(r"/tiket/(\d+)", tiket.text).group(1))


async def trx_oleh_id(trx_id: int):
    from app import database
    from app.timbangan.models import TimbanganTransaksi

    async with database.SessionLocal() as db:
        return await db.get(TimbanganTransaksi, trx_id)


async def test_barang_masuk_tidak_bisa_selesai_tanpa_jumlah_karung(klien):
    """Seluruh komoditas masuk bertara per karung — tanpa angka itu selisihnya
    keliru, dan statusnya tersimpan permanen serta terbawa ke ekspor."""
    await login(klien)
    trx_id = await _tiket_terbuka(klien, "GABAH_BASAH")

    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    assert "Jumlah karung belum diisi" in r.text

    trx = await trx_oleh_id(trx_id)
    assert trx.status_tiket == TIKET_TERBUKA
    assert trx.timbang2_kg is None


async def test_simpan_sementara_menyimpan_angka_tanpa_menutup_tiket(klien):
    await login(klien)
    trx_id = await _tiket_terbuka(klien, "GABAH_BASAH")

    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "sementara",
    })
    assert "Tiket masih terbuka" in r.text

    trx = await trx_oleh_id(trx_id)
    assert trx.timbang2_kg == 3570          # angkanya aman dari HP mati
    assert trx.status_tiket == TIKET_TERBUKA
    assert trx.status_kontrol is None       # belum dihitung — dan tidak boleh
    assert not trx.selisih_kg


async def test_simpan_sementara_lalu_diselesaikan_setelah_karung_pasti(klien):
    await login(klien)
    trx_id = await _tiket_terbuka(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "sementara",
    })
    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "nomor_acuan": "N-1", "waktu": "", "catatan": "", "aksi": "selesai",
    })
    assert "selesai dan tersimpan" in r.text

    trx = await trx_oleh_id(trx_id)
    assert trx.status_tiket == TIKET_SELESAI
    assert trx.status_kontrol is not None


async def test_angka_yang_disimpan_sementara_muncul_lagi_di_formulir(klien):
    """Kalau tidak, petugas harus mengingat sendiri angka yang tadi diketik."""
    await login(klien)
    trx_id = await _tiket_terbuka(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "sementara",
    })
    form = (await klien.get(f"{PREFIX}/tiket/{trx_id}")).text
    assert 'name="berat_kg"' in form
    assert 'value="3570"' in form


async def test_simpan_sementara_tercatat_di_audit(klien):
    from sqlalchemy import select

    from app import database
    from app.timbangan.models import TimbanganAudit

    await login(klien)
    trx_id = await _tiket_terbuka(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "sementara",
    })
    async with database.SessionLocal() as db:
        jejak = (await db.execute(
            select(TimbanganAudit).where(
                TimbanganAudit.aksi == "SIMPAN_SEMENTARA")
        )).scalars().one()
    assert "tiket tetap terbuka" in jejak.ringkasan


async def test_pengiriman_tetap_bisa_selesai_tanpa_jumlah_karung(klien):
    """Pagarnya khusus barang masuk — alur pengiriman tidak ikut berubah."""
    await login(klien)
    trx_id = await _tiket_terbuka(klien, "BERAS", berat_kg="4200")
    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "13600", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    assert "selesai dan tersimpan" in r.text
    assert (await trx_oleh_id(trx_id)).status_tiket == TIKET_SELESAI


async def test_tombol_simpan_sementara_hanya_untuk_barang_masuk(klien):
    await login(klien)
    masuk = await _tiket_terbuka(klien, "GABAH_BASAH")
    assert "Simpan sementara" in (await klien.get(f"{PREFIX}/tiket/{masuk}")).text

    keluar = await _tiket_terbuka(klien, "BERAS", berat_kg="4200")
    assert "Simpan sementara" not in (
        await klien.get(f"{PREFIX}/tiket/{keluar}")).text


# ─────────────── Super Admin ───────────────

async def _jadi_super(app_uji, username: str = "wahid"):
    from app import database

    async with database.SessionLocal() as db:
        orang = await akun_oleh(app_uji, username)
        orang = await db.get(TimbanganAkun, orang.id)
        orang.role = ROLE_SUPERADMIN
        await db.commit()


async def test_transaksi_dibatalkan_tetap_tertera_di_catatan(klien, app_uji):
    """Truk yang batal bongkar memang pernah datang."""
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/batal",
                     data={"alasan": "Mutu ditolak"})
    daftar = (await klien.get(f"{PREFIX}/transaksi")).text
    assert f"/transaksi/{trx_id}" in daftar
    assert "Batal" in daftar


async def test_admin_biasa_tidak_bisa_menghapus_catatan(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, "wahid")
    rincian = (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    assert "Hapus permanen" not in rincian          # tombolnya tidak ada…

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/hapus", data={
        "alasan": "coba", "ketik_kode": "TRX-20260830-P1-001"})
    assert r.status_code == 403                     # …dan pintunya tertutup
    assert await trx_oleh_id(trx_id) is not None


async def test_super_admin_bisa_menghapus_catatan(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    kode = (await trx_oleh_id(trx_id)).kode

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/hapus", data={
        "alasan": "Salah entri saat uji coba", "ketik_kode": kode})
    assert "dihapus permanen" in r.text
    assert await trx_oleh_id(trx_id) is None


async def test_menghapus_catatan_menuntut_kode_dan_alasan(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    kode = (await trx_oleh_id(trx_id)).kode

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/hapus", data={
        "alasan": "apa saja", "ketik_kode": "TRX-SALAH"})
    assert "ketik nomor transaksinya persis" in r.text

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/hapus", data={
        "alasan": "   ", "ketik_kode": kode})
    assert "disertai alasan" in r.text
    assert await trx_oleh_id(trx_id) is not None


async def test_jejak_audit_menyimpan_salinan_penuh_catatan_yang_dihapus(
    klien, app_uji
):
    """Sebuah catatan boleh hilang dari daftar, tidak dari sejarah."""
    from sqlalchemy import select

    from app import database
    from app.timbangan.models import TimbanganAudit

    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    kode = (await trx_oleh_id(trx_id)).kode
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/hapus", data={
        "alasan": "Salah entri saat uji coba", "ketik_kode": kode})

    async with database.SessionLocal() as db:
        jejak = (await db.execute(
            select(TimbanganAudit).where(
                TimbanganAudit.aksi == "HAPUS_TRANSAKSI")
        )).scalars().one()
    assert kode in jejak.ringkasan
    assert "Salah entri saat uji coba" in jejak.ringkasan
    assert '"timbang1_kg": 13600' in jejak.nilai_sebelum
    assert '"jumlah_karung": 120' in jejak.nilai_sebelum


async def test_super_admin_punya_semua_wewenang_admin(klien, app_uji):
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    for jalur in ("/transaksi", "/laporan", "/monitoring", "/pengguna",
                  "/tara", "/aturan", "/pengaturan"):
        assert (await klien.get(PREFIX + jalur)).status_code == 200, jalur


# ── Pemisahan perannya tidak boleh bisa dilangkahi ──

async def test_admin_bisa_mengangkat_super_admin_pertama(klien, app_uji):
    """Harus ada jalan membuat yang pertama — dan memulihkan bila hilang."""
    await login(klien, "wahid")
    budi = await akun_oleh(app_uji, "budi")
    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Budi", "username": "budi", "role": ROLE_SUPERADMIN,
        "perangkat_kode": "P1", "sandi_baru": "",
    })
    assert "diubah" in r.text
    assert (await akun_oleh(app_uji, "budi")).role == ROLE_SUPERADMIN


async def test_setelah_ada_super_admin_pintunya_tertutup_bagi_admin(
    klien, app_uji
):
    """Kalau tidak, Admin mana pun tinggal mengangkat dirinya sendiri.

    Sejak pengelolaan pengguna menjadi wewenang Super Admin, Admin bahkan
    tidak sampai ke formulirnya — ditolak di pintu, bukan di isian.
    """
    await _jadi_super(app_uji, "miftah")
    await login(klien, "wahid")
    budi = await akun_oleh(app_uji, "budi")

    assert (await klien.get(f"{PREFIX}/pengguna")).status_code == 403
    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Budi", "username": "budi", "role": ROLE_SUPERADMIN,
        "perangkat_kode": "P1", "sandi_baru": "",
    })
    assert r.status_code == 403
    assert (await akun_oleh(app_uji, "budi")).role == ROLE_PETUGAS


@pytest.mark.parametrize("jalur,data", [
    ("", {"nama": "Diambil Alih", "username": "miftah",
          "role": ROLE_ADMIN, "perangkat_kode": "", "sandi_baru": ""}),
    ("/status", {}),
    ("/hapus", {"ketik_username": "miftah"}),
])
async def test_admin_tidak_bisa_menyentuh_akun_super_admin(
    klien, app_uji, jalur, data
):
    """Termasuk menonaktifkannya lalu mengangkat dirinya sendiri."""
    await _jadi_super(app_uji, "miftah")
    await login(klien, "wahid")
    orang = await akun_oleh(app_uji, "miftah")

    r = await klien.post(f"{PREFIX}/pengguna/{orang.id}{jalur}", data=data)
    assert r.status_code == 403

    tetap = await akun_oleh(app_uji, "miftah")
    assert tetap.role == ROLE_SUPERADMIN
    assert tetap.status == "aktif"
    assert tetap.nama == "Miftah"


async def test_admin_tidak_bisa_membuat_super_admin_baru_lewat_pintu_lain(
    klien, app_uji
):
    """Kalau bisa, cukup buat akun Super Admin baru lalu masuk dengannya."""
    await _jadi_super(app_uji, "miftah")
    await login(klien, "wahid")
    r = await klien.post(f"{PREFIX}/pengguna", data={
        "username": "pintubelakang", "nama": "Pintu Belakang",
        "role": ROLE_SUPERADMIN, "sandi": "rahasia123", "perangkat_kode": "",
    })
    assert r.status_code == 403

    from sqlalchemy import select

    from app import database
    async with database.SessionLocal() as db:
        assert (await db.execute(select(TimbanganAkun).where(
            TimbanganAkun.username == "pintubelakang"))).scalars().first() is None


async def test_peran_karangan_ditolak_saat_membuat_akun(klien, app_uji):
    await login(klien, "wahid")
    r = await klien.post(f"{PREFIX}/pengguna", data={
        "username": "aneh", "nama": "Aneh", "role": "DEWA",
        "sandi": "rahasia123", "perangkat_kode": "",
    })
    assert "tidak dikenal" in r.text


async def test_super_admin_menghapus_akun_tanpa_menghapus_catatannya(
    klien, app_uji
):
    """Keputusan Direksi: catatannya tetap, namanya saja yang dikosongkan."""
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    budi = await akun_oleh(app_uji, "budi")
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}/hapus",
                         data={"ketik_username": "budi"})
    assert "dihapus" in r.text

    trx = await trx_oleh_id(trx_id)
    assert trx is not None                      # catatannya utuh…
    assert trx.timbang1_kg == 13600
    assert trx.status_kontrol is not None
    assert trx.timbang1_petugas_id is None      # …namanya saja yang lepas
    assert trx.timbang2_petugas_id is None


async def test_jejak_audit_masih_menjawab_siapa_setelah_akunnya_dihapus(
    klien, app_uji
):
    """Satu-satunya tempat yang masih bisa menyebut pelakunya."""
    from sqlalchemy import select

    from app import database
    from app.timbangan.models import TimbanganAudit

    await login(klien, "budi")
    await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    budi = await akun_oleh(app_uji, "budi")
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengguna/{budi.id}/hapus",
                     data={"ketik_username": "budi"})

    async with database.SessionLocal() as db:
        timbang = (await db.execute(
            select(TimbanganAudit).where(
                TimbanganAudit.aksi == "SIMPAN_TIMBANG_2")
        )).scalars().one()
        hapus = (await db.execute(
            select(TimbanganAudit).where(TimbanganAudit.aksi == "HAPUS_AKUN")
        )).scalars().one()

    assert timbang.akun_id is None
    assert timbang.akun_nama == "Budi"                   # namanya tetap terbaca
    assert "nama dikosongkan dari" in hapus.ringkasan
    assert "timbangan_transaksi.timbang1_petugas_id" in hapus.ringkasan


# ─────────────── Transfer internal ───────────────

async def test_beranda_menawarkan_transfer_internal(klien):
    await login(klien)
    beranda = (await klien.get(f"{PREFIX}/")).text
    assert "Transfer internal" in beranda
    # Satu jenis saja, jadi langsung ke formulirnya.
    assert f"{PREFIX}/timbang/TRANSFER" in beranda


async def test_transfer_internal_timbang_bermuatan_lalu_kosong(klien):
    """Armada datang bermuatan dan ditimbang ulang setelah dibongkar —
    urutannya sama seperti barang masuk."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/TRANSFER")).text
    assert "Berat truk bermuatan" in form
    assert "Asal → tujuan" in form

    await klien.post(f"{PREFIX}/timbang/TRANSFER", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "",
        "pihak_nama": "Gudang 1 → Gudang 2", "nomor_polisi": "AD 7 CC",
        "nama_sopir": "Slamet", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))

    form2 = (await klien.get(f"{PREFIX}/tiket/{trx_id}")).text
    assert "Berat truk kosong" in form2

    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3600", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    assert "selesai dan tersimpan" in r.text

    trx = await trx_oleh_id(trx_id)
    assert trx.status_tiket == TIKET_SELESAI
    assert trx.berat_bermuatan_kg == 13600
    assert trx.berat_kosong_kg == 3600
    assert trx.netto_timbangan_kg == 10000
    assert trx.pihak_nama == "Gudang 1 → Gudang 2"


async def test_transfer_internal_tanpa_dokumen_pembanding(klien):
    """Keputusan Direksi: cukup dicatat berapa yang berpindah.

    Kolom dokumen tidak ditampilkan — menyediakannya hanya mengundang angka
    yang tidak akan pernah dipakai.
    """
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/TRANSFER")).text
    assert "Nota supplier" not in form
    assert "Surat jalan" not in form
    assert 'name="jumlah_karung"' in form        # muatan tetap boleh dicatat

    await klien.post(f"{PREFIX}/timbang/TRANSFER", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "",
        "pihak_nama": "Gudang 1 → Gudang 2", "nomor_polisi": "AD 7 CC",
        "nama_sopir": "Slamet", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    form2 = (await klien.get(f"{PREFIX}/tiket/{trx_id}")).text
    assert "Berat menurut dokumen" not in form2


async def test_transfer_internal_tidak_terkena_pagar_jumlah_karung(klien):
    """Pagar itu khusus barang masuk, yang taranya memang per karung."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/TRANSFER")).text
    await klien.post(f"{PREFIX}/timbang/TRANSFER", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "",
        "pihak_nama": "Gudang 1 → Gudang 2", "nomor_polisi": "AD 7 CC",
        "nama_sopir": "Slamet", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3600", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    assert "Jumlah karung belum diisi" not in r.text
    assert (await trx_oleh_id(trx_id)).status_tiket == TIKET_SELESAI
    assert "Simpan sementara" not in (
        await klien.get(f"{PREFIX}/timbang/TRANSFER")).text


async def test_unduh_csv_dibuka_di_jendela_terpisah(klien):
    """Di PWA terpasang tidak ada bilah peramban. Menautkan langsung ke
    berkas membuat iOS menggantikan seluruh layar dengan pratinjau yang hanya
    menawarkan "Open in…" — aplikasi harus ditutup paksa."""
    await login(klien, "wahid")
    for jalur in ("/transaksi", "/laporan"):
        teks = (await klien.get(PREFIX + jalur)).text
        # Atribut tautannya ditulis sebelum href, jadi diperiksa dari
        # potongan tepat di depan alamatnya.
        potongan = teks[max(0, teks.index("ekspor.csv") - 200):
                        teks.index("ekspor.csv")]
        # data-unduh: diambil di latar lalu diserahkan ke lembar Bagikan,
        # supaya halaman tidak pernah ditinggalkan. target="_blank" hanya
        # jalan terakhir bila JS tidak jalan.
        assert "data-unduh" in potongan, jalur
        assert 'target="_blank"' in potongan, jalur
        assert "download" in potongan, jalur


async def test_ekspor_menyebut_nama_berkasnya_di_header(klien):
    """Nama berkas dibaca dari jawaban server oleh app.js — bukan disusun
    ulang di sisi peramban, supaya hanya ada satu tempat yang menentukannya."""
    await login(klien, "wahid")
    r = await klien.get(f"{PREFIX}/ekspor.csv?dari=2026-08-01&sampai=2026-08-30")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == (
        'attachment; filename="timbangan-20260801-20260830.csv"'
    )


# ─────────────── Nomor polisi wajib ───────────────

@pytest.mark.parametrize("jenis", ["GABAH_BASAH", "BERAS"])
async def test_masuk_dan_keluar_menolak_tanpa_nomor_polisi(klien, jenis):
    """Keduanya melibatkan pihak luar, jadi catatannya harus bisa menunjuk
    kendaraan tertentu bila kelak ada sengketa."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    r = await klien.post(f"{PREFIX}/timbang/{jenis}", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1", "nomor_polisi": "  ",
        "nama_sopir": "Slamet", "jumlah_karung": "120", "tara_per_karung_kg": "0,25",
        "berat_acuan_kg": "10000", "nomor_acuan": "N-1", "tara_lain_kg": "0",
        "waktu": "", "catatan": "", "pihak_nama": "",
    })
    assert "Nomor polisi wajib diisi" in r.text
    assert "0 transaksi" in (await klien.get(f"{PREFIX}/tiket")).text \
        or "Tidak ada" in (await klien.get(f"{PREFIX}/tiket")).text


@pytest.mark.parametrize("jenis", ["GABAH_BASAH", "BERAS"])
async def test_isiannya_ditandai_wajib_di_layar(klien, jenis):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    potongan = form[form.index('name="nomor_polisi"') - 300:
                    form.index('name="nomor_polisi"') + 300]
    assert "required" in potongan
    assert "Nomor polisi (boleh kosong)" not in form


@pytest.mark.parametrize("jenis,arah", [("BEBAS", "jasa timbang"),
                                        ("TRANSFER", "transfer internal")])
async def test_jasa_timbang_dan_transfer_tetap_boleh_tanpa_nomor_polisi(
    klien, jenis, arah
):
    """Keduanya tidak selalu memakai kendaraan bernomor."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    r = await klien.post(f"{PREFIX}/timbang/{jenis}", data={
        "kode": kode_dari(form), "berat_kg": "12850",
        "cara_timbang": "SEKALI" if jenis == "BEBAS" else "DUA_KALI",
        "supplier_id": "", "pihak_nama": "CV Sumber Rejeki",
        "nomor_polisi": "", "nama_sopir": "Slamet", "jumlah_karung": "",
        "tara_per_karung_kg": "", "berat_acuan_kg": "", "nomor_acuan": "",
        "tara_lain_kg": "0", "waktu": "", "catatan": "",
    })
    assert "Nomor polisi wajib" not in r.text, arah


async def test_koreksi_tidak_bisa_mengosongkan_nomor_polisi(klien):
    """Pada formulir koreksi, kolom kosong berarti "tidak diubah" — bukan
    "kosongkan". Jadi nomor polisinya tidak mungkin hilang lewat jalan ini."""
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/koreksi", data={
        "alasan": "Salah ketik", "timbang1_kg": "", "timbang2_kg": "",
        "nomor_polisi": "", "nama_sopir": "Slamet", "supplier_id": "",
        "jumlah_karung": "", "tara_per_karung_kg": "", "berat_acuan_kg": "",
        "nomor_acuan": "", "catatan": "",
    })
    assert "wajib" not in r.text
    assert (await trx_oleh_id(trx_id)).nomor_polisi == "AD 5 BB"


# ─────────────── Jejak audit ───────────────

@pytest.mark.parametrize("siapa", ["budi", "miftah", "wahid"])
async def test_jejak_audit_tertutup_bagi_selain_super_admin(klien, siapa):
    """Termasuk bagi Admin. Halaman ini mengawasi wewenang menghapus, jadi
    yang membacanya jangan sama dengan yang memakainya sehari-hari."""
    await login(klien, siapa)
    r = await klien.get(f"{PREFIX}/audit")
    assert r.status_code == 403
    assert "hanya untuk Super Admin" in r.text


async def test_super_admin_melihat_jejak_penimbangan(klien, app_uji):
    await login(klien, "budi")
    await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/audit")).text
    assert "SIMPAN_TIMBANG_1" in teks
    assert "SIMPAN_TIMBANG_2" in teks
    assert "Budi" in teks                       # pelakunya tertera


async def test_jejak_audit_bisa_disaring(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/batal",
                     data={"alasan": "Mutu ditolak"})

    # Hanya isi tabelnya yang diperiksa: daftar saringannya sendiri memuat
    # setiap nama aksi, jadi mencari di seluruh halaman selalu ketemu.
    async def isi_tabel(query: str) -> str:
        teks = (await klien.get(f"{PREFIX}/audit?{query}")).text
        return teks[teks.index("<tbody>"):teks.index("</tbody>")]

    hanya_void = await isi_tabel("aksi=VOID")
    assert "VOID" in hanya_void
    assert "SIMPAN_TIMBANG_1" not in hanya_void

    budi = await akun_oleh(app_uji, "budi")
    punya_budi = await isi_tabel(f"oleh={budi.id}")
    assert "SIMPAN_TIMBANG_1" in punya_budi
    assert "VOID" not in punya_budi              # itu pekerjaan Wahid

    kode = (await trx_oleh_id(trx_id)).kode
    assert kode in await isi_tabel(f"cari={kode}")


async def test_jejak_audit_menyebut_nama_pemilik_akun_yang_sudah_dihapus(
    klien, app_uji
):
    """Inilah satu-satunya tempat yang masih bisa menjawab siapa pelakunya."""
    await login(klien, "budi")
    await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    budi = await akun_oleh(app_uji, "budi")
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengguna/{budi.id}/hapus",
                     data={"ketik_username": "budi"})

    teks = (await klien.get(f"{PREFIX}/audit")).text
    assert "Budi" in teks
    assert "akun dihapus" in teks


async def test_jejak_audit_menampilkan_angka_sebelum_diubah(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/koreksi", data={
        "alasan": "Salah baca timbangan", "timbang1_kg": "13500",
        "timbang2_kg": "", "nomor_polisi": "", "nama_sopir": "Slamet",
        "supplier_id": "", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "catatan": "",
    })
    await klien.post(f"{PREFIX}/keluar")

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/audit?aksi=KOREKSI")).text
    assert "13600" in teks and "13500" in teks   # sebelum dan sesudah
    assert "timbang1 kg" in teks                 # kuncinya dibaca manusia


async def test_jejak_audit_tidak_punya_pintu_ubah_atau_hapus(klien, app_uji):
    """Hanya bertambah. Tidak ada rute yang bisa menyentuhnya."""
    from fastapi.routing import APIRoute

    await _jadi_super(app_uji)
    jalur = [r.path for r in app_uji.routes
             if isinstance(r, APIRoute) and "audit" in r.path]
    assert jalur == [f"{PREFIX}/audit"]
    for r in app_uji.routes:
        if isinstance(r, APIRoute) and "audit" in r.path:
            assert r.methods == {"GET"}


# ─────────────── Pengguna & setelan: Super Admin saja ───────────────

@pytest.mark.parametrize("jalur,metode", [
    ("/pengguna", "get"), ("/pengguna", "post"), ("/pengaturan", "post"),
])
async def test_admin_biasa_tidak_lagi_mengelola_pengguna_dan_setelan(
    klien, app_uji, jalur, metode
):
    await _jadi_super(app_uji, "miftah")
    await login(klien, "wahid")
    r = await getattr(klien, metode)(
        PREFIX + jalur,
        **({"data": {"kunci": "maks_foto_mb", "nilai": "8", "aksi": "simpan",
                     "username": "x", "nama": "X", "role": ROLE_PETUGAS,
                     "sandi": "rahasia123", "perangkat_kode": ""}}
           if metode == "post" else {}),
    )
    assert r.status_code == 403


async def test_setelan_terbaca_admin_tapi_tanpa_kotak_isian(klien, app_uji):
    """Admin tetap perlu tahu batas yang berlaku — hanya tidak mengubahnya."""
    await _jadi_super(app_uji, "miftah")
    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert "20.000" in teks
    assert "wewenang Super Admin" in teks
    assert 'name="kunci"' not in teks            # formulirnya tidak ada


async def test_admin_diantar_ke_pengaturan_setelah_mengangkat_super_pertama(
    klien, app_uji
):
    """Pintunya menutup di belakangnya — jangan sampai berakhir di layar
    "akses ditolak" seolah perubahannya gagal."""
    await login(klien, "wahid")
    budi = await akun_oleh(app_uji, "budi")
    r = await klien.post(f"{PREFIX}/pengguna/{budi.id}", data={
        "nama": "Budi", "username": "budi", "role": ROLE_SUPERADMIN,
        "perangkat_kode": "P1", "sandi_baru": "",
    })
    assert r.status_code == 200
    assert "tertutup bagi Anda" in r.text
    assert (await akun_oleh(app_uji, "budi")).role == ROLE_SUPERADMIN


# ─────────────── Menu navigasi ───────────────

def _menu_aktif(teks: str) -> list[str]:
    """Nama menu yang menyala pada satu halaman."""
    blok = teks[teks.index('class="bawah__isi"'):teks.index("</nav>")]
    return [
        # Buang ikon SVG-nya; yang dibandingkan namanya, bukan gambarnya.
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", potongan)).strip()
        for potongan in re.findall(
            r'class="aktif"[^>]*>(.*?)</a>', blok, re.S
        )
    ]


@pytest.mark.parametrize("jalur,menu", [
    ("/", "Beranda"),
    ("/tiket", "Tiket"),
    ("/transaksi", "Catatan"),
    ("/laporan", "Ringkasan"),
    ("/monitoring", "Ringkasan"),
    ("/pengaturan", "Pengaturan"),
    ("/aturan", "Pengaturan"),
    ("/tara", "Pengaturan"),
    ("/pengguna", "Pengaturan"),
    ("/akun", "Pengaturan"),
    ("/audit", "Pengaturan"),
])
async def test_menu_menyala_di_halaman_yang_sedang_dibuka(
    klien, app_uji, jalur, menu
):
    """Dulu menu Catatan tidak pernah menyala: rutenya mengirim nomor halaman
    paginasi dengan nama variabel yang sama seperti nama layar, dan nomor itu
    menimpanya tanpa suara. Diuji untuk SEMUA menu, bukan yang itu saja —
    tabrakan nama seperti ini tidak mengumumkan dirinya."""
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    r = await klien.get(PREFIX + jalur)
    assert r.status_code == 200, jalur
    assert _menu_aktif(r.text) == [menu], jalur


async def test_menu_catatan_tetap_menyala_di_halaman_kedua(klien, app_uji):
    """Justru di sinilah dulu bug-nya paling terlihat."""
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    r = await klien.get(f"{PREFIX}/transaksi?hal=2")
    assert _menu_aktif(r.text) == ["Catatan"]


async def test_menu_catatan_menyala_di_rincian_dan_koreksi(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    for jalur in (f"/transaksi/{trx_id}", f"/transaksi/{trx_id}/koreksi"):
        assert _menu_aktif((await klien.get(PREFIX + jalur)).text) == ["Catatan"], jalur


# ─────────────── Waktu yang diketik operator ───────────────

def test_waktu_operator_selalu_berzona():
    """Isian datetime-local mengirim angka polos tanpa zona, dan angka itu
    adalah WIB. Diserahkan apa adanya ke kolom timestamptz, Postgres
    menafsirkannya sebagai UTC — tepat tujuh jam meleset.

    Diuji di tingkat fungsi, bukan lewat HTTP, justru karena SQLite
    menyembunyikan kesalahannya: ia menyimpan tanpa zona sehingga angkanya
    kembali apa adanya. Hanya Postgres yang memperlihatkannya, yaitu hanya
    di produksi.
    """
    from zoneinfo import ZoneInfo

    from app.timbangan.routes.pos import _waktu_operator

    hasil = _waktu_operator("2026-08-31T09:15")
    assert hasil is not None
    assert hasil.tzinfo is not None, "waktu tanpa zona akan dibaca sebagai UTC"
    assert hasil.utcoffset().total_seconds() == 7 * 3600
    assert hasil.astimezone(ZoneInfo("UTC")).hour == 2   # 09:15 WIB = 02:15 UTC


def test_waktu_operator_kosong_atau_ngawur_jatuh_ke_jam_sistem():
    from app.timbangan.routes.pos import _waktu_operator

    assert _waktu_operator("") is None
    assert _waktu_operator(None) is None
    assert _waktu_operator("bukan waktu") is None


async def test_jam_yang_diketik_petugas_tampil_sama_persis(klien):
    """Yang diketik 09:15 harus terbaca 09:15 — bukan 16:15."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1",
        "nomor_polisi": "AD 5 BB", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "tara_lain_kg": "0", "waktu": "2026-08-31T09:15",
        "catatan": "", "nomor_acuan": "N-1", "nama_sopir": "Slamet", "pihak_nama": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    assert "09:15" in tiket.text
    assert "16:15" not in tiket.text


# ─────────────── Nama pihak ikut tercetak besar ───────────────

@pytest.mark.parametrize("jalur", ["/", "/tiket"])
async def test_pihak_tercetak_sebesar_nomor_polisi(klien, jalur):
    """Petugas mencocokkan dua hal saat truk berhenti: platnya, dan siapa
    yang mengirim. Keduanya harus terbaca sekali lihat."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1",
        "nomor_polisi": "AD 5 BB", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "",
        "nomor_acuan": "N-1", "nama_sopir": "Slamet", "pihak_nama": "",
    })
    teks = (await klien.get(PREFIX + jalur)).text
    baris = teks[teks.index('class="pilihan__nama"'):]
    baris = baris[:baris.index("</div>", baris.index("pilihan__pihak"))]
    assert "AD 5 BB" in baris
    assert "H. Anton" in baris          # di baris besar yang sama


async def test_nama_pihak_wajib_di_semua_arah(klien):
    """Catatan timbang tanpa nama pihak tidak bisa dicocokkan dengan nota,
    tidak bisa direkap, dan tidak bisa dipertanggungjawabkan kepada siapa pun.
    """
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/TRANSFER")).text
    r = await klien.post(f"{PREFIX}/timbang/TRANSFER", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "", "pihak_nama": "",
        "nomor_polisi": "", "nama_sopir": "Slamet", "jumlah_karung": "",
        "tara_per_karung_kg": "", "berat_acuan_kg": "", "nomor_acuan": "",
        "tara_lain_kg": "0", "waktu": "", "catatan": "",
    })
    assert "wajib diisi" in r.text
    assert "Tidak ada truk" in (await klien.get(f"{PREFIX}/tiket")).text \
        or "0" in (await klien.get(f"{PREFIX}/tiket")).text


# ─────────────── Lembar pemeriksaan yang alasannya hilang ───────────────

async def test_lembar_terbuka_menyebut_bahwa_pemicunya_sudah_hilang(
    klien, app_uji
):
    """Lembar dibuka otomatis oleh status yang menuntut pemeriksaan. Bila
    angkanya lalu dikoreksi dan statusnya turun, lembarnya tetap terbuka —
    menutupnya keputusan manusia. Tetapi Admin yang membukanya kemudian tidak
    punya petunjuk apa pun tentang apa yang dulu dipersoalkan.
    """
    await login(klien, "budi")
    form = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    await klien.post(f"{PREFIX}/timbang/BERAS", data={
        "kode": kode_dari(form), "berat_kg": "3680",
        "cara_timbang": "DUA_KALI", "supplier_id": "1",
        "nomor_polisi": "K 8382 CC", "jumlah_karung": "0",
        "tara_per_karung_kg": "0", "berat_acuan_kg": "9000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "",
        "nomor_acuan": "SJ-1", "nama_sopir": "Slamet", "pihak_nama": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "15680", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    trx = await trx_oleh_id(trx_id)
    assert trx.status_kontrol in ("KELEBIHAN", "PERLU_PEMERIKSAAN",
                                  "INVESTIGASI")

    await klien.post(f"{PREFIX}/keluar")
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    rincian = (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    assert "sudah berubah sejak lembar ini dibuka" not in rincian

    # Angkanya dibetulkan; statusnya turun, lembarnya tetap terbuka.
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/koreksi", data={
        "alasan": "Berat menurut dokumen tidak diinput",
        "timbang1_kg": "", "timbang2_kg": "", "nomor_polisi": "",
        "nama_sopir": "Slamet", "supplier_id": "", "jumlah_karung": "",
        "tara_per_karung_kg": "", "berat_acuan_kg": "12000",
        "nomor_acuan": "", "catatan": "",
    })
    trx = await trx_oleh_id(trx_id)
    assert trx.status_kontrol not in ("KELEBIHAN", "PERLU_PEMERIKSAAN",
                                      "INVESTIGASI")

    rincian = (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    assert "sudah berubah sejak lembar ini dibuka" in rincian
    assert "Terbuka" in rincian          # tetap terbuka, tidak ditutup mesin
    assert "Tutup pemeriksaan" in rincian


# ─────────────── Salah pilih arah barang ───────────────

async def _mulai_masuk(klien, jenis="GABAH_BASAH", nopol="AD 5 BB") -> int:
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    await klien.post(f"{PREFIX}/timbang/{jenis}", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1", "nomor_polisi": nopol,
        "jumlah_karung": "120", "tara_per_karung_kg": "0,25",
        "berat_acuan_kg": "10000", "tara_lain_kg": "0", "waktu": "",
        "catatan": "", "nomor_acuan": "N-1", "nama_sopir": "Slamet", "pihak_nama": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    return int(re.search(r"/tiket/(\d+)", tiket.text).group(1))


async def test_arah_bisa_dibetulkan_sebelum_timbang_kedua(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, "wahid")
    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "Salah pilih saat mulai menimbang"})
    assert "Jenis barang diubah" in r.text

    trx = await trx_oleh_id(trx_id)
    assert trx.jenis_kode == "BERAS"
    assert trx.arah == "KELUAR"
    assert trx.status_tiket == TIKET_TERBUKA      # tiketnya tetap terbuka


async def test_arah_bisa_dibetulkan_setelah_timbang_kedua(klien, app_uji):
    """Angka timbangnya tidak perlu diketik ulang — hanya ditafsirkan ulang."""
    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "nomor_acuan": "N-1", "waktu": "", "catatan": "", "aksi": "selesai",
    })
    await klien.post(f"{PREFIX}/keluar")

    semula = await trx_oleh_id(trx_id)
    assert semula.arah == "MASUK"
    assert semula.berat_bermuatan_kg == 13600 and semula.berat_kosong_kg == 3570

    await login(klien, "wahid")
    # Komoditas lain pada ARAH YANG SAMA: angkanya tidak perlu disentuh sama
    # sekali, hanya aturan kontrolnya yang berganti.
    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "GABAH_KERING", "alasan": "Ternyata gabah kering"})
    assert "dihitung ulang" in r.text

    trx = await trx_oleh_id(trx_id)
    assert trx.jenis_kode == "GABAH_KERING" and trx.arah == "MASUK"
    assert trx.timbang1_kg == 13600 and trx.timbang2_kg == 3570
    assert trx.berat_bermuatan_kg == 13600 and trx.berat_kosong_kg == 3570


async def test_arah_mustahil_ditolak_sambil_menyebut_jalan_keluarnya(
    klien, app_uji
):
    """Angka yang urutannya benar tidak bisa sekadar dibalik arahnya.

    Truk yang datang 13,6 t lalu pergi 3,57 t secara fisik adalah barang
    masuk — pengiriman selalu pergi lebih berat. Yang penting di sini bukan
    penolakannya, melainkan bahwa penolakan itu MENYEBUT apa yang harus
    dilakukan, alih-alih melempar galat "berat truk kosong harus lebih kecil"
    yang benar tetapi tidak menolong siapa pun.
    """
    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "nomor_acuan": "N-1", "waktu": "", "catatan": "", "aksi": "selesai",
    })
    await klien.post(f"{PREFIX}/keluar")
    await login(klien, "wahid")

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "coba"})
    assert "mustahil" in r.text
    assert "Tukar urutan angka timbang" in r.text
    assert (await trx_oleh_id(trx_id)).arah == "MASUK"   # tidak tersentuh

    # Dengan penukaran, perbaikannya jalan dan angkanya masuk akal.
    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "Petugas mengetik mengikuti label",
        "tukar_timbangan": "1"})
    assert "dihitung ulang" in r.text
    trx = await trx_oleh_id(trx_id)
    assert trx.arah == "KELUAR"
    assert trx.timbang1_kg == 3570 and trx.timbang2_kg == 13600
    assert trx.berat_kosong_kg == 3570 and trx.berat_bermuatan_kg == 13600


async def test_tara_bawaan_ikut_berganti_tapi_yang_diketik_dihormati(
    klien, app_uji
):
    await login(klien, "budi")
    # Tara 0,25 = bawaan gabah, jadi ia hanya diterima dari formulir.
    bawaan = await _mulai_masuk(klien)
    # Tara 0,4 diketik sendiri — hasil menimbang karung yang benar-benar ada.
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1", "nomor_polisi": "B 1 CD",
        "jumlah_karung": "120", "tara_per_karung_kg": "0,4",
        "berat_acuan_kg": "10000", "tara_lain_kg": "0", "waktu": "",
        "catatan": "", "nomor_acuan": "N-2", "nama_sopir": "Slamet", "pihak_nama": "",
    })
    diketik = (await trx_oleh_kode(klien, "B 1 CD"))
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, "wahid")
    for tid in (bawaan, diketik):
        await klien.post(f"{PREFIX}/transaksi/{tid}/jenis", data={
            "jenis_kode": "BERAS", "alasan": "salah pilih"})

    from app import database
    from app.timbangan.models import TimbanganMuatan
    from sqlalchemy import select
    async with database.SessionLocal() as db:
        tara = {}
        for tid in (bawaan, diketik):
            m = (await db.execute(select(TimbanganMuatan).where(
                TimbanganMuatan.transaksi_id == tid))).scalars().first()
            tara[tid] = float(m.tara_per_karung_kg)
    assert tara[bawaan] == 0.05      # bawaan BERAS keluar
    assert tara[diketik] == 0.4      # pengamatan petugas dihormati


async def trx_oleh_kode(klien, nopol: str) -> int:
    tiket = await klien.get(f"{PREFIX}/tiket")
    potongan = tiket.text[:tiket.text.index(nopol)]
    return int(re.findall(r"/tiket/(\d+)", potongan)[-1])


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_petugas_tidak_boleh_mengubah_arah(klien, app_uji, siapa):
    """Mengubah arah mengubah seluruh hasil kontrol transaksi yang sudah
    tersimpan — keputusan yang harus punya nama."""
    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, siapa)
    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "mau ganti"})
    assert r.status_code == 403
    assert (await trx_oleh_id(trx_id)).arah == "MASUK"


async def test_ubah_arah_wajib_beralasan_dan_tercatat(klien, app_uji):
    from sqlalchemy import select

    from app import database
    from app.timbangan.models import TimbanganAudit

    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)
    await klien.post(f"{PREFIX}/keluar")
    await login(klien, "wahid")

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "   "})
    assert "disertai alasan" in r.text
    assert (await trx_oleh_id(trx_id)).arah == "MASUK"

    await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "Salah pilih saat mulai"})
    async with database.SessionLocal() as db:
        jejak = (await db.execute(select(TimbanganAudit).where(
            TimbanganAudit.aksi == "UBAH_JENIS"))).scalars().one()
    assert "Gabah Basah" in jejak.ringkasan and "Beras" in jejak.ringkasan
    assert "MASUK" in jejak.nilai_sebelum and "KELUAR" in jejak.nilai_sesudah


async def test_formulir_ubah_jenis_hanya_tampak_bagi_admin(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)
    milik_petugas = (await klien.get(f"{PREFIX}/transaksi/{trx_id}/koreksi")).text
    assert "Salah pilih jenis atau arah barang?" not in milik_petugas
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, "wahid")
    milik_admin = (await klien.get(f"{PREFIX}/transaksi/{trx_id}/koreksi")).text
    assert "Salah pilih jenis atau arah barang?" in milik_admin
    assert 'name="jenis_kode"' in milik_admin


async def test_pesan_arah_mustahil_tidak_merusak_tanda_bacanya(klien, app_uji):
    """Pemisah ribuan pernah ditulis dengan `.replace(",", ".")` atas seluruh
    kalimat, sehingga koma kalimatnya ikut jadi titik."""
    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "nomor_acuan": "N-1", "waktu": "", "catatan": "", "aksi": "selesai",
    })
    await klien.post(f"{PREFIX}/keluar")
    await login(klien, "wahid")
    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "coba"})
    assert "arah keluar, truk kosong" in r.text
    assert "13.600 kg" in r.text and "3.570 kg" in r.text


# ─────────────── Arah barang terbaca di daftar ───────────────

async def test_tiket_menyebut_arah_dan_tidak_memakai_kata_masuk_untuk_jam(
    klien, app_uji
):
    """Baris tiket dulu berbunyi "Beras · masuk 09:43" yang bermaksud JAM
    KEDATANGAN — dan terbaca sebagai arah barang. Pada pengiriman itu
    langsung menyesatkan.
    """
    await login(klien, "budi")
    form = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    await klien.post(f"{PREFIX}/timbang/BERAS", data={
        "kode": kode_dari(form), "berat_kg": "3570", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "K 8482 CC", "jumlah_karung": "0",
        "tara_per_karung_kg": "0", "berat_acuan_kg": "10000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "SJ-1",
        "nama_sopir": "Slamet", "pihak_nama": "",
    })
    for jalur in (f"{PREFIX}/tiket", f"{PREFIX}/"):
        teks = (await klien.get(jalur)).text
        blok = teks[teks.index("K 8482 CC"):]
        blok = blok[:blok.index("</a>")]
        assert "pengiriman" in blok, jalur
        assert "masuk" not in blok, jalur      # tidak ada lagi kata itu
        assert "sejak" in blok, jalur


async def test_beras_masuk_dan_beras_keluar_bisa_dibedakan_di_daftar(
    klien, app_uji
):
    """Keduanya sama-sama bernama "Beras" — tanpa arahnya, satu daftar
    memuat dua baris yang tampak identik."""
    await login(klien, "budi")
    for jenis, nopol, berat in (("BERAS_MASUK", "AD 1 AA", "13600"),
                                ("BERAS", "AD 2 BB", "3570")):
        form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
        await klien.post(f"{PREFIX}/timbang/{jenis}", data={
            "kode": kode_dari(form), "berat_kg": berat,
            "cara_timbang": "DUA_KALI", "supplier_id": "1",
            "nomor_polisi": nopol, "jumlah_karung": "100",
            "tara_per_karung_kg": "0,1", "berat_acuan_kg": "9000",
            "tara_lain_kg": "0", "waktu": "", "catatan": "",
            "nomor_acuan": "N", "nama_sopir": "Slamet", "pihak_nama": "",
        })
    teks = (await klien.get(f"{PREFIX}/tiket")).text
    for nopol, arah in (("AD 1 AA", "barang masuk"), ("AD 2 BB", "pengiriman")):
        blok = teks[teks.index(nopol):]
        assert arah in blok[:blok.index("</a>")], nopol


async def test_catatan_menyebut_arah_pada_kolom_komoditas(klien, app_uji):
    await login(klien, "budi")
    await _selesaikan(klien, "GABAH_BASAH")
    await klien.post(f"{PREFIX}/keluar")

    await _jadi_super(app_uji)
    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/transaksi")).text
    # Hanya isi tabelnya: daftar saringan di atas juga memuat nama komoditas.
    tabel = teks[teks.index("<tbody>"):teks.index("</tbody>")]
    blok = tabel[tabel.index("Gabah Basah"):]
    assert "barang masuk" in blok[:220]


# ─────────────── Sebutan lawan transaksi ───────────────

@pytest.mark.parametrize("jenis,sebutan,bukan", [
    ("GABAH_BASAH", "Supplier", "Pelanggan"),
    ("BERAS", "Pelanggan", "Supplier"),
    ("BEBAS", "Pemilik barang", "Supplier"),
    ("TRANSFER", "Asal → tujuan", "Supplier"),
])
async def test_lawan_transaksi_dinamai_menurut_arah(klien, jenis, sebutan, bukan):
    """Satu kolom data, empat nama. Memakai "Supplier" untuk semuanya membuat
    layar berbohong: pada pengiriman yang menerima barang adalah pelanggan."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    assert sebutan in form
    assert bukan not in form


async def test_sebutan_ikut_berubah_saat_arahnya_dibetulkan(klien, app_uji):
    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)
    await klien.post(f"{PREFIX}/keluar")
    await login(klien, "wahid")

    assert "Supplier" in (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "Salah pilih"})

    rincian = (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    assert "Pelanggan" in rincian
    assert "Supplier" not in rincian


# ─────────────── Daftar pihak mengikuti arah ───────────────

async def _tambah_pelanggan(nama: str) -> int:
    from app import database
    from app.models import Pelanggan

    async with database.SessionLocal() as db:
        p = Pelanggan(nama_pelanggan=nama)
        db.add(p)
        await db.commit()
        return p.id


async def test_barang_masuk_hanya_menawarkan_supplier(klien):
    """Menawarkan pelanggan di sisi pembelian membuat petugas bisa mencatat
    pembelian atas nama pembeli — salah pilih yang baru ketahuan
    berbulan-bulan kemudian, saat rekonsiliasi tidak ketemu."""
    await _tambah_pelanggan("Toko Beras Handoko")
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert "H. Anton" in form                    # supplier
    assert "Toko Beras Handoko" not in form      # pelanggan tidak muncul


async def test_pengiriman_hanya_menawarkan_pelanggan(klien):
    await _tambah_pelanggan("Toko Beras Handoko")
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    assert "Toko Beras Handoko" in form
    assert "H. Anton" not in form                # supplier tidak muncul


async def test_pengiriman_menyimpan_ke_kolom_pelanggan(klien):
    pid = await _tambah_pelanggan("Toko Beras Handoko")
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    await klien.post(f"{PREFIX}/timbang/BERAS", data={
        "kode": kode_dari(form), "berat_kg": "3570", "cara_timbang": "DUA_KALI",
        "supplier_id": str(pid), "nomor_polisi": "K 8482 CC",
        "jumlah_karung": "100", "tara_per_karung_kg": "0,05",
        "berat_acuan_kg": "9000", "tara_lain_kg": "0", "waktu": "",
        "catatan": "", "nomor_acuan": "SJ-1", "nama_sopir": "Slamet", "pihak_nama": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    trx = await trx_oleh_id(trx_id)
    assert trx.pelanggan_id == pid
    assert trx.supplier_id is None          # tidak pernah keduanya
    assert "Toko Beras Handoko" in tiket.text


async def test_barang_masuk_menyimpan_ke_kolom_supplier(klien):
    await login(klien)
    trx_id = await _mulai_masuk(klien)
    trx = await trx_oleh_id(trx_id)
    assert trx.supplier_id == 1
    assert trx.pelanggan_id is None


async def test_ubah_arah_menyelamatkan_nama_pihak_ke_teks(klien, app_uji):
    """Supplier id 5 bukan pelanggan id 5 — idnya tidak bisa dibawa. Tetapi
    namanya bisa, dan itulah yang dibutuhkan catatan."""
    await login(klien, "budi")
    trx_id = await _mulai_masuk(klien)          # MASUK, supplier H. Anton
    await klien.post(f"{PREFIX}/keluar")

    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/jenis", data={
        "jenis_kode": "BERAS", "alasan": "Ternyata pengiriman"})

    trx = await trx_oleh_id(trx_id)
    assert trx.arah == "KELUAR"
    assert trx.supplier_id is None and trx.pelanggan_id is None
    assert trx.pihak_nama == "H. Anton"         # tidak hilang diam-diam


# ─────────────── Lembar terbuka harus bisa dijangkau ───────────────

async def test_ringkasan_menautkan_lembar_pemeriksaan_yang_terbuka(
    klien, app_uji
):
    """Angka "2 lembar pemeriksaan masih terbuka" dulu teks polos, dan daftar
    di bawahnya hanya memuat transaksi yang STATUSNYA masih menuntut
    pemeriksaan. Lembar yang angkanya sudah dikoreksi karena itu terhitung
    tetapi tidak muncul di mana pun — justru lembar itulah yang perlu ditutup.
    """
    await login(klien, "budi")
    form = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    await klien.post(f"{PREFIX}/timbang/BERAS", data={
        "kode": kode_dari(form), "berat_kg": "3680", "cara_timbang": "DUA_KALI",
        "supplier_id": "", "pihak_nama": "CV Uji", "nomor_polisi": "K 8382 CC",
        "jumlah_karung": "0", "tara_per_karung_kg": "0",
        "berat_acuan_kg": "9000", "tara_lain_kg": "0", "waktu": "",
        "catatan": "", "nomor_acuan": "SJ-1", "nama_sopir": "Slamet",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "15680", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    await klien.post(f"{PREFIX}/keluar")
    await _jadi_super(app_uji)
    await login(klien, "wahid")

    # Angkanya dikoreksi sampai statusnya tidak lagi menuntut pemeriksaan —
    # keadaan yang dulu membuat lembarnya menghilang dari layar.
    await klien.post(f"{PREFIX}/transaksi/{trx_id}/koreksi", data={
        "alasan": "harusnya tidak ada dokumen", "timbang1_kg": "",
        "timbang2_kg": "", "nomor_polisi": "", "nama_sopir": "Slamet",
        "supplier_id": "", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "0", "nomor_acuan": "", "catatan": "",
    })
    trx = await trx_oleh_id(trx_id)
    assert trx.status_kontrol not in ("KELEBIHAN", "PERLU_PEMERIKSAAN",
                                      "INVESTIGASI")

    laporan = (await klien.get(f"{PREFIX}/laporan")).text
    assert "lembar pemeriksaan masih terbuka" in laporan
    assert f"/transaksi/{trx_id}" in laporan       # bisa dijangkau
    assert "tidak menutup lembarnya" in laporan    # dan dijelaskan


async def test_ringkasan_bersih_setelah_lembarnya_ditutup(klien, app_uji):
    await login(klien, "budi")
    form = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    await klien.post(f"{PREFIX}/timbang/BERAS", data={
        "kode": kode_dari(form), "berat_kg": "3680", "cara_timbang": "DUA_KALI",
        "supplier_id": "", "pihak_nama": "CV Uji", "nomor_polisi": "K 1 AA",
        "jumlah_karung": "0", "tara_per_karung_kg": "0",
        "berat_acuan_kg": "9000", "tara_lain_kg": "0", "waktu": "",
        "catatan": "", "nomor_acuan": "SJ-2", "nama_sopir": "Slamet",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "15680", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    await klien.post(f"{PREFIX}/keluar")
    await _jadi_super(app_uji)
    await login(klien, "wahid")

    assert "lembar pemeriksaan masih terbuka" in (
        await klien.get(f"{PREFIX}/laporan")).text

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/periksa", data={
        "kategori_hasil": "SALAH_CATAT",
        "catatan_resolusi": "Nota belum diisi saat menimbang",
        "dilaporkan_ke": "", "langkah_ulang_timbang": "",
        "langkah_hitung_karung": "", "langkah_periksa_tara": "",
        "langkah_periksa_dokumen": "", "langkah_periksa_muatan": "",
        "langkah_lapor": "",
    })
    assert "Pemeriksaan ditutup" in r.text
    assert "lembar pemeriksaan masih terbuka" not in (
        await klien.get(f"{PREFIX}/laporan")).text


# ─────────────── Pihak & sopir wajib ───────────────

@pytest.mark.parametrize("jenis,sebutan", [
    ("GABAH_BASAH", "Supplier"),
    ("BERAS", "Pelanggan"),
    ("BEBAS", "Pemilik barang"),
    ("TRANSFER", "Asal → tujuan"),
])
async def test_pihak_kosong_ditolak_dengan_sebutan_arahnya(klien, jenis, sebutan):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    r = await klien.post(f"{PREFIX}/timbang/{jenis}", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "", "pihak_nama": "",
        "nomor_polisi": "AD 5 BB", "nama_sopir": "Slamet",
        "jumlah_karung": "100", "tara_per_karung_kg": "0,1",
        "berat_acuan_kg": "9000", "nomor_acuan": "N", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    assert f"{sebutan} wajib diisi" in r.text


async def test_pihak_boleh_dari_daftar_atau_diketik(klien):
    """Dua jalan yang sah — yang dilarang hanya kosong."""
    await login(klien)
    for pilih, tulis in ((("supplier_id", "1"), ("pihak_nama", "")),
                         (("supplier_id", ""), ("pihak_nama", "H. Baru"))):
        form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
        r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
            "kode": kode_dari(form), "berat_kg": "13600",
            "cara_timbang": "DUA_KALI", pilih[0]: pilih[1], tulis[0]: tulis[1],
            "nomor_polisi": "AD 5 BB", "nama_sopir": "Slamet",
            "jumlah_karung": "120", "tara_per_karung_kg": "0,25",
            "berat_acuan_kg": "10000", "nomor_acuan": "N-1",
            "tara_lain_kg": "0", "waktu": "", "catatan": "",
        })
        assert "wajib diisi" not in r.text


async def test_nama_sopir_wajib(klien):
    """Sopir satu-satunya orang yang hadir di jembatan saat angkanya dibaca."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1", "pihak_nama": "",
        "nomor_polisi": "AD 5 BB", "nama_sopir": "   ",
        "jumlah_karung": "120", "tara_per_karung_kg": "0,25",
        "berat_acuan_kg": "10000", "nomor_acuan": "N-1", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    assert "Nama sopir wajib diisi" in r.text


async def test_isian_sopir_ditandai_wajib_di_layar(klien):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    potongan = form[form.index('name="nama_sopir"') - 300:
                    form.index('name="nama_sopir"') + 200]
    assert "required" in potongan
    assert "Nama sopir (boleh kosong)" not in form


# ─────────────── Karung: boleh di tahap mana saja, asal tidak keduanya kosong ──

async def test_karung_keluar_dari_kartu_nota_di_kedua_layar(klien):
    """Nomor dan berat adalah isi kertas yang dibawa sopir; jumlah karung
    adalah hitungan petugas. Satu kartu bernama "Nota supplier" mengundang
    angka karung disalin dari nota."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    kartu_nota = form[form.index("Nota supplier"):form.index('name="jumlah_karung"')]
    assert "berat_acuan_kg" in kartu_nota
    assert "Muatan" in kartu_nota          # kartu terpisah dibuka sebelum karung
    assert 'name="jumlah_karung"' in form  # tetap ada di layar ini


async def test_karung_diisi_di_timbang_pertama_terbawa_ke_kedua(klien):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1", "pihak_nama": "",
        "nomor_polisi": "AD 5 BB", "nama_sopir": "Slamet",
        "jumlah_karung": "120", "tara_per_karung_kg": "0,25",
        "berat_acuan_kg": "10000", "nomor_acuan": "N-1", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    form2 = (await klien.get(f"{PREFIX}/tiket/{trx_id}")).text
    assert 'value="120"' in form2

    # Tidak perlu diketik ulang: langsung bisa diselesaikan.
    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    assert "selesai dan tersimpan" in r.text


async def test_karung_boleh_baru_diisi_di_timbang_kedua(klien):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1", "pihak_nama": "",
        "nomor_polisi": "AD 5 BB", "nama_sopir": "Slamet",
        "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "10000", "nomor_acuan": "N-1", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "", "nomor_acuan": "",
        "waktu": "", "catatan": "", "aksi": "selesai",
    })
    assert "selesai dan tersimpan" in r.text
    assert (await trx_oleh_id(trx_id)).jumlah_karung == 120


async def test_tara_disarankan_juga_di_timbang_kedua(klien):
    """Sarannya justru lebih tajam di sini: pihaknya sudah diketahui, jadi
    sampling khusus pihak itu bisa dipakai."""
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/BERAS_PK")).text
    await klien.post(f"{PREFIX}/timbang/BERAS_PK", data={
        "kode": kode_dari(form), "berat_kg": "13600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1", "pihak_nama": "",
        "nomor_polisi": "AD 5 BB", "nama_sopir": "Slamet",
        "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "10000", "nomor_acuan": "N-1", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    form2 = (await klien.get(f"{PREFIX}/tiket/{trx_id}")).text
    assert 'value="0.100"' in form2          # bawaan aturan Beras PK
    assert "aturan komoditas" in form2


# ─────────────── Istilah Ringkasan: fakta, bukan tugas ───────────────

async def test_ringkasan_tidak_menyebut_pekerjaan_untuk_yang_sudah_tuntas(
    klien, app_uji
):
    """Angka di petak menghitung STATUS KONTROL, dan status adalah catatan
    permanen tentang apa yang terjadi saat menimbang — ia tidak berubah ketika
    pemeriksaannya ditutup. Istilah "Perlu diperiksa" karena itu membuat
    transaksi yang sudah tuntas ditelusuri terbaca sebagai pekerjaan
    menggantung. Daftar tugas yang sesungguhnya adalah lembar yang terbuka.
    """
    await login(klien, "budi")
    form = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    await klien.post(f"{PREFIX}/timbang/BERAS", data={
        "kode": kode_dari(form), "berat_kg": "3680", "cara_timbang": "DUA_KALI",
        "supplier_id": "", "pihak_nama": "CV Uji", "nomor_polisi": "K 8 CC",
        "nama_sopir": "Slamet", "jumlah_karung": "0",
        "tara_per_karung_kg": "0", "berat_acuan_kg": "9000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "SJ-1",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "15680", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    await klien.post(f"{PREFIX}/keluar")
    await _jadi_super(app_uji)
    await login(klien, "wahid")

    await klien.post(f"{PREFIX}/transaksi/{trx_id}/periksa", data={
        "kategori_hasil": "SELISIH_WAJAR", "catatan_resolusi": "sudah dicek",
        "dilaporkan_ke": "", "langkah_ulang_timbang": "",
        "langkah_hitung_karung": "", "langkah_periksa_tara": "",
        "langkah_periksa_dokumen": "", "langkah_periksa_muatan": "",
        "langkah_lapor": "",
    })

    laporan = (await klien.get(f"{PREFIX}/laporan")).text
    # Angkanya tetap ada — ia memang statistik, dan itu benar.
    assert "Di luar batas" in laporan
    assert "Selisih di luar batas" in laporan
    # Tapi tidak lagi berbunyi seperti tugas yang menggantung.
    assert "Perlu diperiksa" not in laporan
    assert "Menunggu ditelusuri" not in laporan
    assert "lembar pemeriksaan masih terbuka" not in laporan


async def test_angka_dan_daftar_di_luar_batas_sepakat(klien, app_uji):
    """Petaknya menghitung SEMUA status di luar batas; daftarnya dulu hanya
    memuat PERLU_PEMERIKSAAN. Angka "1" dengan daftar kosong di layar yang
    sama membuat orang mengira ada yang disembunyikan."""
    await login(klien, "budi")
    form = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    await klien.post(f"{PREFIX}/timbang/BERAS", data={
        "kode": kode_dari(form), "berat_kg": "3680", "cara_timbang": "DUA_KALI",
        "supplier_id": "", "pihak_nama": "CV Uji", "nomor_polisi": "K 9 DD",
        "nama_sopir": "Slamet", "jumlah_karung": "0",
        "tara_per_karung_kg": "0", "berat_acuan_kg": "9000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "SJ-9",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "15680", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
        "aksi": "selesai",
    })
    assert (await trx_oleh_id(trx_id)).status_kontrol == "KELEBIHAN"

    await klien.post(f"{PREFIX}/keluar")
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    laporan = (await klien.get(f"{PREFIX}/laporan")).text
    assert "Selisih di luar batas" in laporan
    assert f"/transaksi/{trx_id}" in laporan     # KELEBIHAN pun ikut terdaftar


# ─────────────── Kalimat karung mengikuti kenyataan arah barang ───────────────

async def test_kalimat_karung_di_timbang_pertama_mengikuti_arah(klien):
    """Pada pengiriman, timbang pertama adalah truk KOSONG — belum ada satu
    karung pun untuk dihitung. Menyuruh menghitungnya di situ hanya mengundang
    angka karangan."""
    await login(klien)
    masuk = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert "dihitung saat bongkar" in masuk
    assert "Truk masih kosong" not in masuk

    keluar = (await klien.get(f"{PREFIX}/timbang/BERAS")).text
    assert "Truk masih kosong" in keluar
    assert "baru dihitung saat muat" in keluar
    assert "dihitung saat bongkar" not in keluar


@pytest.mark.parametrize("jenis,kalimat", [
    ("GABAH_BASAH", "Dihitung saat bongkar, bukan disalin dari nota."),
    ("BERAS", "Dihitung saat muat, bukan disalin dari surat jalan."),
    ("TRANSFER", "Kosongkan bila muatannya curah"),
])
async def test_kalimat_karung_di_timbang_kedua_mengikuti_arah(
    klien, jenis, kalimat
):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    await klien.post(f"{PREFIX}/timbang/{jenis}", data={
        "kode": kode_dari(form), "berat_kg": "3680", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "pihak_nama": "Gudang 1 → Gudang 2",
        "nomor_polisi": "AD 5 BB", "nama_sopir": "Slamet",
        "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "9000", "nomor_acuan": "N", "tara_lain_kg": "0",
        "waktu": "", "catatan": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    assert kalimat in (await klien.get(f"{PREFIX}/tiket/{trx_id}")).text


# ─────────────── Struk: selisih hanya bila ada pembandingnya ───────────────

async def test_struk_jasa_timbang_tidak_mencetak_dokumen_nol(klien):
    """Timbang bebas tidak punya dokumen. Mencetak "Menurut dokumen 0 kg ·
    Selisih 0,00 kg" membuat angka nol terbaca seperti pernyataan, padahal
    tidak ada dokumen yang menyatakannya."""
    from pypdf import PdfReader
    from io import BytesIO

    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/BEBAS")).text
    await klien.post(f"{PREFIX}/timbang/BEBAS", data={
        "kode": kode_dari(form), "berat_kg": "14248", "cara_timbang": "SEKALI",
        "supplier_id": "", "pihak_nama": "Pak Arif", "nomor_polisi": "AD 9262 BE",
        "nama_sopir": "Pak Arif", "jumlah_karung": "0",
        "tara_per_karung_kg": "0", "berat_acuan_kg": "0", "nomor_acuan": "",
        "tara_lain_kg": "0", "waktu": "", "catatan": "",
    })
    trx_id = 1
    r = await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/80mm")
    assert r.status_code == 200
    teks = "\n".join(
        h.extract_text() or "" for h in PdfReader(BytesIO(r.content)).pages)
    assert "BERAT BARANG" in teks
    assert "Menurut dokumen" not in teks
    assert "Selisih" not in teks


async def test_struk_tetap_mencetak_selisih_bila_dokumennya_ada(klien):
    """Beras PK sengaja transparan (`rahasia=False`) — hasil kontrolnya
    memang diserahkan ke pengirim, sesuai Sistem Tara butir 9. Gabah dan
    seluruh pengiriman sebaliknya: selisihnya tidak pernah dicetak."""
    from pypdf import PdfReader
    from io import BytesIO

    await login(klien)
    trx_id = await _selesaikan(klien, "BERAS_PK")
    r = await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/80mm")
    teks = "\n".join(
        h.extract_text() or "" for h in PdfReader(BytesIO(r.content)).pages)
    assert "Menurut dokumen" in teks and "Selisih" in teks


async def test_tautan_cetak_dibuka_bukan_diunduh(klien):
    """Di peramban meja PDF harus TERBUKA di penampil — di situlah tombol
    cetaknya. Atribut `download` akan membuatnya langsung terunduh, sehingga
    mencetak jadi dua langkah lebih jauh.

    `data-unduh` tetap ada untuk iOS, yang mencegatnya ke lembar Bagikan;
    lembar Bagikan macOS TIDAK punya pilihan Cetak, jadi cegatan itu memang
    hanya boleh berlaku di iOS. Penjaganya di app.js.
    """
    await login(klien, "budi")
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    teks = (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak")).text
    for jalur in ("cetak/80mm", "cetak/ncr"):
        potongan = teks[max(0, teks.index(jalur) - 200):teks.index(jalur) + 120]
        assert "data-unduh" in potongan, jalur
        assert 'target="_blank"' in potongan, jalur
        assert "download" not in potongan, jalur


async def test_tautan_csv_tetap_diunduh(klien, app_uji):
    """CSV sebaliknya: menampilkannya mentah di tab tidak berguna."""
    await _jadi_super(app_uji)
    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/transaksi")).text
    potongan = teks[max(0, teks.index("ekspor.csv") - 200):teks.index("ekspor.csv")]
    assert "data-unduh" in potongan and "download" in potongan


# ─────────────────── Cetak langsung ke printer ───────────────────

async def test_perintah_cetak_epos_sejalan_dengan_struk_pdf(klien):
    """Dua jalur cetak, satu isi.

    Kertas dari printer dan kertas dari PDF sama-sama ditandatangani pengirim
    barang. Bila angkanya bisa berbeda, salah satunya adalah bukti palsu —
    dan tidak ada yang tahu yang mana.
    """
    await login(klien)
    trx_id = await _selesaikan(klien, "BERAS_PK")

    r = await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/epos")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/xml")

    from xml.etree import ElementTree
    akar = ElementTree.fromstring(r.text)
    ruang = "{http://www.epson-pos.com/schemas/2011/03/epos-print}"
    teks = "\n".join((el.text or "") for el in akar.iter(ruang + "text"))
    assert "B U K T I   T I M B A N G" in teks
    assert "BERAT BARANG" in teks
    # Beras PK transparan — selisihnya memang diserahkan ke pengirim.
    assert "Menurut dokumen" in teks and "Selisih" in teks


async def test_perintah_cetak_epos_ikut_menutup_selisih_yang_rahasia(klien):
    """SOP butir 8 berlaku di printer persis seperti di PDF."""
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_KERING")
    r = await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak/epos")
    assert "Selisih" not in r.text and "Menurut dokumen" not in r.text


async def test_halaman_penyiapan_printer_menyebut_kedua_izin(klien):
    """Tanpa keduanya tombol cetak hanya diam, dan petugas menyimpulkan
    aplikasinya rusak — jadi keduanya harus tertulis, bukan disiratkan."""
    await login(klien)
    r = await klien.get(f"{PREFIX}/printer")
    assert r.status_code == 200
    assert "sertifikat" in r.text.lower()
    assert "jaringan lokal" in r.text.lower()


async def test_penyiapan_printer_tertutup_bagi_yang_belum_masuk(klien):
    r = await klien.get(f"{PREFIX}/printer")
    assert "Kata sandi" in r.text


async def test_cetak_uji_bisa_diminta_tanpa_transaksi(klien):
    """Printer harus bisa diuji sebelum ada barang datang — bukan sesudah."""
    await login(klien)
    r = await klien.get(f"{PREFIX}/printer/uji")
    assert r.status_code == 200
    assert 'cut type="feed"' in r.text

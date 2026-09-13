"""Keamanan akun Pos Timbang, dan hal kecil yang bisa menyesatkan.

Temuan QA T-19, T-20, T-23, T-24, T-25, T-26, T-27 — 11 September 2026.

**T-19.** Token sesi berlaku 180 hari dan tak bisa dicabut oleh apa pun.
Sesudah petugas mengganti sandinya lalu menekan Keluar, cookie lama di
perangkat lain tetap dijawab 200. Login yang gagal tidak diaudit dan tidak
dibatasi sama sekali — bertentangan dengan RANCANGAN §10 yang menuntut
keduanya.

**T-20.** Parameter tujuan menerima alamat situs lain, jadi halaman masuk pos
timbang bisa dipakai mengantar petugas ke tempat yang memanen sandinya.

**T-23.** Lembar pemeriksaan yang sudah ditutup bisa ditutup ULANG, menimpa
kategori hasil dan nama penutupnya. Dan lembar milik tiket yang dibatalkan
tetap terbuka selamanya, menumpuk di antrean sebagai pekerjaan yang tak
mungkin diselesaikan siapa pun.

**T-24.** Pemasok yang sudah dihapus tetap ditawarkan di layar timbang.

**T-25.** Nama sopir "=HYPERLINK(...)" dieksekusi saat CSV dibuka di Excel.

**T-26.** "Total barang" menjumlahkan barang masuk, barang keluar, jasa
timbang, dan transfer internal menjadi satu angka — angka yang tak berarti
apa-apa, dan yang membacanya mengira itu jumlah gabah yang diterima.
"""
from __future__ import annotations

import pytest

from app.timbangan import logic, security as sec, service
from app.timbangan.service import InputMuatan, InputTimbang

pytestmark = pytest.mark.usefixtures("jenis_tersemai")


def _masuk(kode, supplier_id, berat=13_600):
    return InputTimbang(
        kode=kode, arah=logic.MASUK, jenis_kode="GABAH_BASAH", berat_kg=berat,
        supplier_id=supplier_id, nomor_polisi="AD 1234 XY", nama_sopir="Slamet",
        perangkat_kode="P1",
        muatan=[InputMuatan(jenis_kode="GABAH_BASAH", jumlah_karung=120,
                            tara_per_karung_kg=0.25, berat_acuan_kg=10_048,
                            nomor_acuan="NOTA-01")])


# ─────────────────────────── T-19 ───────────────────────────

def test_token_membawa_versinya():
    token = sec.buat_token(7, versi=3)
    assert sec.baca_token(token) == (7, 3)


def test_token_versi_lama_ditolak():
    """Inilah yang membuat Keluar dan ganti sandi berarti sesuatu di
    perangkat yang TIDAK sedang dipegang."""
    dibaca = sec.baca_token(sec.buat_token(7, versi=1))
    assert sec.token_masih_berlaku(dibaca, versi_akun=1) is True
    assert sec.token_masih_berlaku(dibaca, versi_akun=2) is False


def test_token_lama_tanpa_versi_dianggap_versi_satu():
    """Deploy tak boleh memutus semua petugas sekaligus — hanya mereka yang
    versinya memang dinaikkan sesudahnya."""
    import hashlib
    import hmac as _hmac
    import json

    from hmu_identitas.token import _b64e

    muatan = _b64e(json.dumps({"sub": 9, "exp": 9_999_999_999}).encode())
    tanda = _b64e(_hmac.new(sec._kunci(), muatan.encode(), hashlib.sha256).digest())
    assert sec.baca_token(f"{muatan}.{tanda}") == (9, 1)


@pytest.mark.parametrize("rusak", ["", "a.b", "....", "\udcff.\udcff"])
def test_token_rusak_tak_pernah_melempar(rusak):
    assert sec.baca_token(rusak) is None


async def test_ganti_sandi_menaikkan_versi(db, petugas):
    """Sandi yang diganti memutus sesi lama. Sebelumnya tidak: cookie lama
    tetap dijawab 200 sesudah ganti sandi DAN sesudah Keluar."""
    petugas.password_hash = sec.hash_sandi("rahasia123")
    await db.flush()
    lama = petugas.token_version

    await service.ubah_profil(db, orang=petugas, sandi_lama="rahasia123",
                              sandi_baru="sandibaru456")
    assert petugas.token_version > lama


async def test_peran_berubah_juga_menaikkan_versi(db, admin, petugas):
    """Yang turun harus benar-benar turun — dan itu tak terjadi selama
    tokennya yang lama masih diterima."""
    from app.timbangan.models import ROLE_ADMIN

    lama = petugas.token_version
    await service.ubah_akun(db, admin=admin, orang=petugas, role=ROLE_ADMIN)
    assert petugas.token_version > lama


def test_pembatas_percobaan_masuk():
    """RANCANGAN §10 menuntutnya; sampai sekarang tak ada sama sekali."""
    from app.timbangan import gerbang_masuk as gm

    gm.bersihkan()
    for _ in range(gm.BATAS_GAGAL):
        assert gm.boleh_coba("budi", "10.0.0.1") is None
        gm.catat_gagal("budi", "10.0.0.1")
    assert gm.boleh_coba("budi", "10.0.0.1") is not None
    # Petugas lain di gudang yang sama tak ikut terkunci.
    assert gm.boleh_coba("sari", "10.0.0.1") is None


# ─────────────────────────── T-20 ───────────────────────────

@pytest.mark.parametrize("jahat", [
    "https://evil.example", "//evil.example", "/bukan-timbangan",
    "javascript:alert(1)", "///evil.example", "/timbangan/../lain",
])
def test_tujuan_di_luar_modul_ditolak(jahat):
    """Pos timbang hanya punya satu tempat yang sah untuk dituju sesudah
    masuk: dirinya sendiri."""
    assert sec.tujuan_aman(jahat) == "/timbangan/"


@pytest.mark.parametrize("baik", ["/timbangan/", "/timbangan/tiket",
                                  "/timbangan/laporan?bulan=9"])
def test_tujuan_di_dalam_modul_diterima(baik):
    assert sec.tujuan_aman(baik) == baik


# ─────────────────────────── T-25 ───────────────────────────

@pytest.mark.parametrize("jahat", [
    '=HYPERLINK("https://evil.example","klik")', "+1+1", "-1+1", "@SUM(A1)",
])
def test_nilai_csv_tak_pernah_jadi_rumus(jahat):
    """Nama sopir diketik petugas dan bisa berisi apa saja. Dibuka di Excel,
    sel yang diawali `=` dijalankan — dan yang membukanya biasanya bagian
    keuangan, di komputer yang punya akses ke hal lain."""
    from app.timbangan.routes.laporan import jinakkan_sel

    assert str(jinakkan_sel(jahat)).startswith("'")


def test_angka_csv_tetap_angka():
    """Mengubah angka jadi teks membuat kolom jumlah di Excel berhenti
    menjumlah — kerusakan yang tak terlihat sampai angkanya dipakai."""
    from app.timbangan.routes.laporan import jinakkan_sel

    assert jinakkan_sel(13_600) == 13_600
    assert jinakkan_sel("Slamet") == "Slamet"
    assert jinakkan_sel(None) is None


# ─────────────────────────── T-24 ───────────────────────────

async def test_pemasok_terhapus_tak_ditawarkan(db, supplier):
    """Pemasok yang sudah dihapus tetap muncul di daftar pilihan, dan tiket
    yang tertaut padanya tak bisa ditelusuri ke mana pun."""
    from datetime import datetime, timezone

    from app.models import Supplier

    mati = Supplier(nama_supplier="Sudah Berhenti",
                    deleted_at=datetime.now(timezone.utc))
    db.add(mati)
    await db.flush()

    nama = [s.nama_supplier for s in await service.daftar_pihak(db, logic.MASUK)]
    assert "H. Anton" in nama
    assert "Sudah Berhenti" not in nama


async def test_daftar_supplier_juga_menyaring_yang_terhapus(db, supplier):
    """Penyaring lamanya merujuk `is_active`, atribut yang tak pernah ada di
    model ini — jadi `hasattr` selalu False dan penyaringnya tak pernah
    berjalan sekali pun."""
    from datetime import datetime, timezone

    from app.models import Supplier

    db.add(Supplier(nama_supplier="Mati Juga",
                    deleted_at=datetime.now(timezone.utc)))
    await db.flush()

    nama = [s.nama_supplier for s in await service.daftar_supplier(db)]
    assert "Mati Juga" not in nama


# ─────────────────────────── T-23 ───────────────────────────

async def test_lembar_pemeriksaan_tak_bisa_ditutup_dua_kali(db, petugas, admin,
                                                            supplier):
    """Penutupan kedua menimpa kategori hasil dan nama penutupnya — jadi
    lembar yang sudah diselesaikan seseorang bisa ditulis ulang oleh orang
    lain, tanpa satu pun jejak bahwa itu pernah terjadi."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-P-001", supplier.id))
    trx = await service.simpan_timbang_kedua(db, akun=petugas, kode=trx.kode,
                                             berat_kg=3_570)
    lembar = await service.pemeriksaan_transaksi(db, trx.id)
    assert lembar is not None

    await service.selesaikan_pemeriksaan(
        db, akun=admin, lembar=lembar, langkah={},
        kategori_hasil="SELISIH_WAJAR", catatan_resolusi="sudah dicek")
    with pytest.raises(service.LayananError, match="sudah ditutup"):
        await service.selesaikan_pemeriksaan(
            db, akun=admin, lembar=lembar, langkah={},
            kategori_hasil="LAIN", catatan_resolusi="ditulis ulang")


async def test_void_menutup_lembar_pemeriksaannya(db, petugas, admin, supplier):
    """Lembar milik tiket yang dibatalkan menumpuk di antrean selamanya
    sebagai pekerjaan yang tak mungkin diselesaikan siapa pun."""
    from app.timbangan.models import PEMERIKSAAN_SELESAI

    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-P-002", supplier.id))
    trx = await service.simpan_timbang_kedua(db, akun=petugas, kode=trx.kode,
                                             berat_kg=3_570)
    assert await service.pemeriksaan_transaksi(db, trx.id) is not None

    await service.void_transaksi(db, akun=admin, trx=trx, alasan="salah input")

    lembar = await service.pemeriksaan_transaksi(db, trx.id)
    assert lembar.status == PEMERIKSAAN_SELESAI
    assert not await service.daftar_pemeriksaan_terbuka(db)


# ─────────────────────────── T-26 ───────────────────────────

async def test_total_barang_dipisah_per_arah(db, petugas, supplier):
    """Satu angka yang menjumlahkan gabah masuk, beras keluar, jasa timbang,
    dan transfer internal tidak berarti apa-apa — dan yang membacanya
    mengira itu jumlah gabah yang diterima."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-R-001", supplier.id))
    await service.simpan_timbang_kedua(db, akun=petugas, kode=trx.kode,
                                       berat_kg=3_570)
    jasa = InputTimbang(kode="TRX-R-002", arah=logic.BEBAS, jenis_kode="BEBAS",
                        berat_kg=12_850, cara_timbang="SEKALI",
                        pihak_nama="CV Sumber Rejeki", nama_sopir="Slamet",
                        perangkat_kode="P1")
    await service.simpan_timbang_pertama(db, akun=petugas, data=jasa)

    r = await service.ringkasan_dashboard(db, service.FilterTransaksi())
    assert r.masuk_kg > 0
    assert r.keluar_kg == 0
    # Jasa timbang tak pernah ikut: barangnya tak masuk dan tak keluar.
    assert r.masuk_kg + r.keluar_kg < 12_850


# ─────────────────────────── T-21 ───────────────────────────

async def test_ubah_jenis_tiket_partai_tak_melempar_galat(db, petugas, admin,
                                                          supplier):
    """Tiket partai tak punya `timbang2_kg`, dan jalur hitung lamanya
    menghitung dari dua angka. Hasilnya TypeError — halaman galat 500, bukan
    kalimat yang bisa dibaca Admin. Temuan QA T-21."""
    from app.timbangan.models import CARA_PARTAI

    data = InputTimbang(
        kode="TRX-PT-001", arah=logic.MASUK, jenis_kode="BERAS_PK",
        berat_kg=70, cara_timbang=CARA_PARTAI, supplier_id=supplier.id,
        nama_sopir="Slamet", perangkat_kode="P1",
        muatan=[InputMuatan(jenis_kode="BERAS_PK", jumlah_karung=1,
                            tara_per_karung_kg=0.25, berat_acuan_kg=70)])
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.selesaikan_partai(db, akun=petugas, kode=trx.kode)

    # Ke komoditas KELUAR — arahnya ikut berbalik.
    await service.ubah_jenis(db, akun=admin, trx=trx, jenis_kode="BEKATUL",
                             alasan="salah pilih komoditas")
    assert trx.jenis_kode == "BEKATUL"
    # Beratnya tetap jumlah baris partainya, bukan nol atau angka karangan.
    assert float(trx.berat_bermuatan_kg or 0) == 70

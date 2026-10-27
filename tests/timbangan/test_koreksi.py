"""Koreksi mengubah HANYA yang dikoreksi, dan hasilnya dihitung ulang.

Lima temuan QA 11 September 2026 yang semuanya berpusat di alur koreksi.

**T-05.** Hitung ulang hanya berjalan bila `cara_timbang == DUA_KALI`. Jasa
timbang sekali yang dikoreksi 12.000 → 8.000 nettonya TETAP 12.000: angka yang
dikoreksi tersimpan, hasilnya tidak. Partai kecil lebih kacau lagi — koreksi
mengubah `timbang1_kg`, padahal pada partai angka itu cuma baris pertama.

**T-06.** Borang koreksi mengisi ulang SEMUA nilai dengan pembulatan, dan
rutenya memperlakukan tiap kolom terisi sebagai perubahan. Memperbaiki nama
sopir ikut mengubah tara 0,0858 → 0,086 dan nota 13.990,5 → 13.990. Dan
formulir yang dibuka sebelum orang lain mengoreksi MENGEMBALIKAN koreksi itu.

**T-07.** Koreksi yang membuat statusnya jadi wajib-periksa tak membuka lembar
pemeriksaan — jadi tiket bertanda INVESTIGASI tanpa satu pun lembar, dan tak
ada yang menindaklanjutinya.

**T-10.** Partai kecil: menambah "+70 kg" terduplikasi jadi 250 kg, dan
mengirim ulang formulir awal MENGHAPUS baris ketiga & keempat.

**T-13.** `aturan_snapshot` ditulis tiap penimbangan tetapi TAK PERNAH dibaca.
Tiket lama dinilai ulang dengan aturan yang berlaku hari ini — termasuk saat
dicetak, jadi bukti yang dicetak ulang bisa berbeda dari yang dulu diserahkan.
"""
from __future__ import annotations

import inspect

import pytest
from sqlalchemy import select

from app.timbangan import service
from app.timbangan.models import TimbanganPemeriksaan, TimbanganTransaksi

pytestmark = pytest.mark.usefixtures("supplier", "pelanggan_kledo")

GB = "GABAH_BASAH"


def _muatan(**kw):
    d = dict(jenis_kode=GB, tara_per_karung_kg=0.25)
    d.update(kw)
    return service.InputMuatan(**d)


async def _masuk(db, petugas, kunci="k", **kw):
    d = dict(kunci=kunci, arah="MASUK", jenis_kode=GB, berat_kg=15000,
             supplier_id=1, nomor_polisi="AD 1 A", nama_sopir="Joko",
             muatan=[_muatan()])
    d.update(kw)
    return await service.simpan_timbang_pertama(
        db, akun=petugas, data=service.InputTimbang(**d))


# ─────────────────────────── T-05 ───────────────────────────

@pytest.mark.asyncio
async def test_koreksi_jasa_timbang_sekali_menghitung_ulang(db, jenis_tersemai, petugas):
    """Repro QA test_T05. Netto tetap 12.000 padahal angkanya sudah 8.000."""
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=service.InputTimbang(
            kunci="sekali", arah="BEBAS", jenis_kode="BEBAS", berat_kg=12000,
            cara_timbang="SEKALI", supplier_id=1, nama_sopir="Darto",
            muatan=[service.InputMuatan(jenis_kode="BEBAS", jumlah_karung=1)]))
    await service.koreksi_transaksi(
        db, akun=petugas, trx=trx, perubahan={"timbang1_kg": 8000.0},
        alasan="salah ketik")
    assert float(trx.netto_timbangan_kg) == 8000.0


@pytest.mark.asyncio
async def test_hitung_ulang_punya_satu_jalur_per_cara(db):
    """Satu fungsi per `cara_timbang`, bukan satu `if` yang melupakan dua."""
    kode = inspect.getsource(service)
    assert "_hitung_ulang_koreksi" in kode
    fn = inspect.getsource(service._hitung_ulang_koreksi)
    # Ketiganya disebut: dua secara eksplisit, dan DUA_KALI sebagai sisanya.
    for cara in ("CARA_SEKALI", "CARA_PARTAI"):
        assert cara in fn, f"{cara} tak ditangani"
    assert "timbang2_kg is None" in fn, "jalur dua-kali tak ditangani"


# ─────────────────────────── T-06 ───────────────────────────

@pytest.mark.asyncio
async def test_koreksi_tak_menyentuh_kolom_yang_tak_diubah(db, jenis_tersemai, petugas):
    """Memperbaiki nama sopir tak boleh ikut membulatkan tara dan nota."""
    trx = await _masuk(db, petugas, kunci="t6",
                       muatan=[_muatan(tara_per_karung_kg=0.0858,
                                       jumlah_karung=100,
                                       berat_acuan_kg=13990.5)])
    await service.simpan_timbang_kedua(
        db, akun=petugas, kode=trx.kode, berat_kg=5000,
        muatan=[_muatan(tara_per_karung_kg=0.0858, jumlah_karung=100,
                        berat_acuan_kg=13990.5)])
    await db.refresh(trx, ["muatan"])
    tara_asli = float(trx.muatan[0].tara_per_karung_kg)
    nota_asli = float(trx.muatan[0].berat_acuan_kg)

    await service.koreksi_transaksi(
        db, akun=petugas, trx=trx, perubahan={"nama_sopir": "Slamet"},
        alasan="salah tulis nama")

    await db.refresh(trx, ["muatan"])
    assert float(trx.muatan[0].tara_per_karung_kg) == tara_asli, "tara ikut berubah"
    assert float(trx.muatan[0].berat_acuan_kg) == nota_asli, "nota ikut dibulatkan"


@pytest.mark.asyncio
async def test_borang_koreksi_mengirim_nilai_asli_untuk_dibandingkan():
    """Rutenya tak bisa tahu kolom mana yang benar-benar diubah tanpa nilai
    aslinya. Tanpa itu, tiap kolom terisi dianggap perubahan."""
    import pathlib

    html = (pathlib.Path(__file__).resolve().parents[2]
            / "app/timbangan/templates/koreksi.html").read_text()
    assert 'name="asli_' in html, "nilai asli tak ikut dikirim"


# ─────────────────────────── T-07 ───────────────────────────

@pytest.mark.asyncio
async def test_koreksi_yang_jadi_investigasi_membuka_lembar(db, jenis_tersemai, petugas):
    """Repro QA test_T06. Status INVESTIGASI tanpa lembar pemeriksaan berarti
    tak ada yang menindaklanjutinya."""
    trx = await _masuk(db, petugas, kunci="t7")
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=trx.kode, berat_kg=5000,
        muatan=[_muatan(jumlah_karung=100, berat_acuan_kg=9975)])
    assert trx.status_kontrol == "NORMAL"

    await service.koreksi_transaksi(
        db, akun=petugas, trx=trx, perubahan={},
        muatan=[_muatan(jumlah_karung=100, berat_acuan_kg=10300)],
        alasan="nota revisi")
    assert trx.status_kontrol == "INVESTIGASI"

    lembar = (await db.execute(
        select(TimbanganPemeriksaan)
        .where(TimbanganPemeriksaan.transaksi_id == trx.id)
    )).scalars().all()
    assert lembar, "status INVESTIGASI tanpa lembar pemeriksaan"


# ─────────────────────────── T-13 ───────────────────────────

@pytest.mark.asyncio
async def test_aturan_dibangun_dari_snapshot_tiket(db, jenis_tersemai, petugas):
    """`aturan_snapshot` ditulis tiap penimbangan dan tak pernah dibaca.

    Tiket lama lalu dinilai ulang dengan aturan yang berlaku HARI INI — dan
    saat bukti dicetak ulang, isinya bisa berbeda dari yang dulu diserahkan ke
    sopir.
    """
    assert hasattr(service, "aturan_dari_snapshot")
    trx = await _masuk(db, petugas, kunci="t13")
    aturan = service.aturan_dari_snapshot(trx)
    assert aturan is not None and aturan.kode == GB


# ─────────────────────────── T-10 ───────────────────────────

@pytest.mark.asyncio
async def test_tambah_partai_tak_menggandakan_saat_dikirim_ulang(db, jenis_tersemai, petugas):
    """"+70 kg" yang terkirim dua kali jadi 250 kg, bukan 180 kg.

    Penambahan partai tak punya penanda apa pun, jadi kiriman ulang — ketukan
    dobel, atau antrean luring yang mengirim lagi — tak bisa dibedakan dari
    karung berikutnya yang kebetulan sama beratnya.
    """
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=service.InputTimbang(
            kunci="p1", arah="MASUK", jenis_kode=GB, berat_kg=110,
            cara_timbang="PARTAI", supplier_id=1, nama_sopir="Tani",
            muatan=[_muatan()]))
    await service.tambah_penimbangan(db, akun=petugas, kode=trx.kode, berat=[70.0],
                                kunci="baris-1")
    await service.tambah_penimbangan(db, akun=petugas, kode=trx.kode, berat=[70.0],
                                kunci="baris-1")          # kiriman ULANG
    await db.refresh(trx, ["penimbangan"])
    assert len(trx.penimbangan) == 2, [b.berat_kg for b in trx.penimbangan]
    assert float(trx.timbang1_kg) == 180.0


@pytest.mark.asyncio
async def test_kirim_ulang_formulir_awal_tak_menghapus_baris_susulan(
        db, jenis_tersemai, petugas):
    """Mengirim ulang formulir AWAL menghapus baris ketiga & keempat.

    Formulir awal menulis ulang seluruh daftar baris dari satu angka —
    perilaku yang benar saat tiketnya baru, dan merusak saat barang susulan
    sudah masuk.
    """
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=service.InputTimbang(
            kunci="p2", arah="MASUK", jenis_kode=GB, berat_kg=100,
            cara_timbang="PARTAI", supplier_id=1, nama_sopir="Tani",
            muatan=[_muatan()]))
    await service.tambah_penimbangan(db, akun=petugas, kode=trx.kode,
                                berat=[50.0, 30.0], kunci="b2")
    await db.refresh(trx, ["penimbangan"])
    assert len(trx.penimbangan) == 3

    # Formulir awal dikirim ULANG dengan kunci yang sama.
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=service.InputTimbang(
            kunci="p2", arah="MASUK", jenis_kode=GB, berat_kg=100,
            cara_timbang="PARTAI", supplier_id=1, nama_sopir="Tani",
            muatan=[_muatan()]))
    await db.refresh(trx, ["penimbangan"])
    assert len(trx.penimbangan) == 3, "baris susulan terhapus"

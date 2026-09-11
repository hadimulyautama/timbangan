"""Kertas yang keluar dari printer harus mengatakan yang sebenarnya.

Temuan QA T-11, 11 September 2026. Cetak hanya memeriksa KEPEMILIKAN tiket.
Akibatnya dua hal yang sama-sama beredar sebagai bukti sah:

  · tiket yang sudah DIBATALKAN tercetak persis seperti struk normal —
    tak ada satu kata pun di kertasnya yang menyebut pembatalannya;
  · tiket yang masih TERBUKA (timbang kedua belum ada) tercetak lengkap
    dengan baris netto, padahal angkanya belum ada;
  · cetak ulang identik dengan cetakan pertama, jadi dua lembar untuk satu
    truk tak bisa dibedakan mana yang asli — dan begitu tiketnya pernah
    direvisi, dua lembar itu bisa memuat angka yang berbeda.

Bukti timbang adalah dokumen yang ditandatangani pihak luar. Yang dijaga di
sini bukan kerapian layar, melainkan apa yang boleh dipegang orang di luar
pabrik sebagai bukti.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.timbangan import epos, logic, service
from app.timbangan.models import (
    TIKET_DITUTUP_PAKSA,
    TIKET_SELESAI,
    TIKET_TERBUKA,
    TRX_AKTIF,
    TRX_VOID,
)


def _trx(**ubah):
    dasar = dict(
        kode="TRX-260911-P1-001", tanggal=date(2026, 9, 11),
        status_tiket=TIKET_SELESAI, status_transaksi=TRX_AKTIF,
        jumlah_revisi=0,
    )
    dasar.update(ubah)
    return SimpleNamespace(**dasar)


# ─────────────── Apa yang boleh dicetak ───────────────

def test_tiket_selesai_dan_aktif_boleh_dicetak():
    service.pastikan_boleh_cetak(_trx())


@pytest.mark.parametrize("keadaan,petunjuk", [
    ({"status_transaksi": TRX_VOID}, "dibatalkan"),
    ({"status_tiket": TIKET_TERBUKA}, "belum"),
    ({"status_tiket": TIKET_DITUTUP_PAKSA}, "ditutup paksa"),
])
def test_tiket_tak_sah_ditolak_dengan_sebabnya(keadaan, petunjuk):
    """Penolakan menyebut SEBABNYA. "Tidak bisa dicetak" saja membuat petugas
    mencoba lagi lewat jalan lain — dan salah satunya akan berhasil."""
    with pytest.raises(service.LayananError) as e:
        service.pastikan_boleh_cetak(_trx(**keadaan))
    assert petunjuk in str(e.value).lower()


# ─────────────── Cetak ulang ditandai ───────────────

def _aturan():
    return SimpleNamespace(nama="Gabah kering panen", acuan=logic.ACUAN_NOTA,
                           rahasia=False)


def _struk(cetakan_ke=1, revisi=0):
    trx = SimpleNamespace(
        kode="TRX-260911-P1-002", tanggal=date(2026, 9, 11),
        nomor_polisi="AD 1234 XY", nama_sopir="Suparno", catatan="",
        partai=False, penimbangan=[], berat_bermuatan_kg=12000,
        berat_kosong_kg=3760, netto_timbangan_kg=8240, berat_barang_kg=8240,
        berat_acuan_kg=8250, selisih_kg=-10, jumlah_karung=0, total_tara_kg=0,
        tara_lain_kg=0, jumlah_revisi=revisi,
        timbang1_waktu=datetime(2026, 9, 11, 2, 15, tzinfo=timezone.utc),
        timbang2_waktu=datetime(2026, 9, 11, 3, 40, tzinfo=timezone.utc),
    )
    return epos.struk_timbang(
        trx=trx, aturan=_aturan(), pihak="Karyo Tani", petugas="Rusdi",
        muatan=[], perusahaan="PT Hadi Mulya Utama", alamat="Masaran",
        telepon="+62 851", arah_masuk=True, tampilkan_selisih=False,
        cetakan_ke=cetakan_ke,
    )


def test_cetakan_pertama_tak_diberi_tanda():
    """Lembar asli tidak boleh dicurigai. Tanda hanya untuk yang memang ulang."""
    assert "CETAKAN ULANG" not in _struk(cetakan_ke=1)


def test_cetak_ulang_ditandai_beserta_nomornya():
    xml = _struk(cetakan_ke=3)
    assert "CETAKAN ULANG ke-3" in xml


def test_cetakan_menyebut_revisi_bila_tiket_pernah_dikoreksi():
    """Dua lembar untuk satu truk bisa memuat angka berbeda bila di antaranya
    ada koreksi. Nomor revisinya yang membuat keduanya bisa dibedakan."""
    xml = _struk(cetakan_ke=2, revisi=1)
    assert "Revisi 1" in xml


def test_tiket_tanpa_revisi_tak_menyebut_revisi():
    assert "Revisi" not in _struk(cetakan_ke=1, revisi=0)


# ─────────────── Revisi ikut tersimpan ───────────────

pytestmark_db = pytest.mark.usefixtures("jenis_tersemai")


@pytest.mark.usefixtures("jenis_tersemai")
async def test_riwayat_cetak_menyimpan_nomor_revisi(db, petugas, admin, supplier):
    """Sengketa dibuka berbulan-bulan kemudian, dan yang ditanya adalah
    "lembar mana yang dipegang orang itu". Tanpa nomor revisi di riwayat,
    pertanyaan itu tak punya jawaban."""
    from app.timbangan.service import InputMuatan, InputTimbang

    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=InputTimbang(
        kode="TRX-260911-P1-003", arah=logic.MASUK, jenis_kode="GABAH_BASAH",
        berat_kg=13_600, supplier_id=supplier.id, nomor_polisi="AD 1234 XY",
        nama_sopir="Slamet", perangkat_kode="P1",
        muatan=[InputMuatan(jenis_kode="GABAH_BASAH", jumlah_karung=120,
                            tara_per_karung_kg=0.25, berat_acuan_kg=10_048,
                            nomor_acuan="NOTA-01")]))
    await service.simpan_timbang_kedua(db, akun=petugas, kode=trx.kode,
                                       berat_kg=3_570)
    trx.jumlah_revisi = 2
    await db.commit()

    catatan = await service.catat_cetak(db, akun=admin, trx=trx, format="80MM")
    assert catatan.revisi == 2

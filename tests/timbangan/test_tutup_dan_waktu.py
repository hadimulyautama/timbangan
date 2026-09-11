"""Tiga pagar yang belum ada di pos timbang.

Temuan QA T-14, T-15, T-16 — 11 September 2026.

**T-14.** Pengiriman yang KURANG dari surat jalan ditutup SELESAI tanpa
lembar pemeriksaan dan tanpa terhitung di "perlu tindakan". Kekurangan 1.008
kg berakhir tanpa satu pun jejak yang menuntut seseorang menjelaskannya.

**T-15.** "Truk tidak jadi bongkar" menutup tiket tanpa timbang keluar, dan
siapa pun bisa menutup tiket orang lain. Muatan yang DITOLAK tetap keluar
dari pabrik, dan tanpa timbang keluar tak ada kontrol masuk−keluar sama
sekali (RANCANGAN §4.3) — truk bisa pergi membawa lebih banyak daripada yang
ia bawa masuk, dan tak ada angka yang bisa menunjukkannya.

**T-16.** Jam timbang bebas diisi. Timbang kedua bisa bertanggal Maret untuk
tiket September, memindahkan tiket ke periode yang sudah ditutup — dan
jendela sinkronisasi produksi yang tujuh hari tak akan pernah melihatnya.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.timbangan import logic, service
from app.timbangan.db import sekarang
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


# ─────────────────────────── T-14 ───────────────────────────

def test_kurang_dari_surat_jalan_menuntut_tindakan():
    """Statusnya harus ikut terhitung di "perlu tindakan" — sebuah kiriman
    yang kurang adalah persis keadaan yang perlu dijelaskan seseorang."""
    assert logic.KURANG in logic.STATUS_WAJIB_PERIKSA


async def test_pengiriman_kurang_membuka_lembar_pemeriksaan(db, petugas, supplier):
    """Lembar pemeriksaan ADALAH antreannya. Tanpa lembar, kekurangan itu tak
    muncul di layar siapa pun."""
    from app.models import Pelanggan
    from app.timbangan.models import TimbanganPemeriksaan
    from sqlalchemy import func, select

    p = Pelanggan(nama_pelanggan="Toko Beras Jaya")
    db.add(p)
    await db.flush()

    keluar = InputTimbang(
        kode="TRX-K-001", arah=logic.KELUAR, jenis_kode="BERAS",
        # `supplier_id` adalah kolom "pihak" yang generik; untuk arah KELUAR
        # layanan menaruhnya di `pelanggan_id`.
        berat_kg=4_000, supplier_id=p.id, nomor_polisi="AD 9 ZZ",
        nama_sopir="Budi", perangkat_kode="P1",
        muatan=[InputMuatan(jenis_kode="BERAS", jumlah_karung=0,
                            tara_per_karung_kg=0, berat_acuan_kg=10_000,
                            nomor_acuan="SJ-01")])
    await service.simpan_timbang_pertama(db, akun=petugas, data=keluar)
    # Keluar bermuatan 12.900: barangnya 8.900 kg, kurang 1.100 dari surat jalan.
    trx = await service.simpan_timbang_kedua(db, akun=petugas, kode="TRX-K-001",
                                             berat_kg=12_900)

    assert trx.status_kontrol == logic.KURANG
    jumlah = (await db.execute(select(func.count(TimbanganPemeriksaan.id))
                               .where(TimbanganPemeriksaan.transaksi_id == trx.id))
              ).scalar_one()
    assert jumlah == 1, "kekurangan ditutup tanpa satu pun antrean tindak lanjut"


# ─────────────────────────── T-15 ───────────────────────────

async def test_tutup_paksa_menolak_bila_truk_masih_bisa_ditimbang_keluar(
        db, petugas, supplier):
    """Muatan yang DITOLAK tetap wajib ditimbang keluar. Tanpa itu tak ada
    kontrol masuk−keluar, dan itulah satu-satunya angka yang menjaganya."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-T-001", supplier.id))
    with pytest.raises(service.LayananError) as e:
        await service.tutup_paksa(db, akun=petugas, trx=trx, alasan="mutu ditolak")
    assert "timbang keluar" in str(e.value).lower()


async def test_tutup_paksa_boleh_bila_truk_memang_pergi_tanpa_ditimbang(
        db, petugas, supplier):
    """Kadang truknya memang sudah pergi. Yang dituntut bukan mustahilnya,
    melainkan pengakuan tertulis bahwa itulah yang terjadi."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-T-002", supplier.id))
    hasil = await service.tutup_paksa(
        db, akun=petugas, trx=trx, alasan="truk pergi saat petugas istirahat",
        tanpa_timbang_keluar=True)
    assert hasil.status_tiket == "DITUTUP_PAKSA"


async def test_petugas_tak_bisa_menutup_tiket_orang_lain(db, petugas, petugas2,
                                                         supplier):
    """Andi menutup tiket Siti, dan Siti tak pernah tahu."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-T-003", supplier.id))
    with pytest.raises(service.LayananError) as e:
        await service.tutup_paksa(db, akun=petugas2, trx=trx, alasan="truk pergi",
                                  tanpa_timbang_keluar=True)
    assert "admin" in str(e.value).lower()


async def test_admin_tetap_bisa_menutup_tiket_siapa_pun(db, petugas, admin,
                                                        supplier):
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-T-004", supplier.id))
    hasil = await service.tutup_paksa(db, akun=admin, trx=trx, alasan="truk pergi",
                                      tanpa_timbang_keluar=True)
    assert hasil.status_tiket == "DITUTUP_PAKSA"


# ─────────────────────────── T-16 ───────────────────────────

async def test_jam_timbang_kedua_tak_boleh_di_masa_depan(db, petugas, supplier):
    await service.simpan_timbang_pertama(db, akun=petugas,
                                         data=_masuk("TRX-W-001", supplier.id))
    with pytest.raises(service.LayananError) as e:
        await service.simpan_timbang_kedua(
            db, akun=petugas, kode="TRX-W-001", berat_kg=3_570,
            waktu_operator=sekarang() + timedelta(hours=3))
    assert "masa depan" in str(e.value).lower()


async def test_jam_timbang_kedua_tak_boleh_sebelum_timbang_pertama(db, petugas,
                                                                   supplier):
    """Truk tak bisa keluar sebelum ia masuk."""
    await service.simpan_timbang_pertama(db, akun=petugas,
                                         data=_masuk("TRX-W-002", supplier.id))
    with pytest.raises(service.LayananError) as e:
        await service.simpan_timbang_kedua(
            db, akun=petugas, kode="TRX-W-002", berat_kg=3_570,
            waktu_operator=sekarang() - timedelta(days=30))
    assert "sebelum" in str(e.value).lower()


async def test_petugas_tak_bisa_memundurkan_jam_berbulan_bulan(db, petugas,
                                                               supplier):
    """Memundurkan tanggal memindahkan tiket ke periode yang sudah ditutup —
    dan ke luar jendela tujuh hari yang dibaca produksi."""
    data = _masuk("TRX-W-003", supplier.id)
    data.waktu_operator = sekarang() - timedelta(hours=200)
    with pytest.raises(service.LayananError) as e:
        await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert "admin" in str(e.value).lower()


async def test_admin_boleh_melewati_batas_jam_dan_tercatat(db, admin, supplier):
    """Pengecualiannya ada, tetapi ia bernama — dan namanya masuk audit."""
    from sqlalchemy import select

    from app.timbangan.models import TimbanganAudit

    data = _masuk("TRX-W-004", supplier.id)
    data.waktu_operator = sekarang() - timedelta(hours=200)
    trx = await service.simpan_timbang_pertama(db, akun=admin, data=data)
    # SQLite mengembalikan datetime tanpa zona; yang diuji di sini jamnya,
    # bukan cara penyimpanannya.
    assert trx.timbang1_waktu.replace(tzinfo=None) \
        == data.waktu_operator.replace(tzinfo=None)

    aksi = list((await db.execute(select(TimbanganAudit.aksi))).scalars())
    assert "WAKTU_MUNDUR" in aksi


async def test_jam_dalam_batas_tetap_bebas_diisi(db, petugas, supplier):
    """Pagar ini tak boleh menghalangi alasan ia ada: petugas yang mencatat
    terlambat satu-dua jam."""
    data = _masuk("TRX-W-005", supplier.id)
    data.waktu_operator = sekarang() - timedelta(hours=2)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode="TRX-W-005", berat_kg=3_570)
    assert trx.status_tiket == "SELESAI"

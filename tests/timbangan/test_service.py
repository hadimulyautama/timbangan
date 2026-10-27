"""Uji lapisan layanan: alur timbang dua tahap, idempotensi, koreksi, audit.

Yang dijaga di sini adalah janji-janji operasional modul, bukan rumusnya
(rumus diuji di `test_logic.py`):

  · timbang pertama membuka tiket, timbang kedua menutup dan menilai
  · kiriman ulang dari antrean offline tidak melahirkan transaksi kembar
  · arah barang menentukan mana angka bermuatan dan mana angka kosong
  · tanggal mengikuti timbang kedua
  · petugas timbang pertama & kedua keduanya tercatat
  · data tidak pernah hilang: batal & tutup paksa meninggalkan jejak
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from hmu_core import ProsesTerpadu, User

from app.timbangan import logic, service
from app.timbangan.models import (
    CARA_PARTAI,
    CARA_SEKALI,
    PEMERIKSAAN_DIBUKA,
    PEMERIKSAAN_SELESAI,
    TIKET_DITUTUP_PAKSA,
    TIKET_SELESAI,
    TIKET_SELESAI,
    TIKET_TERBUKA,
    TRX_VOID,
    TimbanganAudit,
    TimbanganJenis,
    TimbanganPemeriksaan,
    TimbanganTransaksi,
)
from app.timbangan.service import InputMuatan, InputTimbang

pytestmark = pytest.mark.usefixtures("jenis_tersemai", "supplier", "pelanggan_kledo")


def masuk_gabah(kode: str, supplier_id: int | None, berat: float) -> InputTimbang:
    return InputTimbang(
        kode=kode,
        arah=logic.MASUK,
        jenis_kode="GABAH_BASAH",
        berat_kg=berat,
        supplier_id=supplier_id,
        nomor_polisi=" ad 1234 xy ",
        muatan=[InputMuatan(
            jenis_kode="GABAH_BASAH", jumlah_karung=120,
            tara_per_karung_kg=0.25, berat_acuan_kg=10_048,
            nomor_acuan="NOTA-01",
        )],
        perangkat_kode="P1",
            nama_sopir="Slamet",
    )


# ─────────────────── Penyemaian master ───────────────────

async def test_penyemaian_tidak_menimpa_aturan_yang_sudah_disetel(db):
    """Aturan yang sudah diubah manajemen di DB tidak boleh dikembalikan."""
    baris = (await db.execute(
        select(TimbanganJenis).where(TimbanganJenis.kode == "GABAH_BASAH")
    )).scalars().one()
    baris.ambang_nilai = 3.0
    await db.commit()

    assert await service.pastikan_jenis(db) == 0
    aturan = await service.aturan_untuk(db, "GABAH_BASAH")
    assert aturan.ambang_nilai == 3.0


async def test_aturan_dibaca_dari_db_bukan_dari_kode(db):
    peta = await service.peta_aturan(db)
    assert set(peta) == {a.kode for a in logic.JENIS_AWAL}


# ─────────────────── Alur dua tahap ───────────────────

async def test_timbang_pertama_membuka_tiket(db, petugas, supplier):
    orang = User(nama="Budi", role="operator", status="aktif")
    db.add(orang)
    await db.flush()
    petugas.user_id = orang.id
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=masuk_gabah("TRX-20260830-P1-001", supplier.id, 13_600)
    )
    assert trx.status_tiket == TIKET_TERBUKA
    assert trx.timbang1_petugas_id == petugas.id
    assert trx.timbang2_kg is None
    assert trx.status_kontrol is None        # belum dinilai — belum lengkap
    assert trx.nomor_polisi == "AD 1234 XY"  # dinormalkan
    assert len(trx.muatan) == 1

    terbuka = await service.tiket_terbuka(db)
    assert [b.trx.kode for b in terbuka] == ["TRX-20260830-P1-001"]

    proses = (await db.execute(select(ProsesTerpadu).where(
        ProsesTerpadu.aplikasi == "timbangan",
        ProsesTerpadu.id_sumber == str(trx.id),
    ))).scalar_one()
    assert proses.kode == trx.kode
    assert proses.jenis == "penimbangan"
    assert proses.status == "berjalan"
    assert proses.metadata_domain["nomor_polisi"] == "AD 1234 XY"
    assert proses.metadata_domain["supplier_id"] == supplier.id
    assert proses.pelaksana_id == orang.id
    await db.refresh(proses, ["arus"])
    assert proses.arus == []  # menimbang tidak mengubah stok barang


async def test_timbang_kedua_menutup_dan_menilai(db, petugas, petugas2, supplier):
    """Contoh Anton: netto kontrol 10.000 vs nota 10.048 → perlu pemeriksaan."""
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=masuk_gabah("TRX-20260830-P1-002", supplier.id, 13_600)
    )
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas2, kode="TRX-20260830-P1-002", berat_kg=3_570
    )

    assert trx.status_tiket == TIKET_SELESAI
    assert trx.berat_bermuatan_kg == 13_600      # masuk: datang penuh
    assert trx.berat_kosong_kg == 3_570
    assert trx.netto_timbangan_kg == 10_030
    assert trx.berat_barang_kg == 10_000
    assert trx.selisih_kg == -48
    assert trx.status_kontrol == logic.PERLU_PEMERIKSAAN
    # Dua orang berbeda, KEDUANYA tercatat — dan itu yang penting: siapa
    # menimbang apa tak boleh hilang hanya karena kertasnya memuat satu nama.
    #
    # ⚠ `petugas_bukti_id` DIBUANG 30 September 2026. Baris di sini dulu
    # berbunyi "yang tertera di bukti yang kedua"; pemilik memutuskan yang
    # tertera adalah akun yang MENCETAK, sebab blok itu ruang tanda tangan dan
    # yang menandatangani adalah yang menyerahkan kertasnya kepada sopir.
    # Lihat `test_struk_menyebut_akun_yang_mencetak` di `test_web`.
    assert trx.timbang1_petugas_id == petugas.id
    assert trx.timbang2_petugas_id == petugas2.id

    proses = (await db.execute(select(ProsesTerpadu).where(
        ProsesTerpadu.aplikasi == "timbangan",
        ProsesTerpadu.id_sumber == str(trx.id),
    ))).scalar_one()
    assert proses.status == "selesai"
    assert proses.metadata_domain["berat_barang_kg"] == trx.berat_barang_kg
    assert proses.waktu_selesai == trx.timbang2_waktu


async def test_arah_keluar_membalik_urutan_angka(db, petugas, supplier):
    """Pengiriman: truk datang kosong, pergi bermuatan."""
    data = InputTimbang(
        kode="TRX-20260830-P1-003",
        arah=logic.KELUAR,
        jenis_kode="BEKATUL",
        berat_kg=6_200,                       # timbang pertama = KOSONG
        supplier_id=supplier.id,
        nomor_polisi="AD 9 ZZ",
        muatan=[InputMuatan(
            jenis_kode="BEKATUL", jumlah_karung=240,
            tara_per_karung_kg=0.05, berat_acuan_kg=12_000,
            nomor_acuan="SJ-77",
        )],
            nama_sopir="Slamet",
    )
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=18_220
    )

    assert trx.berat_kosong_kg == 6_200
    assert trx.berat_bermuatan_kg == 18_220
    assert trx.netto_timbangan_kg == 12_020
    assert trx.berat_barang_kg == 12_008
    assert trx.status_kontrol == logic.NORMAL
    assert trx.batas_bawah_kg == 0            # kiriman tidak boleh kurang


async def test_pengiriman_kurang_dari_surat_jalan_ditandai(db, petugas, supplier):
    data = InputTimbang(
        kode="TRX-20260830-P1-004", arah=logic.KELUAR, jenis_kode="BEKATUL",
        berat_kg=6_200, supplier_id=supplier.id, nomor_polisi="AD 8 KK",
        muatan=[InputMuatan(
            jenis_kode="BEKATUL", jumlah_karung=240,
            tara_per_karung_kg=0.05, berat_acuan_kg=12_000,
        )],
            nama_sopir="Slamet",
    )
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=18_200
    )
    assert trx.status_kontrol == logic.KURANG


async def test_tanggal_mengikuti_timbang_kedua(db, admin, supplier):
    """Truk masuk menjelang tengah malam tercatat di hari ia selesai.

    Jamnya dihitung mundur dari SEKARANG, bukan ditulis sebagai tanggal
    tetap. Tanggal tetap di masa lalu makin lama makin jauh, dan sejak T-16
    memundurkan jam lebih dari batas yang disetel memang ditolak — uji yang
    memakainya akan gagal suatu hari karena kalendernya, bukan karena
    kodenya.
    """
    from app.timbangan.db import sekarang

    # Dua hari lalu pukul 23:40 → keesokan harinya 01:15. Keduanya PASTI di
    # masa lalu, jadi ujinya tak bergantung pada jam berapa ia dijalankan.
    # Pelakunya Admin: memundurkan jam lebih dari batas yang disetel memang
    # hanya boleh Admin sejak T-16, dan yang diuji di sini bukan pagar itu.
    tengah_malam = sekarang().replace(hour=23, minute=40, second=0, microsecond=0) \
        - timedelta(days=2)
    data = masuk_gabah("TRX-20260830-P1-005", supplier.id, 13_600)
    data.waktu_operator = tengah_malam
    await service.simpan_timbang_pertama(db, akun=admin, data=data)

    keesokan = tengah_malam + timedelta(hours=1, minutes=35)
    assert keesokan.date() != tengah_malam.date(), "ujinya harus melewati tengah malam"
    trx = await service.simpan_timbang_kedua(
        db, akun=admin, kode=data.kode, berat_kg=3_570,
        waktu_operator=keesokan,
    )
    assert trx.tanggal == keesokan.date()


async def test_jasa_timbang_sekali_langsung_selesai(db, petugas):
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=InputTimbang(
        kode="TRX-20260830-P1-006", arah=logic.BEBAS, jenis_kode="BEBAS",
        berat_kg=12_850, cara_timbang=CARA_SEKALI,
        muatan=[InputMuatan(jenis_kode="BEBAS", jumlah_karung=1)],
        supplier_id=1,
            nama_sopir="Slamet",
    ))
    assert trx.status_tiket == TIKET_SELESAI
    assert trx.netto_timbangan_kg == 12_850
    assert trx.status_kontrol == logic.TANPA_KONTROL
    assert trx.berat_kosong_kg is None


# ─────────────────── Ketahanan offline ───────────────────

async def test_kiriman_ulang_tidak_melahirkan_transaksi_kembar(db, petugas, supplier):
    """Antrean offline boleh mengirim ulang berkali-kali tanpa akibat."""
    data = masuk_gabah("TRX-20260830-P1-007", supplier.id, 13_600)
    for _ in range(3):
        await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    jumlah = (await db.execute(
        select(func.count(TimbanganTransaksi.id))
    )).scalar_one()
    assert jumlah == 1
    # Muatan juga tidak menumpuk.
    trx = await service.ambil_kode(db, data.kode)
    assert len(trx.muatan) == 1


async def test_kiriman_ulang_tidak_memundurkan_transaksi_yang_sudah_selesai(
    db, petugas, supplier
):
    data = masuk_gabah("TRX-20260830-P1-008", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )

    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert trx.status_tiket == TIKET_SELESAI
    assert trx.timbang2_kg == 3_570


async def test_timbang_kedua_berulang_dengan_angka_sama_diterima(db, petugas, supplier):
    """Kirim ulang dari antrean luring: angka yang sama, hasil yang sama.

    Menolak yang ini akan membuat antrean luring macet selamanya — ia mengirim
    ulang kiriman yang sama tiap kali sinyal kembali.
    """
    data = masuk_gabah("TRX-20260830-P1-009", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.simpan_timbang_kedua(db, akun=petugas, kode=data.kode, berat_kg=3_570)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    assert trx.timbang2_kg == 3_570


async def test_timbang_kedua_dengan_angka_BERBEDA_ditolak(db, petugas, supplier):
    """Uji ini dulu berbunyi sebaliknya: 9.999 kg dikirim ke tiket yang sudah
    selesai dan diam-diam dibuang, lalu diperiksa bahwa yang tersimpan tetap
    3.570. Perilaku itulah temuan QA T-03.

    Layarnya menjawab "Timbangan selesai dan tersimpan", tanpa satu pun jejak
    audit — jadi yang mengetiknya pulang dengan yakin pekerjaannya tercatat.
    Itu keadaan terburuk yang bisa dibuat sebuah layar: bukan gagal, melainkan
    berbohong.
    """
    data = masuk_gabah("TRX-20260830-P1-009b", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.simpan_timbang_kedua(db, akun=petugas, kode=data.kode, berat_kg=3_570)
    with pytest.raises(service.LayananError) as e:
        await service.simpan_timbang_kedua(
            db, akun=petugas, kode=data.kode, berat_kg=9_999
        )
    assert "sudah diselesaikan" in str(e.value)
    trx = await service.ambil_kode(db, data.kode)
    assert float(trx.timbang2_kg) == 3_570.0


# ─────────────────── Pemeriksaan ───────────────────

async def test_status_wajib_periksa_membuka_lembar_pemeriksaan(
    db, petugas, supplier
):
    data = masuk_gabah("TRX-20260830-P1-010", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    lembar = await service.pemeriksaan_transaksi(db, trx.id)
    assert lembar is not None and lembar.status == PEMERIKSAAN_DIBUKA


async def test_pemeriksaan_selesai_dengan_catatan_resolusi(
    db, petugas, admin2, supplier
):
    """Selesai berarti sudah ditelusuri dan tercatat — bukan berarti bersih."""
    data = masuk_gabah("TRX-20260830-P1-011", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    lembar = await service.pemeriksaan_transaksi(db, trx.id)

    selesai = await service.selesaikan_pemeriksaan(
        db, akun=admin2, lembar=lembar,
        langkah={"langkah_ulang_timbang": "Ditimbang ulang, angka sama."},
        kategori_hasil="SUSUT_PERJALANAN",
        catatan_resolusi="Hujan di perjalanan, karung basah lalu menyusut.",
        dilaporkan_ke="Miftah",
    )
    assert selesai.status == PEMERIKSAAN_SELESAI
    assert selesai.ditutup_oleh_id == admin2.id


async def test_petugas_tidak_boleh_menutup_pemeriksaan(db, petugas, supplier):
    data = masuk_gabah("TRX-20260830-P1-012", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    lembar = await service.pemeriksaan_transaksi(db, trx.id)
    with pytest.raises(service.LayananError, match="Admin"):
        await service.selesaikan_pemeriksaan(
            db, akun=petugas, lembar=lembar, langkah={},
            kategori_hasil="SELISIH_WAJAR", catatan_resolusi="aman",
        )


async def test_resolusi_wajib_beralasan(db, petugas, admin2, supplier):
    data = masuk_gabah("TRX-20260830-P1-013", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    lembar = await service.pemeriksaan_transaksi(db, trx.id)
    with pytest.raises(service.LayananError, match="resolusi"):
        await service.selesaikan_pemeriksaan(
            db, akun=admin2, lembar=lembar, langkah={},
            kategori_hasil="SELISIH_WAJAR", catatan_resolusi="   ",
        )


# ─────────────────── Koreksi, batal, tutup paksa ───────────────────

async def test_koreksi_menghitung_ulang_dan_meninggalkan_jejak(
    db, petugas, supplier
):
    data = masuk_gabah("TRX-20260830-P1-014", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    assert trx.status_kontrol == logic.PERLU_PEMERIKSAAN

    # Salah ketik: nota sebenarnya 10.010, bukan 10.048.
    trx = await service.koreksi_transaksi(
        db, akun=petugas, trx=trx,
        perubahan={},
        muatan=[InputMuatan(
            jenis_kode="GABAH_BASAH", jumlah_karung=120,
            tara_per_karung_kg=0.25, berat_acuan_kg=10_010,
            nomor_acuan="NOTA-01",
        )],
        alasan="Salah ketik berat nota",
    )
    assert trx.selisih_kg == -10
    assert trx.status_kontrol == logic.NORMAL
    assert trx.jumlah_revisi == 1

    jejak = (await db.execute(
        select(TimbanganAudit).where(TimbanganAudit.aksi == "KOREKSI")
    )).scalars().all()
    assert len(jejak) == 1
    assert "10048" in jejak[0].nilai_sebelum.replace(".0", "")


async def test_void_menyimpan_data_dan_menuntut_alasan(db, petugas, admin2, supplier):
    data = masuk_gabah("TRX-20260830-P1-015", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    # Tiketnya diselesaikan lebih dulu: sejak 30 September 2026 petugas BOLEH
    # membatalkan tiket yang masih terbuka (keputusan pemilik), dan yang
    # dijaga di sini penolakan atas transaksi yang SUDAH LENGKAP — di situlah
    # angkanya sudah jadi dasar keputusan orang lain.
    trx.status_tiket = TIKET_SELESAI
    with pytest.raises(service.LayananError, match="sudah ditimbang kedua"):
        await service.void_transaksi(db, akun=petugas, trx=trx, alasan="salah")
    with pytest.raises(service.LayananError, match="alasan"):
        await service.void_transaksi(db, akun=admin2, trx=trx, alasan="  ")

    trx = await service.void_transaksi(
        db, akun=admin2, trx=trx, alasan="Truk salah masuk antrean"
    )
    assert trx.status_transaksi == TRX_VOID
    # Barisnya tetap ada — tidak pernah dihapus permanen.
    assert (await db.execute(select(func.count(TimbanganTransaksi.id)))).scalar_one() == 1


async def test_tutup_paksa_tiket_yang_tidak_jadi_bongkar(db, petugas, supplier):
    """Alasannya kini SELALU "truk pergi tanpa ditimbang keluar".

    Uji ini dulu beralasan "mutu ditolak" dan lulus — yaitu persis celah
    T-15: muatan yang ditolak tetap keluar dari pabrik, dan menutup tiketnya
    tanpa timbang keluar meniadakan satu-satunya kontrol masuk−keluar yang
    ada. Muatan ditolak sekarang diselesaikan lewat timbang kedua biasa.
    """
    data = masuk_gabah("TRX-20260830-P1-016", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    trx = await service.tutup_paksa(
        db, akun=petugas, trx=trx, alasan="Truk pergi saat petugas istirahat",
        tanpa_timbang_keluar=True,
    )
    assert trx.status_tiket == TIKET_DITUTUP_PAKSA
    assert trx.status_kontrol is None
    assert not await service.tiket_terbuka(db)

    with pytest.raises(service.LayananError, match="terbuka"):
        await service.tutup_paksa(db, akun=petugas, trx=trx, alasan="lagi",
                                  tanpa_timbang_keluar=True)


async def test_timbang_kedua_ditolak_setelah_tutup_paksa(db, petugas, supplier):
    data = masuk_gabah("TRX-20260830-P1-017", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.tutup_paksa(db, akun=petugas, trx=trx, alasan="truk pergi",
                              tanpa_timbang_keluar=True)
    with pytest.raises(service.LayananError, match="ditutup paksa"):
        await service.simpan_timbang_kedua(
            db, akun=petugas, kode=data.kode, berat_kg=3_570
        )


# ─────────────────── Tara standar ───────────────────

async def test_sampling_baru_mengganti_bukan_menimpa(db, admin2, supplier):
    pertama = await service.simpan_tara_standar(
        db, akun=admin2, supplier_id=supplier.id, jenis_kode="BERAS_PK",
        jumlah_sampel=20, total_berat_kg=1.8,
    )
    assert pertama.tara_per_karung_kg == pytest.approx(0.09)

    kedua = await service.simpan_tara_standar(
        db, akun=admin2, supplier_id=supplier.id, jenis_kode="BERAS_PK",
        jumlah_sampel=20, total_berat_kg=2.0, alasan="Ganti jenis karung",
    )
    await db.refresh(pertama)
    assert pertama.status == "DIGANTI"
    assert kedua.status == "BERLAKU"

    berlaku = await service.tara_berlaku(
        db, supplier_id=supplier.id, jenis_kode="BERAS_PK"
    )
    assert berlaku.id == kedua.id


async def test_tara_khusus_pihak_menang_atas_tara_umum(db, admin2, supplier):
    await service.simpan_tara_standar(
        db, akun=admin2, supplier_id=None, jenis_kode="BERAS_PK",
        jumlah_sampel=20, total_berat_kg=2.0,          # umum → 0,10
    )
    await service.simpan_tara_standar(
        db, akun=admin2, supplier_id=supplier.id, jenis_kode="BERAS_PK",
        jumlah_sampel=20, total_berat_kg=1.7,          # khusus → 0,085
    )
    aturan = await service.aturan_untuk(db, "BERAS_PK")
    tara, asal = await service.tara_disarankan(
        db, supplier_id=supplier.id, aturan=aturan
    )
    assert tara == pytest.approx(0.085)
    assert asal is not None and asal.supplier_id == supplier.id


async def test_tara_bawaan_dipakai_bila_belum_ada_sampling(db, supplier):
    aturan = await service.aturan_untuk(db, "BERAS_PK")
    tara, asal = await service.tara_disarankan(
        db, supplier_id=supplier.id, aturan=aturan
    )
    assert tara == aturan.tara_default()
    assert asal is None


# ─────────────────── Cetak ───────────────────

async def test_cetak_ulang_wajib_beralasan(db, petugas, supplier):
    data = masuk_gabah("TRX-20260830-P1-018", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    # Timbang keduanya diselesaikan dulu. Uji ini dulu mencetak tiket yang
    # masih TERBUKA dan lulus — persis celah T-11: struk lengkap dengan baris
    # netto keluar untuk truk yang angkanya belum ada.
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )

    pertama = await service.catat_cetak(db, akun=petugas, trx=trx)
    assert pertama.urutan == 1 and not pertama.ulang

    with pytest.raises(service.LayananError, match="alasan"):
        await service.catat_cetak(db, akun=petugas, trx=trx)

    kedua = await service.catat_cetak(
        db, akun=petugas, trx=trx, alasan="Kertas tersangkut"
    )
    assert kedua.urutan == 2 and kedua.ulang


# ─────────────────── Ringkasan ───────────────────

async def test_ringkasan_menghitung_tiket_dan_pemeriksaan(db, petugas, supplier):
    selesai = masuk_gabah("TRX-20260830-P1-019", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=selesai)
    await service.simpan_timbang_kedua(
        db, akun=petugas, kode=selesai.kode, berat_kg=3_570
    )
    await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=masuk_gabah("TRX-20260830-P1-020", supplier.id, 12_000),
    )

    r = await service.ringkasan_dashboard(db, service.FilterTransaksi())
    assert r.jumlah == 2
    assert r.tiket_terbuka == 1
    assert r.perlu_periksa == 1
    assert r.pemeriksaan_terbuka == 1


async def test_transaksi_void_tidak_ikut_terhitung(db, petugas, admin2, supplier):
    data = masuk_gabah("TRX-20260830-P1-021", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.void_transaksi(db, akun=admin2, trx=trx, alasan="salah antrean")

    assert await service.hitung_transaksi(db, service.FilterTransaksi()) == 0
    assert await service.hitung_transaksi(
        db, service.FilterTransaksi(sertakan_void=True)
    ) == 1


# ─────────────── Nomor polisi wajib ───────────────

async def test_koreksi_menolak_mengosongkan_nomor_polisi(
    db, petugas, supplier, jenis_tersemai
):
    """Rute koreksi memperlakukan kolom kosong sebagai "tidak diubah", jadi
    pagar ini tidak terjangkau dari layar. Ia menjaga pintu lain: pemakaian
    langsung layanan ini — antrean luring, perbaikan data, atau apa pun yang
    ditulis kemudian.
    """
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=InputTimbang(
        kode="TRX-20260831-P1-001", arah=logic.MASUK, jenis_kode="GABAH_BASAH",
        berat_kg=13_600, supplier_id=supplier.id, nomor_polisi="AD 5 BB",
        muatan=[InputMuatan(jenis_kode="GABAH_BASAH", jumlah_karung=120,
                            tara_per_karung_kg=0.25, berat_acuan_kg=10_000)],
            nama_sopir="Slamet",
    ))
    with pytest.raises(service.LayananError, match="Nomor polisi wajib"):
        await service.koreksi_transaksi(
            db, akun=petugas, trx=trx, alasan="Salah ketik",
            perubahan={"nomor_polisi": "   "},
        )
    assert trx.nomor_polisi == "AD 5 BB"


async def test_transfer_internal_boleh_tanpa_nomor_polisi(
    db, petugas, jenis_tersemai
):
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=InputTimbang(
        kode="TRX-20260831-P1-002", arah=logic.TRANSFER, jenis_kode="TRANSFER",
        berat_kg=13_600, pihak_nama="Gudang 1 → Gudang 2",
            nama_sopir="Slamet",
    ))
    assert trx.nomor_polisi is None


async def test_koreksi_menolak_mengosongkan_nama_sopir(
    db, petugas, supplier, jenis_tersemai
):
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=InputTimbang(
        kode="TRX-20260901-P1-001", arah=logic.MASUK, jenis_kode="GABAH_BASAH",
        berat_kg=13_600, supplier_id=supplier.id, nomor_polisi="AD 5 BB",
        nama_sopir="Slamet",
        muatan=[InputMuatan(jenis_kode="GABAH_BASAH", jumlah_karung=120,
                            tara_per_karung_kg=0.25, berat_acuan_kg=10_000)],
    ))
    with pytest.raises(service.LayananError, match="Nama sopir wajib"):
        await service.koreksi_transaksi(
            db, akun=petugas, trx=trx, alasan="coba",
            perubahan={"nama_sopir": "   "},
        )
    assert trx.nama_sopir == "Slamet"


async def test_koreksi_menolak_mengosongkan_nama_pihak(
    db, petugas, jenis_tersemai
):
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=InputTimbang(
        kode="TRX-20260901-P1-002", arah=logic.TRANSFER, jenis_kode="TRANSFER",
        berat_kg=13_600, pihak_nama="Gudang 1 → Gudang 2", nama_sopir="Slamet",
    ))
    with pytest.raises(service.LayananError, match="wajib diisi"):
        await service.koreksi_transaksi(
            db, akun=petugas, trx=trx, alasan="coba",
            perubahan={"pihak_nama": "  "},
        )
    assert trx.pihak_nama == "Gudang 1 → Gudang 2"


# ─────────────────── Partai kecil (satu kode, banyak timbang) ───────────────────
#
# Petani dan pedagang menjual sedikit-sedikit, barangnya ditimbang satu per
# satu, dan kedatangannya bisa bertahap. Yang dijaga di sini: kodenya tetap
# satu, angkanya tidak pernah dibulatkan, dan tiketnya boleh menunggu.

def partai(kode: str, berat: float, pihak: str = "Pak Warno") -> InputTimbang:
    """Partai kecil: tanpa nopol, tanpa sopir, tanpa tara karung."""
    return InputTimbang(
        kode=kode, arah=logic.MASUK, jenis_kode="GABAH_BASAH",
        berat_kg=berat, cara_timbang=CARA_PARTAI,
        supplier_id=1, perangkat_kode="P1",
    )


async def test_partai_dibuka_tanpa_nopol_dan_sopir(db, petugas):
    """Yang datang membawa beberapa karung adalah orangnya sendiri."""
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-001", 12.5)
    )
    assert trx.status_tiket == TIKET_TERBUKA
    assert trx.partai
    assert trx.nomor_polisi is None and trx.nama_sopir is None
    assert [float(p.berat_kg) for p in trx.penimbangan] == [12.5]
    assert float(trx.timbang1_kg) == 12.5


async def test_partai_menjumlah_apa_adanya_tanpa_pembulatan(db, petugas):
    """2 kg ya 2 kg — kelipatan 10 kg milik jembatan truk, bukan alat ini."""
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-002", 12.5)
    )
    for w in (2, 7.25, 40):
        trx = await service.tambah_penimbangan(
            db, akun=petugas, kode="TRX-20260902-P1-002", berat_kg=w
        )
    assert float(trx.timbang1_kg) == 61.75
    assert trx.status_tiket == TIKET_TERBUKA, "tiket harus tetap menunggu"


async def test_partai_menolak_angka_di_atas_kapasitas_timbangan_kecil(db, petugas):
    """Salah ketik 1500 untuk 15 kg tertahan di sini, bukan di laporan bulan depan."""
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-003", 12.5)
    )
    with pytest.raises(service.LayananError, match="timbangan kecil"):
        await service.tambah_penimbangan(
            db, akun=petugas, kode="TRX-20260902-P1-003", berat_kg=1_500
        )


async def test_partai_hapus_baris_menomori_ulang_dan_menghitung_ulang(db, petugas):
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-004", 12.5)
    )
    for w in (2, 7.25):
        await service.tambah_penimbangan(
            db, akun=petugas, kode="TRX-20260902-P1-004", berat_kg=w
        )
    trx = await service.hapus_penimbangan(
        db, akun=petugas, kode="TRX-20260902-P1-004", urutan=2
    )
    assert [p.urutan for p in trx.penimbangan] == [1, 2]
    assert [float(p.berat_kg) for p in trx.penimbangan] == [12.5, 7.25]
    assert float(trx.timbang1_kg) == 19.75


async def test_partai_baris_terakhir_tak_bisa_dihapus(db, petugas):
    """Menghapusnya menyisakan tiket tanpa angka sama sekali — batalkan saja."""
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-005", 12.5)
    )
    with pytest.raises(service.LayananError, match="batalkan"):
        await service.hapus_penimbangan(
            db, akun=petugas, kode="TRX-20260902-P1-005", urutan=1
        )


async def test_partai_selesai_menjadikan_jumlah_sebagai_netto(db, petugas):
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-006", 18)
    )
    for w in (23.5, 9):
        await service.tambah_penimbangan(
            db, akun=petugas, kode="TRX-20260902-P1-006", berat_kg=w
        )
    trx = await service.selesaikan_partai(
        db, akun=petugas, kode="TRX-20260902-P1-006", jumlah_karung=3
    )
    assert trx.status_tiket == TIKET_SELESAI
    assert trx.timbang2_kg is None, "tak ada timbang kosong pada partai kecil"
    assert float(trx.netto_timbangan_kg) == 50.5
    assert float(trx.berat_barang_kg) == 50.5
    assert float(trx.total_tara_kg) == 0


async def test_partai_yang_sudah_ditutup_tak_bisa_ditambah(db, petugas):
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-007", 18)
    )
    await service.selesaikan_partai(db, akun=petugas, kode="TRX-20260902-P1-007", jumlah_karung=1)
    with pytest.raises(service.LayananError, match="sudah ditutup"):
        await service.tambah_penimbangan(
            db, akun=petugas, kode="TRX-20260902-P1-007", berat_kg=5
        )


async def test_partai_boleh_menunggu_lintas_hari(db, petugas):
    """Kedatangan bertahap: tiket menua tanpa kehilangan angkanya."""
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-008", 18)
    )
    trx = await service.ambil_kode(db, "TRX-20260902-P1-008")
    trx.timbang1_waktu = trx.timbang1_waktu - timedelta(days=2)
    await db.commit()

    trx = await service.tambah_penimbangan(
        db, akun=petugas, kode="TRX-20260902-P1-008", berat_kg=6
    )
    assert float(trx.timbang1_kg) == 24
    assert trx.status_tiket == TIKET_TERBUKA


async def test_partai_menerima_beberapa_berat_sekaligus(db, petugas):
    """Petugas menimbang lima karung berturut-turut lalu mencatatnya sekali —
    bukan bolak-balik ke layar setiap satu karung."""
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-009", 12.5)
    )
    trx = await service.tambah_penimbangan(
        db, akun=petugas, kode="TRX-20260902-P1-009", berat=[8, 31.25, 6]
    )
    assert [float(p.berat_kg) for p in trx.penimbangan] == [12.5, 8, 31.25, 6]
    assert float(trx.timbang1_kg) == 57.75
    assert [p.urutan for p in trx.penimbangan] == [1, 2, 3, 4]


async def test_partai_menolak_kiriman_tanpa_satu_pun_berat(db, petugas):
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=partai("TRX-20260902-P1-010", 12.5)
    )
    with pytest.raises(service.LayananError, match="Isi dulu berat"):
        await service.tambah_penimbangan(
            db, akun=petugas, kode="TRX-20260902-P1-010", berat=[]
        )


# ─────────────────── Retur ───────────────────
#
# Retur bukan barang masuk atau barang keluar dengan tanda minus. Yang
# membuatnya berdiri sendiri adalah lawan transaksinya yang menyilang: barang
# yang dikembalikan pelanggan datang MASUK, dan barang yang kita tolak
# berangkat KELUAR ke supplier. Salah menaruhnya berarti mencari nama
# pelanggan di daftar supplier.


async def _pelanggan(db, nama: str = "Toko Beras Handoko"):
    from app.models import Pelanggan

    p = Pelanggan(nama_pelanggan=nama, kledo_contact_id=601)
    db.add(p)
    await db.flush()
    return p


def _retur(kode: str, *, arah: str, jenis: str, pihak_id: int,
           berat: float) -> InputTimbang:
    return InputTimbang(
        kode=kode, arah=arah, jenis_kode=jenis, berat_kg=berat,
        supplier_id=pihak_id, nomor_polisi="AD 9 ZZ", nama_sopir="Slamet",
        muatan=[InputMuatan(
            jenis_kode=jenis, jumlah_karung=0, tara_per_karung_kg=0,
            berat_acuan_kg=3_000, nomor_acuan="SJ-RETUR-1",
        )],
        perangkat_kode="P1",
    )


async def test_retur_dari_pelanggan_tersimpan_ke_kolom_pelanggan(db, petugas):
    """Barangnya datang, tetapi yang mengembalikan bukan supplier.

    `simpan_timbang_pertama` menaruh id lawan transaksi menurut ARAH, jadi
    inilah pagar yang memastikan retur tidak jatuh ke kolom yang salah dan
    hilang dari rekap per pelanggan.
    """
    p = await _pelanggan(db)
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=_retur("RTP-20260904-P1-001", arah=logic.RETUR_MASUK,
                    jenis="RETUR_PELANGGAN", pihak_id=p.id, berat=9_000),
    )
    assert trx.pelanggan_id == p.id
    assert trx.supplier_id is None
    assert await service.nama_pihak(db, trx) == "Toko Beras Handoko"


async def test_retur_ke_supplier_tersimpan_ke_kolom_supplier(db, petugas,
                                                             supplier):
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=_retur("RTS-20260904-P1-001", arah=logic.RETUR_KELUAR,
                    jenis="RETUR_SUPPLIER", pihak_id=supplier.id, berat=6_000),
    )
    assert trx.supplier_id == supplier.id
    assert trx.pelanggan_id is None


async def test_retur_dari_pelanggan_datang_bermuatan(db, petugas):
    """Truk retur pelanggan tiba penuh dan pulang kosong — seperti pembelian."""
    p = await _pelanggan(db)
    await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=_retur("RTP-20260904-P1-002", arah=logic.RETUR_MASUK,
                    jenis="RETUR_PELANGGAN", pihak_id=p.id, berat=9_000),
    )
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode="RTP-20260904-P1-002", berat_kg=6_000,
        muatan=[InputMuatan(jenis_kode="RETUR_PELANGGAN", jumlah_karung=60)]
    )
    assert float(trx.berat_bermuatan_kg) == 9_000
    assert float(trx.berat_kosong_kg) == 6_000
    assert float(trx.berat_barang_kg) == 3_000


async def test_retur_ke_supplier_berangkat_bermuatan(db, petugas, supplier):
    """Kebalikannya: truk datang kosong, dimuat, lalu ditimbang lagi.

    Angka yang sama persis dengan uji di atas, hanya urutannya terbalik —
    kalau `_bermuatan_dan_kosong` salah memilah, netto akan keluar negatif.
    """
    await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=_retur("RTS-20260904-P1-002", arah=logic.RETUR_KELUAR,
                    jenis="RETUR_SUPPLIER", pihak_id=supplier.id, berat=6_000),
    )
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode="RTS-20260904-P1-002", berat_kg=9_000,
        muatan=[InputMuatan(jenis_kode="RETUR_SUPPLIER", jumlah_karung=60)]
    )
    assert float(trx.berat_bermuatan_kg) == 9_000
    assert float(trx.berat_kosong_kg) == 6_000
    assert float(trx.berat_barang_kg) == 3_000


async def test_retur_wajib_menyebut_nomor_polisi(db, petugas, supplier):
    """Retur justru peristiwa yang paling mungkin berujung sengketa."""
    data = _retur("RTS-20260904-P1-003", arah=logic.RETUR_KELUAR,
                  jenis="RETUR_SUPPLIER", pihak_id=supplier.id, berat=6_000)
    data.nomor_polisi = "   "
    with pytest.raises(service.LayananError, match="Nomor polisi"):
        await service.simpan_timbang_pertama(db, akun=petugas, data=data)


# ─────────────────── Awalan nomor tiket ───────────────────


@pytest.mark.parametrize("arah,awalan", [
    (logic.MASUK, "MSK"),
    (logic.KELUAR, "KLR"),
    (logic.BEBAS, "BBS"),
    (logic.TRANSFER, "TRF"),
    (logic.RETUR_MASUK, "RTP"),
    (logic.RETUR_KELUAR, "RTS"),
])
async def test_awalan_nomor_mengikuti_arah_barang(db, petugas, arah, awalan):
    """Selembar bukti di tangan harus memberitahu peristiwanya sendiri, tanpa
    perlu membuka sistem."""
    kode = await service.kode_baru(db, petugas, arah)
    assert kode.startswith(f"{awalan}-")
    assert kode.endswith("-P1-001")


async def test_setiap_awalan_punya_urutannya_sendiri(db, petugas, supplier):
    """MSK-…-001 dan KLR-…-001 boleh ada pada hari yang sama.

    Menomori berurut lintas arah justru membuat urutan barang masuk terlihat
    bolong-bolong — seolah ada tiket yang hilang.
    """
    masuk = await service.kode_baru(db, petugas, logic.MASUK)
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=masuk_gabah(masuk, supplier.id, 13_600)
    )
    assert await service.kode_baru(db, petugas, logic.MASUK) != masuk
    assert (await service.kode_baru(db, petugas, logic.KELUAR)).endswith("-001")


async def test_arah_tak_dikenal_tetap_memberi_nomor(db, petugas):
    """Lebih baik memakai awalan lama daripada melahirkan tiket tanpa awalan."""
    assert (await service.kode_baru(db, petugas, "ENTAH")).startswith("TRX-")

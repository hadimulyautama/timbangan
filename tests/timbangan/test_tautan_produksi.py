"""Timbangan tahu ketika tiketnya sudah dipakai produksi.

Temuan QA X-08 / T-12, 11 September 2026.

Produksi menaut batch pembeliannya ke tiket timbang lewat
`purchase_batches.timbangan_transaksi_id` (dan pasangannya di
`pk_purchase_batches`). Timbangan tidak pernah melihat tautan itu. Akibatnya
semua tindakan besar berjalan seolah tiketnya masih miliknya sendiri:

  · membatalkan tiket yang gabahnya sudah masuk stok produksi;
  · menutup paksa tiket yang batch-nya sudah dibuat;
  · mengganti komoditas tiket gabah menjadi PK sementara batch gabahnya ada;
  · mengoreksi pemasok sehingga berbeda dengan pemasok di batch;
  · menghapus permanen — yang ini bahkan tidak sampai berubah apa-apa: FK
    produksi menolaknya, dan yang dilihat Admin adalah halaman galat 500.

Yang benar bukan "tolak diam-diam", melainkan menyebut KODE BATCH-nya, karena
tindakan berikutnya ada di aplikasi sebelah dan orangnya harus tahu apa yang
dicari di sana.

Tabel produksi hanya DIBACA di sini. Timbangan tak pernah menulis padanya.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.timbangan import logic, service
from app.timbangan.service import InputMuatan, InputTimbang

pytestmark = pytest.mark.usefixtures("jenis_tersemai")


def _masuk(kode: str, supplier_id: int | None) -> InputTimbang:
    return InputTimbang(
        kode=kode, arah=logic.MASUK, jenis_kode="GABAH_BASAH", berat_kg=13_600,
        supplier_id=supplier_id, nomor_polisi="AD 1234 XY", nama_sopir="Slamet",
        perangkat_kode="P1",
        muatan=[InputMuatan(jenis_kode="GABAH_BASAH", jumlah_karung=120,
                            tara_per_karung_kg=0.25, berat_acuan_kg=10_048,
                            nomor_acuan="NOTA-01")],
    )


async def _taut(db, trx, kode_batch="GB-20260911-02", tabel="purchase_batches"):
    """Produksi membuat batch dan menautkannya — ditulis langsung, karena
    tabel itu milik repo sebelah dan timbangan memang tak punya modelnya."""
    await db.execute(text(
        f"INSERT INTO {tabel} (id, timbangan_transaksi_id, kode_batch) "
        "VALUES (:i, :t, :k)"), {"i": 1, "t": trx.id, "k": kode_batch})
    await db.commit()


@pytest.fixture
def tindakan():
    """Semua pintu yang harus tahu soal tautan, dengan nama yang terbaca."""
    return None


async def test_void_ditolak_bila_sudah_ditaut_produksi(db, petugas, admin, supplier):
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-A-001", supplier.id))
    await _taut(db, trx)
    with pytest.raises(service.LayananError) as e:
        await service.void_transaksi(db, akun=admin, trx=trx, alasan="salah input")
    # Pesannya menyebut kode batchnya — tindak lanjutnya ada di aplikasi lain.
    assert "GB-20260911-02" in str(e.value)


async def test_tutup_paksa_ditolak_bila_sudah_ditaut_produksi(db, petugas, admin,
                                                              supplier):
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-A-002", supplier.id))
    await _taut(db, trx)
    with pytest.raises(service.LayananError) as e:
        await service.tutup_paksa(db, akun=admin, trx=trx, alasan="truk pergi",
                                  tanpa_timbang_keluar=True)
    assert "GB-20260911-02" in str(e.value)


async def test_ubah_jenis_ditolak_bila_sudah_ditaut_produksi(db, petugas, admin,
                                                             supplier):
    """Komoditas yang berubah membuat batch gabah menunjuk tiket PK."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-A-003", supplier.id))
    await _taut(db, trx)
    with pytest.raises(service.LayananError) as e:
        await service.ubah_jenis(db, akun=admin, trx=trx, jenis_kode="BERAS_PK",
                                 alasan="salah pilih")
    assert "GB-20260911-02" in str(e.value)


async def test_koreksi_pemasok_ditolak_bila_sudah_ditaut_produksi(
        db, petugas, admin, supplier):
    """Pemasok yang dikoreksi di sini tak pernah sampai ke batch di sebelah."""
    from app.models import Supplier

    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-A-004", supplier.id))
    lain = Supplier(nama_supplier="H. Lain", kledo_contact_id=502)
    db.add(lain)
    await db.flush()
    await _taut(db, trx)
    with pytest.raises(service.LayananError) as e:
        await service.koreksi_transaksi(
            db, akun=admin, trx=trx, perubahan={"supplier_id": lain.id},
            alasan="salah pilih pemasok")
    assert "GB-20260911-02" in str(e.value)


async def test_koreksi_angka_tetap_boleh_walau_tertaut(db, petugas, admin, supplier):
    """Yang dikunci hanya yang IKUT TERSALIN ke batch produksi. Membetulkan
    nama sopir tak ada urusannya dengan stok — dan pagar yang mengunci semua
    hal akan dicari jalan memutarnya."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-A-005", supplier.id))
    await _taut(db, trx)
    hasil = await service.koreksi_transaksi(
        db, akun=admin, trx=trx, perubahan={"nama_sopir": "Slamet Riyadi"},
        alasan="nama sopir salah ketik")
    assert hasil.nama_sopir == "Slamet Riyadi"


async def test_hapus_permanen_ditolak_dengan_pesan_bukan_galat_500(
        db, petugas, super_admin, supplier):
    """Sebelumnya FK produksi yang menolak, dan Admin melihat halaman galat."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-A-006", supplier.id))
    await _taut(db, trx)
    with pytest.raises(service.LayananError) as e:
        await service.hapus_transaksi(db, akun=super_admin, trx=trx,
                                      alasan="data uji")
    assert "GB-20260911-02" in str(e.value)


async def test_taut_pk_juga_terbaca(db, petugas, admin, supplier):
    """Dua tabel batch, dua kemungkinan tautan — yang diperiksa harus keduanya."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-A-007", supplier.id))
    await _taut(db, trx, kode_batch="PK-20260911-01", tabel="pk_purchase_batches")
    with pytest.raises(service.LayananError) as e:
        await service.void_transaksi(db, akun=admin, trx=trx, alasan="salah")
    assert "PK-20260911-01" in str(e.value)


async def test_tanpa_tautan_semuanya_tetap_berjalan(db, petugas, admin, supplier):
    """Pagar yang menahan pekerjaan normal lebih merugikan daripada celahnya."""
    trx = await service.simpan_timbang_pertama(db, akun=petugas,
                                               data=_masuk("TRX-A-008", supplier.id))
    hasil = await service.void_transaksi(db, akun=admin, trx=trx, alasan="salah input")
    assert hasil.status_transaksi == "VOID"

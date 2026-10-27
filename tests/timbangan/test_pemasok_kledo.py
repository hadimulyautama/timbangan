"""Identitas baru dari Kledo, catatan lama tetap dapat dikerjakan."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import Supplier
from app.timbangan import logic, service
from app.timbangan.models import TimbanganTransaksi

pytestmark = pytest.mark.usefixtures("jenis_tersemai")


def masukan(sid=None, nama=None, cara="DUA_KALI"):
    return service.InputTimbang(
        kunci=str(uuid4()), arah=logic.MASUK, jenis_kode="GABAH_BASAH",
        berat_kg=100 if cara == "PARTAI" else 15000, cara_timbang=cara,
        supplier_id=sid, pihak_nama=nama, nomor_polisi="AD 1234 UJ",
        nama_sopir="Sopir Uji",
        muatan=[service.InputMuatan(jenis_kode="GABAH_BASAH", jumlah_karung=100)],
    )


@pytest.mark.parametrize("cara", ["DUA_KALI", "SEKALI", "PARTAI"])
async def test_nama_bebas_baru_ditolak_tanpa_membuat_tiket(db, petugas, cara):
    with pytest.raises(service.LayananError, match="wajib dipilih dari daftar Kledo"):
        await service.simpan_timbang_pertama(
            db, akun=petugas, data=masukan(nama="Pemasok Belum Terdaftar", cara=cara))
    assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi)) == 0
    assert await db.scalar(select(func.count()).select_from(Supplier)) == 0


@pytest.mark.parametrize("masalah", ["lokal", "nonaktif", "dihapus", "id_palsu"])
async def test_id_saja_tidak_cukup_untuk_melewati_server(db, petugas, masalah):
    s = Supplier(nama_supplier="Pemasok Uji", kledo_contact_id=501)
    if masalah == "lokal":
        s.kledo_contact_id = None
    elif masalah == "nonaktif":
        s.status = "nonaktif"
    elif masalah == "dihapus":
        s.deleted_at = datetime.now(timezone.utc)
    db.add(s)
    await db.flush()
    with pytest.raises(service.LayananError, match="daftar Kledo yang aktif"):
        await service.simpan_timbang_pertama(
            db, akun=petugas, data=masukan(sid=9999 if masalah == "id_palsu" else s.id))
    assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi)) == 0


async def test_pemasok_tertaut_diterima_dan_nama_tambahan_ditolak(db, petugas, supplier):
    with pytest.raises(service.LayananError, match="tanpa nama bebas"):
        await service.simpan_timbang_pertama(
            db, akun=petugas, data=masukan(supplier.id, "Nama lain"))
    t = await service.simpan_timbang_pertama(db, akun=petugas, data=masukan(supplier.id))
    assert t.supplier_id == supplier.id and t.pihak_nama is None


async def test_pilihan_hanya_kledo_tetapi_master_lama_tidak_dihapus(db, supplier):
    lokal = Supplier(nama_supplier="Pemasok Lama")
    db.add(lokal)
    await db.commit()
    pilihan = await service.daftar_pihak(db, logic.MASUK)
    assert [s.id for s in pilihan] == [supplier.id]
    assert (await db.get(Supplier, lokal.id)).nama_supplier == "Pemasok Lama"


async def tiket_lama(db, petugas, supplier):
    # Tiket ini sah saat dibuat. Hilangnya tautan master setelahnya tidak
    # boleh menghentikan timbang kedua atau koreksi bobotnya.
    data = masukan(supplier.id)
    t = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    supplier.kledo_contact_id = None
    await db.commit()
    return t, data


async def test_kiriman_ulang_dan_timbang_kedua_tiket_lama_tetap_aman(db, petugas, supplier):
    t, data = await tiket_lama(db, petugas, supplier)
    ulang = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert ulang.id == t.id
    hasil = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=t.kode, berat_kg=5000)
    assert hasil.supplier_id == supplier.id
    assert float(hasil.berat_barang_kg) == 10000
    assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi)) == 1


async def test_koreksi_tiket_lama_tidak_memaksa_ganti_pemasok(db, admin, supplier):
    t, _ = await tiket_lama(db, admin, supplier)
    hasil = await service.koreksi_transaksi(
        db, akun=admin, trx=t, perubahan={"nama_sopir": "Sopir Dibetulkan"})
    assert hasil.supplier_id == supplier.id
    assert hasil.nama_sopir == "Sopir Dibetulkan"


async def test_koreksi_tidak_bisa_mengganti_ke_pemasok_lokal(db, admin, supplier):
    t = await service.simpan_timbang_pertama(db, akun=admin, data=masukan(supplier.id))
    lokal = Supplier(nama_supplier="Pemasok Lokal")
    db.add(lokal)
    await db.commit()
    with pytest.raises(service.LayananError, match="daftar Kledo yang aktif"):
        await service.koreksi_transaksi(
            db, akun=admin, trx=t, perubahan={"supplier_id": lokal.id})
    assert t.supplier_id == supplier.id


async def test_nama_bebas_historis_tetap_bisa_dikirim_ulang(db, petugas, supplier):
    data = masukan(supplier.id)
    t = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    t.supplier_id = None
    t.pihak_nama = "Nama Saat Dicatat Dulu"
    await db.commit()
    data.supplier_id = None
    data.pihak_nama = t.pihak_nama
    ulang = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert ulang.id == t.id and ulang.pihak_nama == "Nama Saat Dicatat Dulu"
    hasil = await service.simpan_timbang_kedua(db, akun=petugas, kode=t.kode, berat_kg=5000)
    assert hasil.pihak_nama == "Nama Saat Dicatat Dulu" and hasil.supplier_id is None

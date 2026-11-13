"""Pembanding bobot, identitas historis dan pembacaan tanpa mutasi.

Memakai aplikasi serta SQLite sementara dari fixture pos timbang. Tidak ada
koneksi produksi dan tidak mengaktifkan dukungan multi-perusahaan.
"""
from decimal import Decimal
from sqlalchemy import select
import pytest
from app import database
from app.timbangan import klien_produksi
from app.timbangan.models import (TimbanganTransaksi, TimbanganPenimbangan,
    TimbanganMuatan, TimbanganAudit, TimbanganCetak)
from hmu_core import Warehouse, Silo
from test_web import app_uji, klien, login
from test_rincian_transfer import master, tiket

pytestmark = pytest.mark.fondasi_multi


async def transaksi(db):
    result = {}
    for model in (TimbanganTransaksi, TimbanganPenimbangan, TimbanganMuatan,
                  TimbanganAudit, TimbanganCetak):
        rows = (await db.execute(select(model.__table__).order_by(model.id))).mappings().all()
        result[model.__tablename__] = [dict(row) for row in rows]
    return result


async def test_bobot_dan_snapshot_tetap_saat_nama_gudang_diganti(klien,monkeypatch):
    await master()
    ident = await tiket()
    await login(klien,'miftah')
    async with database.SessionLocal() as db:
        row = await db.get(TimbanganTransaksi,ident)
        assert Decimal(str(row.netto_timbangan_kg)) == Decimal('4000')
        assert Decimal(str(row.total_tara_kg)) == Decimal('10.58')
        assert Decimal(str(row.berat_barang_kg)) == Decimal('3989.42')
        assert row.status_kontrol == 'TANPA_KONTROL'
        before = await transaksi(db)
        (await db.get(Warehouse,101)).nama_gudang = 'Sentra Barat'
        (await db.get(Warehouse,102)).nama_gudang = 'Sentra Timur'
        (await db.get(Silo,103)).nama_silo = 'Nama silo baru'
        await db.commit()
        assert await transaksi(db) == before

    async def dilarang(*args,**kwargs):
        raise AssertionError('Pembacaan tiket historis tidak memanggil integrasi')
    monkeypatch.setattr(klien_produksi,'_minta',dilarang)
    for tab in ('ringkasan','perhitungan','jejak'):
        response = await klien.get(f'/timbangan/transaksi/{ident}?tab={tab}')
        assert response.status_code == 200
        assert 'Gudang 1 uji' in response.text and 'Silo A uji' in response.text
        assert 'Sentra Barat' not in response.text and 'Nama silo baru' not in response.text
    async with database.SessionLocal() as db:
        assert await transaksi(db) == before

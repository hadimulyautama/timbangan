"""Migrasi cuplikan tidak mengarang data lama dan tidak membuang bukti."""
import importlib.util
from pathlib import Path
import pytest
from sqlalchemy import text,insert
from datetime import date
from app.timbangan.models import TimbanganTransaksi
from alembic.migration import MigrationContext
from alembic.operations import Operations

async def test_migrasi_snapshot_nullable_dan_downgrade_terlindungi(mesin):
    f=Path(__file__).resolve().parents[2]/'migrations/versions/0047_pengiriman_snapshot.py'
    spec=importlib.util.spec_from_file_location(f.stem,f);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    def operasi(c,fn):
        with Operations.context(MigrationContext.configure(c)):fn()
    async with mesin.kw['bind'].begin() as c:
        await c.execute(insert(TimbanganTransaksi.__table__).values(kode='UJI-LAMA',tanggal=date.today(),arah='KELUAR',jenis_kode='PENGIRIMAN',timbang1_kg=5000))
        assert await c.scalar(text("SELECT pengiriman_snapshot FROM timbangan_transaksi WHERE kode='UJI-LAMA'")) is None
        await c.run_sync(lambda conn:operasi(conn,m.downgrade))
        await c.run_sync(lambda conn:operasi(conn,m.upgrade))
        assert await c.scalar(text("SELECT pengiriman_snapshot FROM timbangan_transaksi WHERE kode='UJI-LAMA'")) is None
        assert await c.scalar(text("SELECT count(*) FROM timbangan_transaksi WHERE kode='UJI-LAMA'"))==1
        await c.execute(text("UPDATE timbangan_transaksi SET pengiriman_snapshot='{}'::json WHERE kode='UJI-LAMA'"))
        with pytest.raises(RuntimeError,match='Cuplikan kiriman'):
            await c.run_sync(lambda conn:operasi(conn,m.downgrade))
        assert await c.scalar(text("SELECT pengiriman_snapshot::text FROM timbangan_transaksi WHERE kode='UJI-LAMA'"))=='{}'

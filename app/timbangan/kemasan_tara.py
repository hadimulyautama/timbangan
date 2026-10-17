"""Master tara bersama: disemai Produksi, diubah Admin di Pos Timbang.

Tabel dimigrasi Produksi. Timbangan mengubah nilai di tabel yang sama,
sehingga tak ada penyalinan master atau dua angka yang bisa berselisih.
Tiket timbang menyimpan snapshot; revisi master hanya untuk rincian baru.
"""
from decimal import Decimal, InvalidOperation

from sqlalchemy import text, table, column, Numeric, Integer, DateTime, select, update, func
from sqlalchemy.exc import DBAPIError

from app.timbangan import service

_TABEL = table('kemasan_tara', column('id', Integer),
               column('tara_per_karung_kg', Numeric(10, 4)),
               column('updated_at', DateTime(timezone=True)))

_SQL = '''SELECT t.id, m.nama AS jenis, s.ukuran_kg, t.tara_per_karung_kg
    FROM kemasan_tara t JOIN packaging_materials m ON m.id=t.packaging_material_id
    JOIN package_sizes s ON s.id=t.package_size_id
    WHERE m.aktif=true AND s.aktif=true ORDER BY m.nama, s.ukuran_kg'''


async def daftar(db):
    # Instalasi mandiri boleh belum memiliki migrasi master Produksi. Savepoint
    # mencegah satu tabel yang belum ada membatalkan kueri Pengaturan lainnya.
    try:
        async with db.begin_nested():
            return (await db.execute(text(_SQL))).mappings().all()
    except DBAPIError:
        return None


async def simpan(db, *, akun, tara_id, teks, ip=None):
    try:
        nilai = Decimal(teks.strip().replace(',', '.'))
        if not nilai.is_finite() or not 0 <= nilai <= 1000:
            raise ValueError
        if nilai != nilai.quantize(Decimal('.0001')):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise service.LayananError('Tara harus angka 0–1.000 kg, maksimal empat angka desimal.')
    lama = await db.scalar(select(_TABEL.c.tara_per_karung_kg).where(
        _TABEL.c.id == tara_id).with_for_update())
    if lama is None:
        raise service.LayananError('Jenis dan ukuran kemasan tidak ditemukan.')
    await db.execute(update(_TABEL).where(_TABEL.c.id == tara_id).values(
        tara_per_karung_kg=nilai, updated_at=func.now()))
    await service.catat_audit(db, akun=akun, aksi='UBAH_TARA_KEMASAN',
                             entitas='kemasan_tara', entitas_id=str(tara_id),
                             ringkasan=f'Tara kemasan {lama} → {nilai} kg',
                             sebelum={'tara_per_karung_kg': str(lama)},
                             sesudah={'tara_per_karung_kg': str(nilai)}, ip=ip)
    await db.commit()
    return nilai

"""Proyeksi baca tiket transfer: tidak mencari relasi atau menulis PadiFlow."""
from decimal import Decimal
from sqlalchemy import select
from app.timbangan.models import TimbanganAkun
from app.timbangan.lintasan_transfer import teks


async def baca(db, trx, pemeriksaan, cetak):
    ids = {trx.timbang1_petugas_id, trx.timbang2_petugas_id}
    ids.update(c.oleh_id for c in cetak)
    if pemeriksaan:
        ids.update([pemeriksaan.dibuka_oleh_id, pemeriksaan.ditutup_oleh_id])
    orang = dict((await db.execute(select(TimbanganAkun.id,TimbanganAkun.nama)
        .where(TimbanganAkun.id.in_([i for i in ids if i])))).all())
    kemasan = (Decimal(str(trx.total_tara_kg)) - Decimal(str(trx.tara_lain_kg or 0))
               if trx.status_tiket == 'SELESAI' and trx.total_tara_kg is not None else None)
    return dict(lintasan=teks(trx.lintasan_transfer) or trx.pihak_nama or 'Belum tercatat',
                terstruktur=bool(trx.lintasan_transfer),kemasan=kemasan,orang=orang,
                karung=trx.jumlah_karung if trx.status_tiket == 'SELESAI' else sum(m.jumlah_karung or 0 for m in trx.muatan))

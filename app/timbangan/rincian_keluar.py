"""Proyeksi baca detail keluar. Tidak menghitung ulang hasil atau menulis Produksi."""
from decimal import Decimal
import logging
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from app.timbangan import pengiriman, klien_produksi, service
from app.timbangan.models import TimbanganAkun

log = logging.getLogger(__name__)

async def status_produksi(db, tid):
    """Status tersimpan seluruh anggota aktif, termasuk kompatibilitas sebelum kiriman."""
    tidak_pasti = dict(kode='tidak_pasti', label='Status PadiFlow belum dapat dipastikan', perintah=[])
    try:
        # Savepoint menjaga pembacaan tiket bila skema/integrasi belum tersedia.
        async with db.begin_nested():
            tabel = await db.run_sync(lambda s: set(inspect(s.connection()).get_table_names()))
            if 'outgoing_records' not in tabel:
                return tidak_pasti
            if 'kiriman_keluar' in tabel:
                rows = (await db.execute(text('''
                    SELECT o.id, o.kode, o.status, o.kiriman_id FROM outgoing_records o
                    LEFT JOIN kiriman_keluar k ON k.id=o.kiriman_id
                    WHERE COALESCE(k.timbangan_transaksi_id,o.timbangan_transaksi_id)=:tid
                    ORDER BY o.id
                '''), {'tid': tid})).mappings().all()
            else:
                rows = (await db.execute(text('''
                    SELECT id, kode, status, NULL AS kiriman_id FROM outgoing_records
                    WHERE timbangan_transaksi_id=:tid ORDER BY id
                '''), {'tid': tid})).mappings().all()
            aktif = [dict(r) for r in rows if r['status'] != 'batal']
            if not aktif:
                return dict(kode='belum', label='Belum ada pengiriman aktif tertaut', perintah=[])
            perjalanan = {r['kiriman_id'] or ('lama', r['id']) for r in aktif}
            if len(perjalanan) != 1:
                return tidak_pasti
            selesai = all(r['status'] == 'selesai' for r in aktif)
            return dict(kode='terverifikasi' if selesai else 'menunggu',
                        label='Terverifikasi di PadiFlow' if selesai else 'Verifikasi PadiFlow belum selesai',
                        perintah=aktif)
    except SQLAlchemyError:
        # Jangan merekam nilai muatan/identitas atau pesan exception dari layanan.
        log.warning('Status PadiFlow tidak tersedia untuk detail timbang')
        return tidak_pasti

async def baca(db, trx, pemeriksaan, cetak):
    data = trx.pengiriman_snapshot
    sumber = 'snapshot' if data else 'historis'
    pesan = None
    if not data and trx.status_tiket == 'TERBUKA' and trx.status_transaksi != 'VOID':
        try:
            data = await pengiriman.baca(db, trx.id)
            sumber = 'langsung'
        except (pengiriman.MuatanTidakSah, klien_produksi.ProduksiTakTersedia, service.LayananError):
            pesan = 'Muatan PadiFlow belum dapat diperiksa. Bacaan yang sudah tersimpan tetap tersedia; lanjutkan melalui timbang kedua untuk menyimpan sementara.'
    ids = {trx.timbang1_petugas_id, trx.timbang2_petugas_id}
    ids.update(c.oleh_id for c in cetak)
    if pemeriksaan:
        ids.update([pemeriksaan.dibuka_oleh_id, pemeriksaan.ditutup_oleh_id])
    orang = dict((await db.execute(select(TimbanganAkun.id, TimbanganAkun.nama).where(TimbanganAkun.id.in_([i for i in ids if i])))).all())
    # Pemisahan tampilan dari total resmi tersimpan, sama dengan bukti timbang.
    tara_karung = (Decimal(str(trx.total_tara_kg)) - Decimal(str(trx.tara_lain_kg or 0))) if trx.total_tara_kg is not None else None
    kelompok = pengiriman.kelompok(data) if data else []
    # Nol historis tanpa kontrol berarti dokumen belum tersedia; nol hasil
    # timbang tetap ditampilkan sebagai nol, bukan dianggap kosong.
    acuan = trx.berat_acuan_kg
    if trx.status_kontrol == 'TANPA_KONTROL' and not acuan:
        acuan = None
    return dict(data=data, sumber=sumber, pesan=pesan, kelompok=kelompok, acuan=acuan,
                total_acuan=sum((p['subtotal'] for p in kelompok), Decimal(0)) if data else None,
                tara_karung=tara_karung, orang=orang,
                produksi=await status_produksi(db, trx.id))

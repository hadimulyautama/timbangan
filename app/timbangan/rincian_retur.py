"""Proyeksi detail retur, terpisah dari penyelesaian timbang dan stok."""
from sqlalchemy import select
from app.timbangan import klien_produksi
from app.timbangan.models import TimbanganAkun

LABEL = {
    'belum': 'Belum ada pengajuan terhubung',
    'menunggu_timbang': 'Menunggu timbang kedua',
    'perlu_koreksi': 'Perlu koreksi di PadiFlow',
    'tertahan': 'Penerimaan PadiFlow tertahan',
    'calon_manual': 'Menunggu verifikasi manual setelah koreksi',
    'sesuai': 'Pencocokan sesuai · belum diterima',
    'diterima_otomatis': 'Diterima otomatis',
    'diterima_manual': 'Diterima manual',
    'diterima': 'Penerimaan tercatat · metode historis tidak tersedia',
    'dibatalkan': 'Pengajuan retur dibatalkan',
    'berubah': 'Tiket berubah · menunggu pemeriksaan ulang di PadiFlow',
    'tiket_tidak_aktif': 'Tiket tidak aktif untuk penerimaan · periksa di PadiFlow',
    'tidak_pasti': 'Status penerimaan belum dapat dipastikan',
    'dibatasi': 'Rincian PadiFlow dibatasi oleh izin akun',
}


async def baca(db, trx, akun, pemeriksaan, cetak, *, lihat=None):
    ids = {trx.timbang1_petugas_id, trx.timbang2_petugas_id}
    ids.update(c.oleh_id for c in cetak)
    if pemeriksaan:
        ids.update([pemeriksaan.dibuka_oleh_id, pemeriksaan.ditutup_oleh_id])
    orang = dict((await db.execute(select(TimbanganAkun.id, TimbanganAkun.nama)
        .where(TimbanganAkun.id.in_([i for i in ids if i])))).all())
    data, pesan, status = None, None, 'dibatasi'
    if akun.akun_id:
        try:
            data = await klien_produksi.detail_retur(trx.id, akun.akun_id, lihat=lihat)
            if (not isinstance(data, dict) or data.get('tiket_id') != trx.id
                    or data.get('kode_tiket') != trx.kode or data.get('pelanggan_id') != trx.pelanggan_id):
                raise ValueError('Hubungan rincian berbeda dari tiket.')
            status = data.get('status', 'tidak_pasti')
            if status not in LABEL:
                status = 'tidak_pasti'
        except klien_produksi.ProduksiDilarang:
            data, status = None, 'dibatasi'
        except (klien_produksi.ProduksiTakTersedia, ValueError, TypeError):
            data, status = None, 'tidak_pasti'
    if status == 'dibatasi':
        pesan = 'Rincian retur memerlukan akun tertaut yang berhak di PadiFlow. Hasil timbang tetap dapat dibaca sesuai izin TeraFlow.'
    elif status == 'tidak_pasti':
        pesan = 'Rincian atau status PadiFlow belum dapat diperiksa. Hasil timbang yang tersimpan tetap tersedia; penerimaan stok belum dapat dipastikan.'
    acuan = trx.berat_acuan_kg
    if trx.status_kontrol == 'TANPA_KONTROL' and not acuan:
        acuan = None
    return dict(data=data, status=status, label=LABEL[status], pesan=pesan, orang=orang, acuan=acuan)

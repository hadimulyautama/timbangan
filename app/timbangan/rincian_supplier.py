"""Referensi retur supplier dari pembaca PadiFlow yang memeriksa akun tertaut.

Tidak menebak relasi dari catatan ataupun PkRejection. Angka pengajuan tetap
angka sumber PadiFlow; tidak dipakai menghitung ulang hasil tiket TeraFlow.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime
from app.timbangan import klien_produksi

LABEL = {
    'belum_terhubung': 'Belum ada pengajuan retur terhubung',
    'diajukan': 'Pengajuan retur tercatat di PadiFlow',
    'dibatalkan': 'Pengajuan retur dibatalkan di PadiFlow',
    'selesai_gudang': 'Selesai di gudang · PadiFlow',
    'dibatasi': 'Rincian PadiFlow dibatasi oleh izin akun',
    'tidak_pasti': 'Status pengajuan belum dapat dipastikan',
}


def _id(nilai):
    if type(nilai) is not int or nilai <= 0:
        raise ValueError('Identitas sumber tidak sah.')
    return nilai


def _angka(nilai):
    n = Decimal(str(nilai))
    if not n.is_finite() or n <= 0:
        raise ValueError('Bobot/jumlah sumber tidak sah.')
    return n


def _teks(data, nama, *, wajib=False):
    nilai = data.get(nama)
    if nilai is None and not wajib:
        return None
    if not isinstance(nilai, str) or (wajib and not nilai.strip()):
        raise ValueError('Keterangan sumber tidak lengkap.')
    return nilai


def periksa(data, trx):
    if (not isinstance(data, dict) or type(data.get('tiket_id')) is not int
            or data['tiket_id'] != trx.id or data.get('kode_tiket') != trx.kode
            or data.get('arah') != trx.arah or data.get('supplier_id') != trx.supplier_id
            or (data.get('supplier_id') is not None and type(data['supplier_id']) is not int)
            or data.get('status') not in ('belum_terhubung', 'diajukan', 'dibatalkan', 'selesai_gudang')):
        raise ValueError('Hubungan pengajuan berbeda dari tiket.')
    status = data['status']
    p = data.get('pengajuan')
    if status == 'belum_terhubung':
        if p is not None:
            raise ValueError('Status dan pengajuan tidak konsisten.')
        return status, None
    if not isinstance(p, dict) or _id(p.get('supplier_id')) != trx.supplier_id:
        raise ValueError('Supplier pengajuan berbeda.')
    if _id(p.get('penerimaan_tiket_id')) == trx.id:
        raise ValueError('Tiket asal tidak boleh tiket retur itu sendiri.')
    if not isinstance(p.get('items'), list) or not p['items']:
        raise ValueError('Rincian sumber belum tersedia.')
    # Hanya kolom operasional yang diperbolehkan diteruskan ke template.
    # Kunci tambahan dari layanan (misalnya data finansial) tidak ikut dibawa.
    hasil = {k: _teks(p, k, wajib=k in ('kode', 'supplier', 'penerimaan', 'alasan'))
             for k in ('kode', 'supplier', 'penerimaan', 'nota', 'alasan', 'catatan')}
    hasil.update(id=_id(p.get('id')), penerimaan_tiket_id=p['penerimaan_tiket_id'],
                 total_kg=_angka(p.get('total_kg')), items=[])
    kunci = set()
    for item in p['items']:
        if not isinstance(item, dict):
            raise ValueError('Item sumber tidak sah.')
        baris = {k: _teks(item, k, wajib=k in ('kunci_sumber', 'kode', 'nama', 'satuan'))
                 for k in ('kunci_sumber', 'kode', 'nama', 'gudang', 'pemilik', 'satuan')}
        if baris['kunci_sumber'] in kunci or baris['satuan'] not in ('karung', 'kg'):
            raise ValueError('Item sumber berulang atau satuan tidak sah.')
        kunci.add(baris['kunci_sumber'])
        baris.update(jumlah=_angka(item.get('jumlah')), bobot_kg=_angka(item.get('bobot_kg')))
        hasil['items'].append(baris)
    selesai = data.get('penyelesaian')
    if selesai is not None:
        if status != 'selesai_gudang' or not isinstance(selesai, dict):
            raise ValueError('Keterangan penyelesaian tidak konsisten.')
        hasil['penyelesaian'] = dict(
            kode=_teks(selesai, 'kode', wajib=True),
            waktu=datetime.fromisoformat(_teks(selesai, 'waktu', wajib=True)),
            total_kg=_angka(selesai.get('total_kg')),
            metode_verifikasi=_teks(selesai, 'metode_verifikasi', wajib=True))
    return status, hasil


async def baca(trx, akun, *, lihat=None):
    status, pengajuan = 'dibatasi', None
    if akun.akun_id:
        try:
            data = await klien_produksi.detail_retur_supplier(trx.id, akun.akun_id, lihat=lihat)
            status, pengajuan = periksa(data, trx)
        except klien_produksi.ProduksiDilarang:
            status = 'dibatasi'
        except (klien_produksi.ProduksiTakTersedia, ValueError, TypeError, InvalidOperation):
            status = 'tidak_pasti'
    pesan = ('Rincian memerlukan akun tertaut dengan izin dan cakupan gudang PadiFlow yang sesuai.'
             if status == 'dibatasi' else
             'PadiFlow belum dapat diperiksa. Hasil timbang tersimpan tetap tersedia; status pengajuan tidak ditebak.'
             if status == 'tidak_pasti' else None)
    return dict(status=status, label=LABEL[status], pengajuan=pengajuan, pesan=pesan)

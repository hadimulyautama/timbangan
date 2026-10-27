"""Kontrak muatan PadiFlow, tanpa stok dan tanpa rumus timbang tandingan.

Identitas sumber disimpan terstruktur dalam satu cuplikan per perjalanan.
Nama dan bobot pelanggan adalah catatan muat, bukan hasil jembatan terpisah.
Cuplikan hanya ditulis ketika timbang diselesaikan, bersama transaksi/audit.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from sqlalchemy import inspect, text


class MuatanTidakSah(ValueError):
    pass


def _angka(v, nama, *, bulat=False):
    try:
        n = Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        raise MuatanTidakSah(f"{nama} muatan PadiFlow belum tersedia atau tidak sah.") from None
    if not n.is_finite() or n < 0 or (bulat and n != n.to_integral_value()):
        raise MuatanTidakSah(f"{nama} muatan PadiFlow tidak sah.")
    return int(n) if bulat else format(n.normalize(), 'f')


def cuplikan(data):
    """Allowlist menjaga payload layanan tidak membawa harga/HPP ke Timbangan.

    Respons API lama satu pelanggan tetap dapat dibaca. Kiriman bersama
    wajib memiliki seluruh ID serta sidik sumber; tidak menebak pemiliknya.
    """
    if not isinstance(data, dict) or not isinstance(data.get('muatan'), list) or not data['muatan']:
        raise MuatanTidakSah('PadiFlow belum memiliki muatan aktual yang dapat diperiksa.')
    if any(not isinstance(b, dict) for b in data['muatan']) or not isinstance(data.get('penerima', []), list) or any(not isinstance(p,dict) for p in data.get('penerima', [])):
        raise MuatanTidakSah('Struktur pelanggan atau muatan PadiFlow tidak sah.')
    hasil = {k:deepcopy(data.get(k)) for k in
             ('kiriman_id','kode_perintah','nomor_polisi','pelanggan','sidik_sumber')}
    hasil['versi'] = 1
    hasil['penerima'] = [{k:p.get(k) for k in
                         ('perintah_id','kode_perintah','pelanggan_id','pelanggan')}
                        for p in data.get('penerima', [])]
    hasil['muatan'] = []
    if hasil['kiriman_id'] is not None and (type(hasil['kiriman_id']) is not int or hasil['kiriman_id']<=0):
        raise MuatanTidakSah('Identitas kiriman PadiFlow tidak sah.')
    bersama = bool(hasil['kiriman_id'])
    ids = set()
    for b in data['muatan']:
        row = {k:b.get(k) for k in ('outgoing_item_id','perintah_id','kode_perintah',
            'pelanggan_id','pelanggan','jenis_kode','nama','kualitas_id','merek_produk_id',
            'packaging_material_id','package_size_id','satuan')}
        row['jenis_kode'] = str(row['jenis_kode'] or '').strip().upper()
        if not row['jenis_kode']:
            raise MuatanTidakSah('Komoditas muatan PadiFlow belum tersedia.')
        for k in ('berat_kg','tara_per_karung_kg'):
            row[k] = _angka(b.get(k), k)
        row['jumlah_karung'] = _angka(b.get('jumlah_karung'), 'Jumlah karung', bulat=True)
        row['jumlah'] = _angka(b.get('jumlah', row['jumlah_karung'] if row['satuan']=='karung' else row['berat_kg']), 'Jumlah aktual')
        if bersama:
            if not all(type(row[k]) is int and row[k]>0 for k in ('outgoing_item_id','perintah_id','pelanggan_id')):
                raise MuatanTidakSah('Identitas pelanggan, perintah, atau item kiriman bersama belum lengkap.')
            cocok = [p for p in hasil['penerima'] if p['perintah_id']==row['perintah_id']
                     and p['pelanggan_id']==row['pelanggan_id'] and p['pelanggan']==row['pelanggan']]
            if len(cocok)!=1 or row['outgoing_item_id'] in ids:
                raise MuatanTidakSah('Hubungan pelanggan dan item kiriman bersama tidak konsisten.')
        if row['outgoing_item_id'] is not None:ids.add(row['outgoing_item_id'])
        hasil['muatan'].append(row)
    if bersama and ({r['perintah_id'] for r in hasil['muatan']} != {p['perintah_id'] for p in hasil['penerima']}):
        raise MuatanTidakSah('Seluruh pelanggan kiriman harus mempunyai muatan aktual yang dapat diperiksa.')
    if bersama and (not hasil['sidik_sumber'] or not hasil['penerima']):
        raise MuatanTidakSah('Sidik sumber kiriman bersama belum tersedia. Perbarui PadiFlow.')
    if sum(Decimal(r['berat_kg']) for r in hasil['muatan'])<=0:
        raise MuatanTidakSah('Muatan aktual PadiFlow belum mempunyai berat acuan yang sah.')
    return hasil


async def baca(db, tiket_id):
    from app.timbangan import klien_produksi, service
    data = cuplikan(await klien_produksi.muatan_pengiriman(tiket_id))
    for row in data['muatan']:
        aturan = await service.aturan_untuk(db, row['jenis_kode'])
        if aturan.arah not in ('MASUK','KELUAR','BEBAS'):
            raise MuatanTidakSah('Aturan muatan PadiFlow belum tersedia.')
    return data


def input_muatan(data):
    from app.timbangan.service import InputMuatan
    return [InputMuatan(jenis_kode=b['jenis_kode'],jumlah_karung=b['jumlah_karung'],
        tara_per_karung_kg=float(b['tara_per_karung_kg']),berat_acuan_kg=float(b['berat_kg']),
        catatan=b.get('nama'),nomor_acuan=b.get('kode_perintah'),
        **{k:b.get(k) for k in ('kualitas_id','merek_produk_id','packaging_material_id','package_size_id')})
        for b in data['muatan']]


def kelompok(data):
    if not data:return []
    hasil = {}
    for b in data['muatan']:
        # Baris lama tanpa ID tidak dikarang menjadi pelanggan terdaftar.
        k = (b.get('pelanggan_id'), b.get('pelanggan') or data.get('pelanggan') or 'Penerima pada catatan lama')
        p = hasil.setdefault(k, dict(pelanggan_id=k[0],pelanggan=k[1],baris=[],subtotal=Decimal(0)))
        p['baris'].append(b);p['subtotal']+=Decimal(str(b['berat_kg']))
    return list(hasil.values())


def ringkasan(data):
    if not data:return ''
    return f"Pengiriman · {len(kelompok(data))} pelanggan · {len(data['muatan'])} baris barang"


def rincian_bukti(trx, *, berat=False):
    """Pembanding hanya dicetak bila kebijakan dokumen mengizinkannya."""
    data=getattr(trx,'pengiriman_snapshot',None)
    if not data:return []
    from app.timbangan import format as fmt
    teks=['RINCIAN MUATAN PADIFLOW', 'Bukan hasil timbang per pelanggan']
    for p in kelompok(data):
        teks.append(p['pelanggan'])
        for b in p['baris']:
            teks.append('  '+str(b.get('nama') or b['jenis_kode']))
            if b.get('jumlah_karung'):teks.append(f"  {b['jumlah_karung']} karung")
            if berat:teks.append('  Acuan muat '+fmt.kg(b['berat_kg']))
        if berat:teks.append('Subtotal muat '+fmt.kg(p['subtotal']))
    if berat:teks.append('Total acuan muat '+fmt.kg(sum(p['subtotal'] for p in kelompok(data))))
    return teks


async def ringkasan_hidup(db, baris):
    """Satu query baca saja untuk kartu tiket yang terlihat; sejarah pakai snapshot.

    Tidak menggabung JOIN ini dengan SUM laporan: satu tiket tetap satu hasil
    timbang. Instalasi lama tanpa kiriman_keluar tetap dapat digunakan.
    """
    ids=[b.trx.id for b in baris if b.trx.arah=='KELUAR' and not b.trx.pengiriman_snapshot]
    if not ids:return baris
    ada=await db.run_sync(lambda s:inspect(s.connection()).has_table('kiriman_keluar'))
    if not ada:return baris
    rows=(await db.execute(text('''
        SELECT k.timbangan_transaksi_id AS tid, count(DISTINCT o.pelanggan_id) AS pelanggan,
               count(i.id) AS barang
          FROM kiriman_keluar k JOIN outgoing_records o ON o.kiriman_id=k.id
          LEFT JOIN outgoing_items i ON i.outgoing_record_id=o.id
         WHERE k.timbangan_transaksi_id=ANY(:ids) AND o.status<>'batal'
         GROUP BY k.timbangan_transaksi_id
    ''') if db.get_bind().dialect.name=='postgresql' else text('''
        SELECT k.timbangan_transaksi_id AS tid, count(DISTINCT o.pelanggan_id) AS pelanggan,
               count(i.id) AS barang
          FROM kiriman_keluar k JOIN outgoing_records o ON o.kiriman_id=k.id
          LEFT JOIN outgoing_items i ON i.outgoing_record_id=o.id
         WHERE k.timbangan_transaksi_id IN ('''+','.join(str(int(i)) for i in ids)+''') AND o.status<>'batal'
         GROUP BY k.timbangan_transaksi_id
    '''), {'ids':ids} if db.get_bind().dialect.name=='postgresql' else {})).mappings()
    counts={r['tid']:f"Pengiriman · {r['pelanggan']} pelanggan · {r['barang']} baris barang" for r in rows}
    for b in baris:b.pengiriman_ringkasan=counts.get(b.trx.id)
    return baris


async def id_dari_pencarian(db, cari):
    """Nama semua penerima/perintah dapat dicari sebelum ada cuplikan final."""
    if not cari:return []
    if not await db.run_sync(lambda s:inspect(s.connection()).has_table('kiriman_keluar')):return []
    pola='%'+cari.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    rows=await db.scalars(text('''
        SELECT DISTINCT k.timbangan_transaksi_id FROM kiriman_keluar k
          JOIN outgoing_records o ON o.kiriman_id=k.id
         WHERE o.status<>'batal' AND k.timbangan_transaksi_id IS NOT NULL
           AND (lower(o.nama_pembeli) LIKE lower(:cari) ESCAPE '\\'
                OR lower(o.kode) LIKE lower(:cari) ESCAPE '\\')
    '''),{'cari':pola})
    return list(rows)

"""Rincian Barang Masuk: nilai tersimpan dan pembacaan penerimaan berizin."""
from decimal import Decimal
from datetime import datetime
from sqlalchemy import select
from app.timbangan import klien_produksi, service
from app.timbangan.models import TimbanganAkun

LABEL = {'tercatat':'Catatan penerimaan tersedia', 'belum':'Belum ada catatan penerimaan',
         'dibatasi':'Rincian penerimaan dibatasi oleh izin akun',
         'tidak_pasti':'Status penerimaan belum dapat dipastikan'}


async def baca(db, trx, akun, pemeriksaan, cetak, *, lihat=None):
    ids = {trx.timbang1_petugas_id, trx.timbang2_petugas_id}
    ids.update(c.oleh_id for c in cetak)
    if pemeriksaan:
        ids.update([pemeriksaan.dibuka_oleh_id, pemeriksaan.ditutup_oleh_id])
    orang = dict((await db.execute(select(TimbanganAkun.id, TimbanganAkun.nama)
        .where(TimbanganAkun.id.in_([i for i in ids if i])))).all())
    data, status = None, 'dibatasi'
    if akun.akun_id:
        try:
            data = await klien_produksi.detail_masuk(trx.id, akun.akun_id, lihat=lihat)
            if (not isinstance(data, dict) or data.get('tiket_id') != trx.id
                    or data.get('kode_tiket') != trx.kode
                    or data.get('jenis_kode') != trx.jenis_kode
                    or data.get('jasa') != bool(trx.jasa)
                    or data.get('status') not in ('belum','tercatat')
                    or not isinstance(data.get('catatan'), list)):
                raise ValueError('Hubungan penerimaan berbeda dari tiket.')
            for c in data['catatan']:
                c['waktu'] = datetime.fromisoformat(c['waktu']) if c.get('waktu') else None
                for q in c.get('qc', []):
                    for putaran in q.get('putaran', []):
                        putaran['waktu'] = datetime.fromisoformat(putaran['waktu']) if putaran.get('waktu') else None
            status = data['status']
        except klien_produksi.ProduksiDilarang:
            data, status = None, 'dibatasi'
        except (klien_produksi.ProduksiTakTersedia, ValueError, TypeError):
            data, status = None, 'tidak_pasti'
    pesan = ('Rincian memerlukan akun tertaut dengan izin PadiFlow dan cakupan gudang yang sesuai.' if status=='dibatasi'
             else 'PadiFlow belum dapat dibaca. Hasil timbang tersimpan tetap tersedia; status penerimaan dan QC belum dapat dipastikan.' if status=='tidak_pasti' else None)
    # Tidak membaca sampling/master saat ini. FK sampling adalah bukti sumber;
    # snapshot hanya menjelaskan aturan waktu transaksi, bukan menebak pilihan
    # petugas bila nilainya dapat ditimpa manual.
    aturan = service.aturan_dari_snapshot(trx)
    tara = []
    for m in trx.muatan:
        sumber = f'Sampling tersimpan #{m.tara_standar_id}' if m.tara_standar_id else 'Sumber pemilihan tidak tercatat'
        tara.append(dict(muatan=m, sumber=sumber))
    acuan = trx.berat_acuan_kg
    if trx.status_kontrol == 'TANPA_KONTROL' and not acuan:
        acuan = None
    # Pemisahan komponen dari total tersimpan, bukan menghitung hasil timbang
    # baru. total_tara_kg dari mesin resmi sudah termasuk tara_lain_kg.
    kemasan = (Decimal(str(trx.total_tara_kg)) - Decimal(str(trx.tara_lain_kg or 0))
               if trx.status_tiket == 'SELESAI' and trx.total_tara_kg is not None else None)
    return dict(data=data,status=status,label=LABEL[status],pesan=pesan,orang=orang,
                acuan=acuan,tara=tara,kemasan=kemasan,
                nota=' · '.join(dict.fromkeys(m.nomor_acuan for m in trx.muatan if m.nomor_acuan)),
                aturan_tara=aturan.sumber_tara if aturan else None)

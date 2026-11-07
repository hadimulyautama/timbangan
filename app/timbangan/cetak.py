"""Pratinjau dan pekerjaan cetak, memakai bukti serta audit layanan yang sama.

GET tidak membuat pekerjaan. Konten dibekukan hanya saat tindakan diminta;
ACK/konfirmasi yang terlambat tidak membaca ulang alasan atau revisi layar.
"""
import hashlib,re
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.timbangan import service,logic,pdf,epos
from app.timbangan.config import tsettings
from app.timbangan.models import TimbanganTransaksi,TimbanganCetak,TimbanganAkun,TimbanganPekerjaanCetak as Job

AKTIF=('siap','dikirim','pdf_siap')

async def kunci_tiket(db,tid):
    t=await db.scalar(select(TimbanganTransaksi).where(TimbanganTransaksi.id==tid).with_for_update().execution_options(populate_existing=True))
    if t is None:raise service.LayananError('Transaksi tidak ditemukan.')
    return t

async def bahan(db,tid,akun):
    from hmu_dokumen.perusahaan import baca
    identitas=await baca(db)
    b=await service.ambil_transaksi(db,tid)
    if b is None:raise service.LayananError('Transaksi tidak ditemukan.')
    service.pastikan_boleh_cetak(b.trx)
    aturan=service.aturan_dari_snapshot(b.trx) or await service.aturan_untuk(db,b.trx.jenis_kode)
    umum=dict(trx=b.trx,aturan=aturan,pihak=b.pihak_tampil,petugas=akun.nama,
        muatan=list(b.trx.muatan),perusahaan=identitas.nama,alamat=identitas.alamat.replace("\n", ", "),
        telepon=identitas.kontak+((" | "+identitas.website) if identitas.website else ""),arah_masuk=logic.timbang_pertama_bermuatan(b.trx.arah),
        cetakan_ke=await service.cetakan_ke(db,tid))
    return b,aturan,umum

def dokumen(umum,format,keluaran='pdf'):
    tampil=format=='80MM' and epos.tampilkan_selisih(umum['trx'],umum['aturan'])
    if keluaran=='printer':return epos.struk_timbang(**umum,tampilkan_selisih=tampil).encode()
    if format=='NCR':return pdf.bukti_ncr(**umum)
    return pdf.bukti_thermal(**umum,tampilkan_selisih=tampil)

def sidik(umum,akun):
    # Kedua format dan perintah printer tercakup, termasuk aturan historis,
    # nama pencetak dan nomor cetakan berikutnya. PDF dibuat deterministik.
    h=hashlib.sha256(str(akun.id).encode())
    h.update(service.versi_tiket(umum['trx']).encode())
    for f,k in [('80MM','pdf'),('NCR','pdf'),('80MM','printer')]:h.update(dokumen(umum,f,k))
    return h.hexdigest()

async def riwayat(db,tid):
    rows=(await db.execute(select(TimbanganCetak,TimbanganAkun.nama,Job).outerjoin(TimbanganAkun,TimbanganAkun.id==TimbanganCetak.oleh_id).outerjoin(Job,Job.cetak_id==TimbanganCetak.id).where(TimbanganCetak.transaksi_id==tid).order_by(TimbanganCetak.urutan.desc()))).all()
    return [dict(c=c,nama=j.nama_pencetak if j else nama or 'Tidak tercatat',metode=j.metode if j else 'Pencatatan lama') for c,nama,j in rows]

async def tertunda(db,tid,akun):
    q=select(Job).where(Job.transaksi_id==tid,Job.status.in_(AKTIF))
    if not akun.is_admin:q=q.where(Job.oleh_id==akun.id)
    return await db.scalar(q.order_by(Job.waktu.desc()))

def rangkap(j):
    # Baca konten beku: pekerjaan satu lembar sebelum rilis tetap satu.
    return 2 if j.keluaran == 'printer' and j.konten.count(b'<cut type="feed"/>') == 2 else 1

def ringkas(j,akun=None):
    return dict(rangkap=rangkap(j),kunci=j.kunci,status=j.status,format=j.format,keluaran=j.keluaran,revisi=j.revisi,nama=j.nama_pencetak,alasan=j.alasan or '',
        boleh_menuntaskan=bool(akun and akun.is_admin and j.oleh_id!=akun.id))

async def milik(db,tid,key,akun,*,pengawasan=False):
    # Selalu kunci tiket dahulu: urutan kunci sama dengan prepare/legacy audit.
    await kunci_tiket(db,tid)
    j=await db.scalar(select(Job).where(Job.kunci==key).with_for_update())
    if not j or j.transaksi_id!=tid or (j.oleh_id!=akun.id and not (pengawasan and akun.is_admin)):
        raise service.LayananError('Pekerjaan ini tidak tersedia bagi akun sekarang. Masuk kembali dengan akun pencetak semula.')
    return j

async def siapkan(db,tid,akun,data):
    await kunci_tiket(db,tid)
    key=str(data.get('kunci',''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,64}',key):raise service.LayananError('Kunci pekerjaan cetak tidak sah.')
    old=await db.get(Job,key)
    if old:
        if old.transaksi_id!=tid or old.oleh_id!=akun.id:raise service.LayananError('Kunci pekerjaan dipakai pada konteks lain.')
        return old
    format=data.get('format');keluaran=data.get('keluaran');alasan=str(data.get('alasan','')).strip()
    if format not in ('80MM','NCR') or keluaran not in ('printer','pdf') or (format=='NCR' and keluaran!='pdf'):
        raise service.LayananError('Pilihan format dan keluaran tidak sah.')
    if len(alasan)>2000:raise service.LayananError('Alasan terlalu panjang (maksimal 2000 karakter).')
    b,aturan,u=await bahan(db,tid,akun)
    cap=sidik(u,akun)
    if data.get('sidik')!=cap:raise service.LayananError('Data tiket atau riwayat cetak berubah. Perbarui pratinjau dan tinjau data terbaru sebelum mencetak.')
    if u['cetakan_ke']>1 and not alasan:raise service.LayananError('Cetak ulang harus disertai alasan.')
    pending=await db.scalar(select(Job).where(Job.transaksi_id==tid,Job.status.in_(AKTIF)))
    if pending:raise service.LayananError('Masih ada pekerjaan cetak milik '+pending.nama_pencetak+'. Periksa hasilnya atau minta Admin menuntaskannya sebelum membuat perintah baru.')
    j=Job(kunci=key,transaksi_id=tid,oleh_id=akun.id,nama_pencetak=akun.nama,
        format=format,keluaran=keluaran,status='siap',sidik=cap,versi_tiket=service.versi_tiket(b.trx),
        revisi=int(b.trx.jumlah_revisi or 0),urutan=u['cetakan_ke'],alasan=alasan or None,konten=dokumen(u,format,keluaran))
    db.add(j)
    try:
        await db.commit()
    except IntegrityError:
        # Dua tiket berbeda tidak berbagi row lock. Kunci tetap global;
        # konflik lintas tiket ditolak tanpa mencetak atau menimpa pekerjaan.
        await db.rollback()
        old=await db.get(Job,key)
        if old:
            if old.transaksi_id==tid and old.oleh_id==akun.id:return old
            raise service.LayananError('Kunci pekerjaan dipakai pada konteks lain.') from None
        raise
    return j

async def keluarkan(db,tid,key,akun):
    j=await milik(db,tid,key,akun)
    if j.status!='siap':raise service.LayananError('Perintah ini sudah diproses. Periksa hasil fisik; jangan mengirim ulang.')
    b,a,u=await bahan(db,tid,akun)
    if sidik(u,akun)!=j.sidik:
        j.status='dibatalkan';await db.commit()
        raise service.LayananError('Data berubah sebelum dikirim. Perbarui pratinjau dan tinjau revisi terbaru.')
    j.status='dikirim' if j.keluaran=='printer' else 'pdf_siap'
    await db.commit();return j

async def hasil(db,tid,key,akun,hasil,ip=None,alasan_penyelesaian=None):
    j=await milik(db,tid,key,akun,pengawasan=True)
    if hasil not in ('printer_berhasil','dikonfirmasi','belum_tercetak','gagal'):
        raise service.LayananError('Hasil cetak tidak dikenal.')
    if j.status in ('berhasil','gagal','belum_tercetak','dibatalkan'):return j
    pencetak=akun
    if j.oleh_id!=akun.id:
        if hasil=='printer_berhasil':
            raise service.LayananError('Admin harus memeriksa hasil fisik, lalu memilih konfirmasi petugas; ACK pencetak lain tidak boleh diklaim.')
        if not isinstance(alasan_penyelesaian,str) or not alasan_penyelesaian.strip():
            raise service.LayananError('Isi alasan penyelesaian pekerjaan petugas lain setelah memeriksa hasil cetak.')
        alasan_penyelesaian=alasan_penyelesaian.strip()
        if len(alasan_penyelesaian)>2000:raise service.LayananError('Alasan penyelesaian maksimal 2000 karakter.')
        pencetak=await db.get(TimbanganAkun,j.oleh_id)
        if pencetak is None:raise service.LayananError('Identitas pencetak semula tidak tersedia.')
        await service.catat_audit(db,akun=akun,aksi='TUNTASKAN_CETAK',entitas='transaksi',entitas_id=tid,
            ringkasan=alasan_penyelesaian,sebelum={'pekerjaan':key,'status':j.status,'pencetak_id':j.oleh_id},
            sesudah={'hasil':hasil,'penyelesai_id':akun.id},ip=ip)
    if hasil in ('belum_tercetak','gagal'):
        j.status=hasil;await db.commit();return j
    if j.status not in ('dikirim','pdf_siap') or (hasil=='printer_berhasil' and j.keluaran!='printer'):
        raise service.LayananError('Pekerjaan belum dikirim untuk keluaran tersebut.')
    trx=await db.get(TimbanganTransaksi,tid)
    j.metode='Printer mengonfirmasi' if hasil=='printer_berhasil' else 'Dikonfirmasi petugas'
    if rangkap(j) == 2:j.metode += ' (2 lbr)'
    await service.catat_cetak(db,akun=pencetak,trx=trx,alasan=j.alasan,format=j.format,ip=ip,pekerjaan=j)
    return j

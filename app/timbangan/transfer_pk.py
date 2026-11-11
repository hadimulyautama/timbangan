"""Pos Timbang hanya menulis tiketnya. PadiFlow tetap satu-satunya penulis stok.

Status baru/tertunda disimpan pada tiket. Poller mengulang sinkronisasi dari
hasil yang sudah commit, sehingga HP mati atau balasan RPC hilang tidak
memaksa petugas menimbang lagi dan tidak menggandakan perpindahan.
"""
import asyncio,logging
from decimal import Decimal
from sqlalchemy import select,update,text,inspect
from app.timbangan import klien_produksi
from app.timbangan.db import sesi_db
from app.timbangan.models import TimbanganTransaksi
log=logging.getLogger(__name__)

async def pilihan(ident,akun,lihat=None):
    from app.timbangan.service import LayananError
    if not akun.akun_id:raise LayananError('Pilih akun bersama yang memiliki akses gudang asal PadiFlow.')
    try:data=await klien_produksi._minta('GET',f'/internal/pk/pengiriman/{ident}',operator_akun_id=akun.akun_id,lihat=lihat)
    except klien_produksi.ProduksiTakTersedia as e:raise LayananError(str(e)) from e
    try:
        if type(data['id']) is not int or data['id']!=ident or data['status']=='dibatalkan':raise ValueError()
        total=Decimal(str(data['total']))
        if not data['items'] or not total.is_finite() or total<=0:raise ValueError()
        if sum(Decimal(str(i['berat_kg'])) for i in data['items'])!=total:raise ValueError()
        if any(not Decimal(str(i['berat_kg'])).is_finite() or Decimal(str(i['berat_kg']))<=0 for i in data['items']):raise ValueError()
        for k in ('asal','tujuan'):
            if type(data['lintasan'][k]['gudang_id']) is not int:raise ValueError()
        if len(data['sidik'])!=64:raise ValueError()
    except (KeyError,TypeError,ValueError,ArithmeticError):raise LayananError('Cuplikan muatan transfer dari PadiFlow tidak sah.')
    return data

async def siapkan(db,akun,data,trx=None):
    from app.timbangan.service import LayananError,normalisasi_nopol
    ident=data.pengiriman_pk_id
    if ident is not None and (type(ident) is not int or not 0<ident<=2147483647):raise LayananError('Identitas perjalanan PK tidak sah.')
    if not ident:
        if trx and trx.pengiriman_pk_id:raise LayananError('Kiriman ulang harus mempertahankan pengiriman PK yang sama.')
        return None
    if data.arah!='TRANSFER' or data.cara_timbang!='DUA_KALI':raise LayananError('Pengiriman PK memakai Transfer Internal dua kali timbang.')
    if trx:
        if trx.pengiriman_pk_id!=ident:raise LayananError('Kunci kiriman sudah dipakai untuk perjalanan lain.')
        # Replay memakai snapshot historisnya, tidak bergantung pada jaringan
        # atau keadaan master yang mungkin telah berubah sesudah perjalanan.
        return trx.lintasan_transfer
    snapshot=await pilihan(ident,akun,data.produksi_lihat)
    if snapshot['status']!='dalam_perjalanan':raise LayananError('Pengiriman sudah memiliki hasil timbang; buka tiket yang ada.')
    if normalisasi_nopol(data.nomor_polisi)!=normalisasi_nopol(snapshot['nomor_polisi']):raise LayananError('Nomor polisi berbeda dari muatan PadiFlow.')
    route=snapshot['lintasan'];a=str(route['asal']['gudang_id']);t=route['tujuan']['pilihan']
    if (data.transfer_asal and data.transfer_asal!=a) or (data.transfer_tujuan and data.transfer_tujuan!=t):raise LayananError('Lintasan harus mengikuti muatan PadiFlow yang dipilih.')
    data.transfer_asal=a;data.transfer_tujuan=t
    if db.bind.dialect.name=='postgresql':
        await db.execute(text('SELECT pg_advisory_xact_lock(14146833,:id)'),{'id':ident})
        # Pemeriksaan sesudah lock menutup balapan dengan pembatalan perjalanan.
        status=await db.scalar(text('SELECT status FROM pengiriman_pk WHERE id=:id'),{'id':ident})
        if status!='dalam_perjalanan':raise LayananError('Pengiriman berubah; baca kembali muatan PadiFlow.')
    existing=await db.scalar(select(TimbanganTransaksi.id).where(TimbanganTransaksi.pengiriman_pk_id==ident))
    if existing is not None:raise LayananError('Perjalanan ini sudah memiliki tiket. Buka tiket yang ada, bukan menimbang ulang.')
    return {**route,'_pengiriman_pk':dict(id=ident,sidik=snapshot['sidik'],total=snapshot['total'],items=snapshot['items'])}

async def penjaga_koreksi(db,trx,perubahan,muatan):
    from app.timbangan.service import LayananError
    if not trx.pengiriman_pk_id:return
    if 'lintasan_transfer' in perubahan and perubahan['lintasan_transfer']!=trx.lintasan_transfer:raise LayananError('Lintasan mengikuti perjalanan PadiFlow; tidak diubah terpisah dari muatannya.')
    affects=muatan is not None or bool({'timbang1_kg','timbang2_kg','tara_lain_kg'}&perubahan.keys())
    if not affects:return
    exists=await db.run_sync(lambda d:inspect(d.connection()).has_table('pengiriman_pk'))
    if not exists:raise LayananError('Status stok PadiFlow tidak dapat dibuktikan; koreksi bobot ditahan.')
    status=await db.scalar(text('SELECT status FROM pengiriman_pk WHERE id=:id'),{'id':trx.pengiriman_pk_id})
    if status not in ('dalam_perjalanan','menunggu_admin'):raise LayananError('Stok perjalanan sudah diselesaikan atau dibatalkan. Koreksi bobot harus menjaga seluruh muatan PadiFlow.')
    trx.pengiriman_pk_status='baru'

async def sinkron_satu(tid):
    """Jangan memegang kunci tiket saat meminta writer PadiFlow menguncinya."""
    if not klien_produksi.terkonfigurasi():return
    async with sesi_db() as db:
        t=await db.get(TimbanganTransaksi,tid)
        if not t or not t.pengiriman_pk_id or t.status_tiket!='SELESAI' or t.status_transaksi=='VOID':return
        pid=t.pengiriman_pk_id;revisi=t.jumlah_revisi;bobot=t.berat_barang_kg
    try:
        result=await klien_produksi._minta('POST',f'/internal/pk/pengiriman/{pid}/sinkron/{tid}')
        status=result.get('status')
        if result.get('ok') is not True or status not in ('selesai','menunggu_admin'):raise klien_produksi.ProduksiTakTersedia('Balasan penyelesaian transfer belum lengkap.')
    except klien_produksi.ProduksiTakTersedia:
        log.warning('Penyelesaian perjalanan PK %s tertunda; akan dicoba ulang.',pid)
        return
    async with sesi_db() as db:
        await db.execute(update(TimbanganTransaksi).where(TimbanganTransaksi.id==tid,TimbanganTransaksi.jumlah_revisi==revisi,TimbanganTransaksi.berat_barang_kg==bobot,TimbanganTransaksi.status_tiket=='SELESAI').values(pengiriman_pk_status=status))
        await db.commit()

_terakhir=0

async def sinkron_tertunda():
    global _terakhir
    async with sesi_db() as db:
        ids=list((await db.scalars(select(TimbanganTransaksi.id).where(TimbanganTransaksi.id>_terakhir,TimbanganTransaksi.pengiriman_pk_id.is_not(None),TimbanganTransaksi.status_tiket=='SELESAI',TimbanganTransaksi.status_transaksi!='VOID',((TimbanganTransaksi.pengiriman_pk_status.is_(None))|TimbanganTransaksi.pengiriman_pk_status.in_(['baru','tertunda','menunggu_admin']))).order_by(TimbanganTransaksi.id).limit(30))).all())
    _terakhir=ids[-1] if ids else 0
    for tid in ids:await sinkron_satu(tid)

async def pekerja():
    while True:
        try:await sinkron_tertunda()
        except asyncio.CancelledError:raise
        except Exception:log.exception('Pemeriksaan pengiriman PK tertunda gagal; akan diulang.')
        await asyncio.sleep(20)

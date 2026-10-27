"""Pilihan lintasan tiket, bukan perintah transfer atau perpindahan stok.

Identitas dan nama dipotret saat dipilih. Tiket lama tidak dipetakan dari
teks bebas; kiriman ulang mempertahankan snapshot walaupun master berganti.
"""
from sqlalchemy import select
from hmu_core import Warehouse, Silo
from app.timbangan import logic


class LintasanTidakSah(ValueError):
    pass


def teks(data):
    if not data:
        return None
    return data['asal']['nama'] + ' → ' + data['tujuan']['nama']


def token(data):
    if not data:
        return '', ''
    return str(data['asal']['gudang_id']), data['tujuan']['pilihan']


async def pilihan(db, tersimpan=None):
    gudang = {w.kode_fungsi:w for w in (await db.scalars(select(Warehouse)
        .where(Warehouse.kode_fungsi.in_(['g1','g2']),Warehouse.aktif.is_(True)))).all()}
    asal,tujuan=[],[]
    if 'g1' in gudang:
        w=gudang['g1'];asal=[dict(nilai=str(w.id),nama=w.nama_gudang)]
    if 'g2' in gudang:
        w=gudang['g2'];tujuan=[dict(nilai=f'gudang:{w.id}',nama='Tumpukan · '+w.nama_gudang)]
        for s in (await db.scalars(select(Silo).where(Silo.warehouse_id==w.id,
            Silo.aktif.is_(True),Silo.jenis_isi=='pk').order_by(Silo.nama_silo,Silo.id))).all():
            tujuan.append(dict(nilai=f'silo:{s.id}',nama=s.nama_silo+' · '+w.nama_gudang))
    if tersimpan:
        a,t=token(tersimpan)
        for daftar,nilai,nama in [(asal,a,tersimpan['asal']['nama']),(tujuan,t,tersimpan['tujuan']['nama'])]:
            if not any(o['nilai']==nilai for o in daftar):
                daftar.append(dict(nilai=nilai,nama=nama+' (tersimpan)'))
    return dict(asal=asal,tujuan=tujuan)


def _id_sah(nilai):
    return (nilai.isascii() and nilai.isdigit() and len(nilai) <= 10
            and 0 < int(nilai) <= 2147483647)


async def baca(db, asal, tujuan, *, tersimpan=None):
    asal,tujuan=str(asal or '').strip(),str(tujuan or '').strip()
    if not asal or not tujuan:
        raise LintasanTidakSah('Pilih asal dan tujuan transfer dari daftar.')
    if tersimpan and token(tersimpan)==(asal,tujuan):
        return tersimpan
    if not _id_sah(asal):
        raise LintasanTidakSah('Asal transfer tidak sah.')
    w1=await db.get(Warehouse,int(asal))
    w2=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2',Warehouse.aktif.is_(True)))
    if not w1 or not w1.aktif or w1.kode_fungsi!='g1' or not w2:
        raise LintasanTidakSah('Lintasan harus dari Gudang 1 aktif menuju Gudang 2 aktif.')
    if tujuan==f'gudang:{w2.id}':
        lokasi=dict(pilihan=tujuan,gudang_id=w2.id,silo_id=None,nama='Tumpukan · '+w2.nama_gudang)
    elif tujuan.startswith('silo:') and _id_sah(tujuan[5:]):
        s=await db.get(Silo,int(tujuan[5:]))
        if not s or not s.aktif or s.warehouse_id!=w2.id or s.jenis_isi!='pk':
            raise LintasanTidakSah('Pilih silo PK aktif di Gudang 2.')
        lokasi=dict(pilihan=tujuan,gudang_id=w2.id,silo_id=s.id,nama=s.nama_silo+' · '+w2.nama_gudang)
    else:
        raise LintasanTidakSah('Tujuan transfer tidak ada pada daftar yang sah.')
    return dict(versi=1,asal=dict(gudang_id=w1.id,nama=w1.nama_gudang),tujuan=lokasi)


async def perubahan(db,trx,form):
    """Kosong pada formulir koreksi lama berarti tidak mengubah lintasan."""
    asal,tujuan=form.get('transfer_asal',''),form.get('transfer_tujuan','')
    if not asal and not tujuan:
        return {},[]
    if trx.arah != logic.TRANSFER:
        raise LintasanTidakSah("Pilihan lintasan hanya untuk Transfer Internal.")
    data=await baca(db,asal,tujuan,tersimpan=trx.lintasan_transfer)
    if data==trx.lintasan_transfer:
        return {},[]
    return {'lintasan_transfer':data,'pihak_nama':teks(data)[:100]},[dict(
        field='lintasan_transfer',label='Asal–tujuan',lama=teks(trx.lintasan_transfer) or trx.pihak_nama or 'Belum tercatat',baru=teks(data))]

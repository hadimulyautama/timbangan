"""Pembaca/guard Retur Supplier: SQLite baru tiap kasus, tanpa data operasional."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4
import pytest
import httpx
from sqlalchemy import select, func, text
from test_web import app_uji, klien, login
from test_rincian_retur import tautkan
from app import database
from app.models import Supplier
from app.timbangan import service, klien_produksi, rincian_supplier
from app.timbangan.models import TimbanganAkun, TimbanganTransaksi, TimbanganAudit, TimbanganCetak
from hmu_identitas import peran as P


async def tiket(selesai=True):
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        s=await db.scalar(select(Supplier))
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(
            kunci=str(uuid4()),arah='RETUR_KELUAR',jenis_kode='RETUR_SUPPLIER',berat_kg=6500,
            nomor_polisi='B 1234 UJ',nama_sopir='Sopir Uji',supplier_id=s.id))
        if selesai:
            t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=6570.1,
                muatan=[service.InputMuatan(jenis_kode='RETUR_SUPPLIER',jumlah_karung=2,
                    tara_per_karung_kg=Decimal('.0858'))])
        return t.id


def payload(t,status='diajukan'):
    return dict(tiket_id=t.id,kode_tiket=t.kode,arah=t.arah,supplier_id=t.supplier_id,status=status,
        pengajuan=None if status=='belum_terhubung' else dict(id=99,kode='RS-UJI-99',penerimaan_tiket_id=800,
            supplier_id=t.supplier_id,supplier='Supplier sintetis',penerimaan='MASUK-UJI-800',nota='NOTA-UJI',
            alasan='Kualitas sumber perlu diperiksa',catatan='UJI BUKAN OPERASIONAL',total_kg='70',
            items=[dict(kunci_sumber='pk:123',kode='PK-UJI',nama='Barang sumber sintetis',gudang='Gudang uji',
                        pemilik='Milik pabrik',satuan='karung',jumlah='2',bobot_kg='50'),
                   dict(kunci_sumber='bp:124',kode='BP-UJI',nama='Broken uji',gudang='Gudang uji',
                        pemilik='Milik pabrik',satuan='kg',jumlah='20',bobot_kg='20')]))


async def sumber(monkeypatch,tid,status='diajukan'):
    async with database.SessionLocal() as db:d=payload(await db.get(TimbanganTransaksi,tid),status)
    calls=[]
    async def baca(tid,aid,*,lihat=None):calls.append((tid,aid,lihat));return deepcopy(d)
    monkeypatch.setattr(klien_produksi,'detail_retur_supplier',baca)
    return d,calls


@pytest.mark.parametrize('status',['diajukan','dibatalkan','belum_terhubung','selesai_gudang'])
@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_panel_baca_saja_berizin(klien,monkeypatch,status,role):
    tid=await tiket();aid=await tautkan('miftah',role);data,calls=await sumber(monkeypatch,tid,status)
    if data['pengajuan']:data['pengajuan']['harga']='RAHASIA-JANGAN-RENDER'
    await login(klien,'miftah');klien.cookies.set('produksi_lihat','operator:gudang1')
    async with database.SessionLocal() as db:
        before=[await db.scalar(select(func.count()).select_from(m)) for m in (TimbanganTransaksi,TimbanganAudit,TimbanganCetak)]
    for _ in range(2):
        r=await klien.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200
        assert r.headers['cache-control']=='private, no-store'
        assert rincian_supplier.LABEL[status] in r.text and 'RAHASIA-JANGAN-RENDER' not in r.text
        assert ('/retur-supplier/99' in r.text)==(status!='belum_terhubung')
        assert 'Cetak bukti timbang' in r.text and 'Koreksi' in r.text
        assert ('Hapus permanen' in r.text)==(role==P.SUPERADMIN)
    assert calls==[(tid,aid,'operator:gudang1')]*2
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.total_tara_kg==0 and Decimal(str(t.berat_barang_kg))==Decimal('70.1')
        assert [await db.scalar(select(func.count()).select_from(m)) for m in (TimbanganTransaksi,TimbanganAudit,TimbanganCetak)]==before


@pytest.mark.parametrize('keadaan',['tanpa-akun','403','timeout','salah-tiket','salah-kode','salah-arah','salah-supplier',
 'supplier-pengajuan','asal-sendiri','id-tidak-sah','status-baru','items-kosong','item-ganda','angka-nan','total-hilang'])
async def test_tidak_bocor_dan_tidak_sukses_palsu(klien,monkeypatch,keadaan):
    tid=await tiket()
    if keadaan!='tanpa-akun':await tautkan()
    d,calls=await sumber(monkeypatch,tid)
    if keadaan in ('403','timeout'):
        async def gagal(*a,**kw):
            raise (klien_produksi.ProduksiDilarang('Uji izin') if keadaan=='403' else klien_produksi.ProduksiTakTersedia('Uji sambungan'))
        monkeypatch.setattr(klien_produksi,'detail_retur_supplier',gagal)
    if keadaan=='salah-tiket':d['tiket_id']+=1
    if keadaan=='salah-kode':d['kode_tiket']='lain'
    if keadaan=='salah-arah':d['arah']='RETUR_MASUK'
    if keadaan=='salah-supplier':d['supplier_id']+=1
    if keadaan=='supplier-pengajuan':d['pengajuan']['supplier_id']+=1
    if keadaan=='asal-sendiri':d['pengajuan']['penerimaan_tiket_id']=tid
    if keadaan=='id-tidak-sah':d['pengajuan']['id']='//host-lain'
    if keadaan=='status-baru':d['status']='terverifikasi'
    if keadaan=='items-kosong':d['pengajuan']['items']=[]
    if keadaan=='item-ganda':d['pengajuan']['items']*=2
    if keadaan=='angka-nan':d['pengajuan']['items'][0]['bobot_kg']='NaN'
    if keadaan=='total-hilang':d['pengajuan']['total_kg']=None
    await login(klien,'wahid');r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert r.status_code==200 and 'RS-UJI-99' not in r.text and 'MASUK-UJI-800' not in r.text
    assert 'Cetak bukti timbang' in r.text
    label='dibatasi' if keadaan in ('403','tanpa-akun') else 'tidak_pasti'
    assert rincian_supplier.LABEL[label] in r.text
    if keadaan=='tanpa-akun':assert not calls


async def tautan(db,tid,status='diajukan'):
    await db.execute(text('CREATE TABLE retur_supplier (id INTEGER PRIMARY KEY,kode TEXT,timbangan_transaksi_id INTEGER UNIQUE,status TEXT)'))
    await db.execute(text('INSERT INTO retur_supplier VALUES (99,:kode,:tid,:status)'),{'kode':'RS-UJI-99','tid':tid,'status':status})
    await db.commit()


@pytest.mark.parametrize('status',['diajukan','dibatalkan','selesai_gudang'])
async def test_hapus_menjaga_pointer_riwayat(klien,status):
    tid=await tiket();await tautkan('wahid',P.SUPERADMIN);await login(klien,'wahid')
    async with database.SessionLocal() as db:
        await tautan(db,tid,status);t=await db.get(TimbanganTransaksi,tid);kode=t.kode
    r=await klien.post(f'/timbangan/transaksi/{tid}/hapus',data={'alasan':'Uji aman','ketik_kode':kode})
    assert 'hubungan pengajuan Retur ke Supplier' in r.text
    async with database.SessionLocal() as db:assert await db.get(TimbanganTransaksi,tid)


@pytest.mark.parametrize('status',['diajukan','selesai_gudang'])
async def test_supplier_jenis_dilindungi_bobot_dan_batal_tetap(klien,status):
    tid=await tiket()
    async with database.SessionLocal() as db:
        await tautan(db,tid,status);a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        t=await db.get(TimbanganTransaksi,tid);s=Supplier(nama_supplier='Supplier lain',kledo_contact_id=999);db.add(s);await db.commit();sid=s.id
        with pytest.raises(service.LayananError,match='hubungan pengajuan'):
            await service.koreksi_transaksi(db,akun=a,trx=t,alasan='Uji identitas',perubahan={'supplier_id':sid})
        with pytest.raises(service.LayananError,match='hubungan pengajuan'):
            await service.ubah_jenis(db,akun=a,trx=t,jenis_kode='PENGIRIMAN',alasan='Uji jenis')
        await service.koreksi_transaksi(db,akun=a,trx=t,alasan='Uji angka',perubahan={'timbang2_kg':6571.2,'nama_sopir':'Sopir Baru'})
        assert t.total_tara_kg==0 and Decimal(str(t.berat_barang_kg))==Decimal('71.2')
        await service.void_transaksi(db,akun=a,trx=t,alasan='Uji batal')
        assert t.status_transaksi=='VOID'
        assert (await db.execute(text('SELECT timbangan_transaksi_id,status FROM retur_supplier'))).one()==(tid,status)


async def test_terbuka_dan_muatan_belum_terbaca_tidak_menghalangi_timbang(klien,monkeypatch):
    tid=await tiket(False);await tautkan();d,c=await sumber(monkeypatch,tid,'belum_terhubung');await login(klien,'wahid')
    r=await klien.get(f'/timbangan/transaksi/{tid}');assert 'Menunggu timbang kedua' in r.text and 'Cetak bukti timbang' not in r.text
    async with database.SessionLocal() as db:
        await tautan(db,tid);a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'));t=await db.get(TimbanganTransaksi,tid)
        await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=6600,muatan=[service.InputMuatan(jenis_kode='RETUR_SUPPLIER',jumlah_karung=2)])
        assert t.status_tiket=='SELESAI' and t.berat_barang_kg==100 and t.total_tara_kg==0


@pytest.mark.parametrize('http_status',[200,403,409,500])
async def test_klien_memakai_get_dan_identitas_akun(monkeypatch,http_status):
    calls=[];client=httpx.AsyncClient
    async def handler(req):
        calls.append(req)
        return httpx.Response(http_status,json={'status':'belum_terhubung'})
    monkeypatch.setattr(klien_produksi,'settings',replace(klien_produksi.settings,produksi_api_url='http://uji-internal',produksi_api_token='token-sintetis'))
    monkeypatch.setattr(klien_produksi.httpx,'AsyncClient',lambda **kw:client(transport=httpx.MockTransport(handler),**kw))
    if http_status==200:await klien_produksi.detail_retur_supplier(1,77,lihat='operator:gudang1')
    else:
        error=klien_produksi.ProduksiDilarang if http_status==403 else klien_produksi.ProduksiTakTersedia
        with pytest.raises(error):await klien_produksi.detail_retur_supplier(1,77,lihat='operator:gudang1')
    assert len(calls)==1 and calls[0].method=='GET'
    assert calls[0].url.path=='/internal/retur-supplier/tiket/1/detail'
    assert calls[0].headers['X-Internal-Token']=='token-sintetis'
    assert calls[0].headers['X-Operator-Akun']=='77' and calls[0].headers['X-Produksi-Lihat']=='operator:gudang1'


@pytest.mark.parametrize('ada',[False,True])
async def test_penyelesaian_opsional_tidak_dianggap_penerimaan_supplier(klien,monkeypatch,ada):
    tid=await tiket();await tautkan();d,calls=await sumber(monkeypatch,tid,'selesai_gudang')
    if ada:
        d['penyelesaian']=dict(kode='KRS-UJI',waktu='2026-10-27T10:00:00+07:00',total_kg='70',metode_verifikasi='manual',hpp='JANGAN-TAMPIL')
    await login(klien,'wahid');r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert r.status_code==200 and 'Selesai di gudang' in r.text
    assert 'bukan konfirmasi penerimaan supplier' in r.text
    assert ('KRS-UJI' in r.text)==ada and 'JANGAN-TAMPIL' not in r.text

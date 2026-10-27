"""Cuplikan per perjalanan dan alokasi sumber, tanpa menyentuh data operasional."""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from app.timbangan import pengiriman, service, logic
from app.timbangan.models import TimbanganTransaksi, TimbanganAudit


def payload():
    penerima=[dict(perintah_id=11+i,kode_perintah=f'OUT-UJI-{i}',pelanggan_id=71+i,pelanggan=f'Penerima Uji {i}') for i in range(2)]
    rows=[]
    for i,(kg,n,tara) in enumerate([(500,20,'.1'),(1000,20,'.25'),(1000,40,'.1'),(1500,30,'.25')]):
        p=penerima[i//2]
        rows.append(dict(**p,outgoing_item_id=101+i,jenis_kode='BERAS',nama=f'Beras kemasan {i%2}',
                         berat_kg=kg,jumlah_karung=n,tara_per_karung_kg=tara,satuan='karung',jumlah=n))
    return dict(kiriman_id=3,kode_perintah='OUT-UJI-0',pelanggan='Kiriman bersama',
                nomor_polisi='B 1234 UJ',sidik_sumber='a'*64,penerima=penerima,muatan=rows)


async def tiket(db, akun):
    await service.pastikan_jenis(db)
    return await service.simpan_timbang_pertama(db,akun=akun,data=service.InputTimbang(
        kunci=str(uuid4()),arah='KELUAR',jenis_kode='PENGIRIMAN',berat_kg=5000,
        nomor_polisi='B 1234 UJ',nama_sopir='Sopir Sintetis'))


def test_kelompok_dan_subtotal_tidak_meratakan_pelanggan():
    d=pengiriman.cuplikan(payload());groups=pengiriman.kelompok(d)
    assert len(groups)==2 and [p['subtotal'] for p in groups]==[Decimal(1500),Decimal(2500)]
    assert [len(p['baris']) for p in groups]==[2,2]
    assert [p['pelanggan_id'] for p in groups]==[71,72]
    assert pengiriman.ringkasan(d)=='Pengiriman · 2 pelanggan · 4 baris barang'


@pytest.mark.parametrize('cacat',['tanpa-tara','negatif','nan','inf','karung-pecahan','pemilik-salah','item-ganda','tanpa-sidik','kosong','berat-tidak-tersedia'])
def test_payload_cacat_ditahan(cacat):
    p=payload()
    if cacat=='tanpa-tara':p['muatan'][0]['tara_per_karung_kg']=None
    if cacat=='negatif':p['muatan'][0]['berat_kg']=-1
    if cacat=='nan':p['muatan'][0]['berat_kg']='NaN'
    if cacat=='inf':p['muatan'][0]['tara_per_karung_kg']='Infinity'
    if cacat=='karung-pecahan':p['muatan'][0]['jumlah_karung']=1.5
    if cacat=='pemilik-salah':p['muatan'][0]['pelanggan_id']=72
    if cacat=='item-ganda':p['muatan'][1]['outgoing_item_id']=101
    if cacat=='tanpa-sidik':p['sidik_sumber']=None
    if cacat=='kosong':p['muatan']=[]
    if cacat=='berat-tidak-tersedia':p['muatan'][0]['berat_kg']=None
    with pytest.raises(pengiriman.MuatanTidakSah):pengiriman.cuplikan(p)


def test_allowlist_tidak_membawa_data_uang():
    p=payload();p['hpp']=990;p['muatan'][0]['harga']=111
    s=pengiriman.cuplikan(p)
    assert 'hpp' not in s and 'harga' not in s['muatan'][0]
    assert set(s['muatan'][0])>= {'outgoing_item_id','perintah_id','pelanggan_id'}


async def test_satu_tiket_hasil_total_dan_tara_setiap_baris(db,petugas):
    t=await tiket(db,petugas);p=payload()
    t=await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9018.5,pengiriman_snapshot=p)
    assert t.status_tiket=='SELESAI' and float(t.netto_timbangan_kg)==4018.5
    assert float(t.total_tara_kg)==18.5 and float(t.berat_barang_kg)==4000
    assert float(t.berat_acuan_kg)==4000 and float(t.selisih_kg)==0
    assert t.pelanggan_id is None and t.pihak_nama is None and len(t.muatan)==4
    assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==1
    assert [b['berat_kg'] for b in t.pengiriman_snapshot['muatan']]==['500','1000','1000','1500']
    before=deepcopy(t.pengiriman_snapshot)
    await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9018.5,pengiriman_snapshot=p)
    assert t.pengiriman_snapshot==before
    n=await db.scalar(select(func.count()).select_from(TimbanganAudit))
    with pytest.raises(service.LayananError,match='berubah'):
        p['muatan'][0]['berat_kg']=600
        await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9018.5,pengiriman_snapshot=p)
    assert await db.scalar(select(func.count()).select_from(TimbanganAudit))==n
    assert t.pengiriman_snapshot==before


async def test_selisih_tidak_dialokasikan_ke_pelanggan(db,petugas):
    t=await tiket(db,petugas)
    t=await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9118.5,pengiriman_snapshot=payload())
    assert float(t.selisih_kg)==100 and float(t.berat_barang_kg)==4100
    assert [p['subtotal'] for p in pengiriman.kelompok(t.pengiriman_snapshot)]==[Decimal(1500),Decimal(2500)]


async def test_sementara_tetap_tanpa_cuplikan_final(db,petugas):
    t=await tiket(db,petugas)
    t=await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9018.5,selesaikan=False)
    assert t.status_tiket=='TERBUKA' and t.pengiriman_snapshot is None and t.berat_barang_kg is None


async def test_koreksi_sopir_tetap_menjaga_alokasi_dan_angka(db,petugas,admin):
    t=await tiket(db,petugas)
    t=await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9018.5,pengiriman_snapshot=payload())
    old=deepcopy(t.pengiriman_snapshot)
    await service.koreksi_transaksi(db,akun=admin,trx=t,perubahan={'nama_sopir':'Sopir Sintetis Baru'},alasan='Perbaiki ejaan')
    assert t.pengiriman_snapshot==old and float(t.berat_barang_kg)==4000
    muatan=pengiriman.input_muatan(old);muatan[0].jumlah_karung=99
    with pytest.raises(service.LayananError,match='PadiFlow'):
        await service.koreksi_transaksi(db,akun=admin,trx=t,perubahan={},muatan=muatan,alasan='Uji larangan')


def test_bukti_rahasia_tidak_membocorkan_pembanding():
    from types import SimpleNamespace
    t=SimpleNamespace(pengiriman_snapshot=pengiriman.cuplikan(payload()))
    aman='\n'.join(pengiriman.rincian_bukti(t))
    assert 'Penerima Uji 0' in aman and 'Penerima Uji 1' in aman
    assert 'Subtotal muat' not in aman and 'Total acuan' not in aman
    assert '4.000' in '\n'.join(pengiriman.rincian_bukti(t,berat=True))

async def test_baca_ulang_sumber_audit_tetap_tanpa_mengubah_bacaan(db,petugas,admin):
    t=await tiket(db,petugas)
    t=await service.simpan_timbang_kedua(db,akun=petugas,kode=t.kode,berat_kg=9018.5,pengiriman_snapshot=payload())
    asli=deepcopy(t.pengiriman_snapshot);baru=payload();baru['sidik_sumber']='b'*64
    baru['muatan'][0]['berat_kg']=600
    await service.koreksi_transaksi(db,akun=admin,trx=t,perubahan={},pengiriman_snapshot=baru,alasan='Sumber muatan telah dikoreksi di PadiFlow')
    assert float(t.timbang1_kg)==5000 and float(t.timbang2_kg)==9018.5
    assert float(t.berat_acuan_kg)==4100 and float(t.berat_barang_kg)==4000 and float(t.selisih_kg)==-100
    audit=await db.scalar(select(TimbanganAudit).where(TimbanganAudit.aksi=='KOREKSI').order_by(TimbanganAudit.id.desc()))
    import json
    assert json.loads(audit.nilai_sebelum)['pengiriman_snapshot']==asli
    assert t.pengiriman_snapshot['sidik_sumber']=='b'*64
    n=t.jumlah_revisi
    await service.koreksi_transaksi(db,akun=admin,trx=t,perubahan={},pengiriman_snapshot=baru,alasan='Uji ulang cuplikan sama')
    assert t.jumlah_revisi==n
    baru['kiriman_id']=99
    with pytest.raises(service.LayananError,match='perjalanan lain'):
        await service.koreksi_transaksi(db,akun=admin,trx=t,perubahan={},pengiriman_snapshot=baru,alasan='Uji pagar')

async def test_laporan_filter_dan_csv_satu_baris_per_tiket(klien):
    from test_web import login
    from app import database
    from app.timbangan.models import TimbanganAkun
    import csv,io
    await login(klien,'wahid')
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        t=await tiket(db,a)
        await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=9018.5,pengiriman_snapshot=payload())
        ringkas=await service.ringkasan_dashboard(db,service.FilterTransaksi())
        assert ringkas.jumlah==1 and float(ringkas.keluar_kg)==4000 and float(ringkas.masuk_kg)==0
        f=service.FilterTransaksi(jenis_kode='BERAS',cari='Penerima Uji 1')
        assert await service.hitung_transaksi(db,f)==1
        assert len(await service.daftar_transaksi(db,f))==1
    r=await klien.get('/timbangan/ekspor.csv')
    assert r.status_code==200
    rows=list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows)==1 and Decimal(rows[0]['berat_barang_kg'])==4000
    assert rows[0]['pihak']=='Pengiriman · 2 pelanggan · 4 baris barang'
    await login(klien,'budi')
    assert (await klien.get('/timbangan/ekspor.csv')).status_code==403
    assert (await klien.get('/timbangan/laporan')).status_code==403

# Fixture HTTP memakai SQLite terpisah; kasus service di atas tetap memakai
# fixture db per uji seperti sebelumnya, tidak ada database operasional.
from test_web import app_uji,klien  # noqa: E402,F401

async def test_bacaan_sementara_desimal_tidak_dibulatkan_saat_form_dibuka(klien,monkeypatch):
    from test_web import login
    from app import database
    from app.timbangan import klien_produksi
    from app.timbangan.models import TimbanganAkun
    async def terputus(tid):raise klien_produksi.ProduksiTakTersedia('Jaringan uji terputus')
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',terputus)
    await login(klien,'budi')
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        t=await tiket(db,a)
        t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=9018.875,selesaikan=False)
        tid=t.id
    r=await klien.get(f'/timbangan/tiket/{tid}')
    assert 'value="9018,875"' in r.text
    assert 'Jaringan uji terputus' in r.text

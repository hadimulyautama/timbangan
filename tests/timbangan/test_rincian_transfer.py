"""Transfer: SQLite terpisah per uji, tidak membaca data operasional."""
import io
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from pypdf import PdfReader
from test_web import app_uji,klien,login,kode_dari
from test_rincian_retur import tautkan
from app import database
from app.timbangan import service,lintasan_transfer as lintasan
from app.timbangan.models import TimbanganAkun,TimbanganTransaksi,TimbanganAudit,TimbanganCetak
from hmu_core import Warehouse,Silo
from hmu_identitas import peran as P

async def master():
    async with database.SessionLocal() as db:
        db.add_all([Warehouse(id=101,kode_fungsi='g1',nama_gudang='Gudang 1 uji',aktif=True),Warehouse(id=102,kode_fungsi='g2',nama_gudang='Gudang 2 uji',aktif=True)])
        await db.flush()
        db.add_all([Silo(id=103,warehouse_id=102,nama_silo='Silo A uji',jenis_isi='pk',aktif=True),Silo(id=104,warehouse_id=102,nama_silo='Silo B uji',jenis_isi='pk',aktif=True),Silo(id=105,warehouse_id=102,nama_silo='Tong beras',jenis_isi='beras',aktif=True),Silo(id=106,warehouse_id=101,nama_silo='Silo G1',jenis_isi='pk',aktif=True),Silo(id=107,warehouse_id=102,nama_silo='Silo tidak aktif',jenis_isi='pk',aktif=False)])
        await db.commit()

async def tiket(*,selesai=True,terstruktur=True,karung=100,tara='.0858',lain=2,nopol=None,catatan='TRF-UJI-123 hanya catatan'):
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(kunci=str(uuid4()),arah='TRANSFER',jenis_kode='TRANSFER',berat_kg=10500,nama_sopir='Sopir Uji',nomor_polisi=nopol,pihak_nama=None if terstruktur else 'Lintasan historis tanpa pemisah',transfer_asal='101' if terstruktur else '',transfer_tujuan='silo:103' if terstruktur else '',catatan=catatan))
        if selesai:
            t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=6500,tara_lain_kg=lain,muatan=[service.InputMuatan(jenis_kode='TRANSFER',jumlah_karung=karung,tara_per_karung_kg=Decimal(tara))])
        return t.id

@pytest.mark.parametrize('tujuan',['gudang:102','silo:103','silo:104'])
async def test_pilihan_simpan_replay_dan_snapshot(klien,tujuan):
    await master();await login(klien)
    page=await klien.get('/timbangan/timbang/TRANSFER');assert page.status_code==200
    assert '<input type="hidden" name="pihak_nama"' in page.text
    assert 'name="pihak_nama" type="text"' not in page.text
    assert 'Tong beras' not in page.text and 'Silo tidak aktif' not in page.text
    key=kode_dari(page.text)
    body=dict(kunci=key,berat_kg='10.500',nama_sopir='Sopir Uji',lintasan_format='1',transfer_asal='101',transfer_tujuan=tujuan)
    r=await klien.post('/timbangan/timbang/TRANSFER',data=body);assert 'Timbang pertama tersimpan' in r.text
    async with database.SessionLocal() as db:
        t=await db.scalar(select(TimbanganTransaksi));tid=t.id;snapshot=t.lintasan_transfer
        w=await db.get(Warehouse,101);w.nama_gudang='Master berganti';w.aktif=False
        s=await db.get(Silo,103);s.aktif=False;await db.commit()
    r=await klien.post('/timbangan/timbang/TRANSFER',data=body);assert 'Timbang pertama tersimpan' in r.text
    async with database.SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==1
        assert (await db.get(TimbanganTransaksi,tid)).lintasan_transfer==snapshot
    r=await klien.get(f'/timbangan/transaksi/{tid}');assert 'Gudang 1 uji' in r.text and 'Master berganti' not in r.text

@pytest.mark.parametrize('asal,tujuan',[('',''),('101',''),('102','gudang:102'),('101','gudang:101'),('101','silo:105'),('101','silo:106'),('101','silo:107'),('101','teks bebas'),('999','silo:103'),('999999999999999999999999','silo:103'),('101','silo:999999999999999999999999')])
async def test_lintasan_salah_ditolak_server(klien,asal,tujuan):
    await master();await login(klien)
    r=await klien.post('/timbangan/timbang/TRANSFER',data=dict(kunci=str(uuid4()),berat_kg='10500',nama_sopir='Sopir Uji',lintasan_format='1',transfer_asal=asal,transfer_tujuan=tujuan))
    assert 'err=' in str(r.url)
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganTransaksi))==0

@pytest.mark.parametrize('terstruktur',[True,False])
@pytest.mark.parametrize('tara,lain',[('0',0),('.0858',0),('.0858',2)])
async def test_detail_historis_tanpa_mutasi_dan_angka(klien,monkeypatch,terstruktur,tara,lain):
    await master();tid=await tiket(terstruktur=terstruktur,tara=tara,lain=lain)
    async def dilarang(*a,**kw):raise AssertionError('Transfer tidak boleh membaca/menulis integrasi')
    from app.timbangan import klien_produksi
    monkeypatch.setattr(klien_produksi,'detail_masuk',dilarang);monkeypatch.setattr(klien_produksi,'muatan_pengiriman',dilarang)
    await login(klien,'miftah')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);before={c.name:getattr(t,c.name) for c in t.__table__.columns}
        counts=[await db.scalar(select(func.count()).select_from(m)) for m in [TimbanganAudit,TimbanganCetak]]
    for tab in ('ringkasan','perhitungan','jejak'):
        r=await klien.get(f'/timbangan/transaksi/{tid}?tab={tab}&kembali=/timbangan/transaksi%3Fhal=2')
        assert r.status_code==200
        for text in ['Ringkasan transfer','Perhitungan','Jejak &amp; dokumen','Tidak ada transfer tertaut','TRF-UJI-123 hanya catatan','Tanpa kontrol','/pekerjaan']:
            assert text in r.text,text
        assert 'Belum dipetakan' not in r.text if terstruktur else 'belum dipetakan' in r.text
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert {c.name:getattr(t,c.name) for c in t.__table__.columns}==before
        assert t.netto_timbangan_kg==4000 and Decimal(str(t.total_tara_kg))==Decimal(tara)*100+lain
        assert Decimal(str(t.berat_barang_kg))==4000-Decimal(tara)*100-lain
        assert t.status_kontrol=='TANPA_KONTROL'
        assert [await db.scalar(select(func.count()).select_from(m)) for m in [TimbanganAudit,TimbanganCetak]]==counts

@pytest.mark.parametrize('kondisi',['terbuka','sementara','batal','ditutup'])
async def test_status_dan_larangan_cetak(klien,kondisi):
    await master();tid=await tiket(selesai=kondisi=='batal')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        if kondisi=='sementara':await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=6500,selesaikan=False,muatan=[service.InputMuatan(jenis_kode='TRANSFER',jumlah_karung=100,tara_per_karung_kg=.0858)])
        if kondisi=='batal':t.status_transaksi='VOID';t.void_alasan='Batal uji'
        if kondisi=='ditutup':t.status_tiket='DITUTUP_PAKSA';t.tutup_paksa_alasan='Truk sudah pergi uji'
        await db.commit()
    await login(klien);r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert 'Hasil akhir belum tersedia' in r.text and 'Cetak bukti timbang' not in r.text
    if kondisi=='sementara':assert '6.500,00 kg · sementara' in r.text and '0,0858' in r.text
    for fmt in ('80mm','ncr','epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/{fmt}',follow_redirects=False)
        assert r.status_code==303 and 'err=' in r.headers['location']

async def test_koreksi_lokasi_versi_audit_dan_tanpa_perubahan(klien):
    await master();tid=await tiket();await login(klien,'wahid')
    async with database.SessionLocal() as db:v=service.versi_tiket(await db.get(TimbanganTransaksi,tid))
    body=dict(versi=v,alasan='Lokasi uji',transfer_asal='101',transfer_tujuan='silo:104')
    r=await klien.post(f'/timbangan/transaksi/{tid}/koreksi/pratinjau',data=body)
    assert r.json()['perubahan'][0]['field']=='lintasan_transfer'
    await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=body)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t.lintasan_transfer['tujuan']['silo_id']==104
        assert t.jumlah_revisi==1 and t.berat_barang_kg==3989.42
        audits=(await db.scalars(select(TimbanganAudit).where(TimbanganAudit.aksi=='KOREKSI'))).all();assert len(audits)==1
        v2=service.versi_tiket(t)
    # stale form cannot overwrite, then unchanged valid form creates no revision
    await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data={**body,'transfer_tujuan':'gudang:102'})
    await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data={**body,'versi':v2})
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t.jumlah_revisi==1 and t.lintasan_transfer['tujuan']['silo_id']==104

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_hak_cetak_pemeriksaan_dan_endpoint(klien,role):
    await master();tid=await tiket();who='miftah' if role==P.OPERATOR else 'wahid'
    await tautkan(who,role);await login(klien,who)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        await service.buka_pemeriksaan(db,trx=t,akun=a);await db.commit()
        before=(t.status_kontrol,t.berat_barang_kg,t.total_tara_kg)
    r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert ('Hapus permanen' in r.text)==(role==P.SUPERADMIN)
    assert ('data-tutup-pemeriksaan' in r.text)==P.admin_keatas(role)
    if P.admin_keatas(role):
        for f in ['langkah_ulang_timbang','langkah_hitung_karung','langkah_periksa_tara','langkah_periksa_dokumen','langkah_periksa_muatan','langkah_lapor','dilaporkan_ke','kategori_hasil','catatan_resolusi']:assert f'name="{f}"' in r.text
        await klien.post(f'/timbangan/transaksi/{tid}/periksa',data={'kategori_hasil':'LAIN'})
        async with database.SessionLocal() as db:assert (await service.pemeriksaan_transaksi(db,tid)).status!='SELESAI'
        body=dict(kategori_hasil='LAIN',catatan_resolusi='Resolusi uji',dilaporkan_ke='Pemeriksa Uji')
        await klien.post(f'/timbangan/transaksi/{tid}/periksa',data=body)
        await klien.post(f'/timbangan/transaksi/{tid}/periksa',data={**body,'catatan_resolusi':'JANGAN TIMPA'})
        async with database.SessionLocal() as db:
            p=await service.pemeriksaan_transaksi(db,tid);t=await db.get(TimbanganTransaksi,tid)
            assert p.catatan_resolusi=='Resolusi uji' and (t.status_kontrol,t.berat_barang_kg,t.total_tara_kg)==before
    else:assert (await klien.post(f'/timbangan/transaksi/{tid}/periksa',data={})).status_code==403
    if role!=P.SUPERADMIN:assert (await klien.post(f'/timbangan/transaksi/{tid}/hapus',data={})).status_code==403
    for fmt in ('80mm','ncr','epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/{fmt}');assert r.status_code==200
        text=r.text if fmt=='epos' else '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
        assert 'Miftah' in text if role==P.OPERATOR else 'Wahid' in text
        assert 'selisih' not in text.lower() and 'acuan' not in text.lower()
        if fmt=='epos':assert '8,580 kg' in text and '10,58 kg' not in text
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0

async def test_hapus_permanen_mempertahankan_snapshot_audit(klien):
    import json
    await master();tid=await tiket();await tautkan('wahid',P.SUPERADMIN);await login(klien,'wahid')
    async with database.SessionLocal() as db:kode=(await db.get(TimbanganTransaksi,tid)).kode
    for body in [dict(alasan='Uji',ketik_kode='SALAH'),dict(alasan='',ketik_kode=kode)]:
        await klien.post(f'/timbangan/transaksi/{tid}/hapus',data=body)
        async with database.SessionLocal() as db:assert await db.get(TimbanganTransaksi,tid)
    await klien.post(f'/timbangan/transaksi/{tid}/hapus',data=dict(alasan='Data sintetis selesai diuji',ketik_kode=kode))
    async with database.SessionLocal() as db:
        assert await db.get(TimbanganTransaksi,tid) is None
        a=await db.scalar(select(TimbanganAudit).where(TimbanganAudit.aksi=='HAPUS_TRANSAKSI'))
        assert json.loads(a.nilai_sebelum)['lintasan_transfer']['tujuan']['silo_id']==103

async def test_relasi_produksi_tetap_melindungi_lokasi_dan_pembatalan(klien):
    from sqlalchemy import text
    await master();tid=await tiket(selesai=False);await tautkan('wahid',P.SUPERADMIN);await login(klien,'wahid')
    async with database.SessionLocal() as db:
        await db.execute(text("INSERT INTO purchase_batches(id,timbangan_transaksi_id,kode_batch) VALUES (1,:tid,'UJI-TAUT')"),{'tid':tid});await db.commit()
        t=await db.get(TimbanganTransaksi,tid);v=service.versi_tiket(t);kode=t.kode
    bodies=[('batal',{'alasan':'Uji'}),('hapus',{'alasan':'Uji','ketik_kode':kode}),('koreksi',{'versi':v,'alasan':'Uji','transfer_asal':'101','transfer_tujuan':'silo:104'}),('jenis',{'jenis_kode':'GABAH_BASAH','alasan':'Uji'})]
    for endpoint,body in bodies:
        await klien.post(f'/timbangan/transaksi/{tid}/{endpoint}',data=body)
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid);assert t and t.status_transaksi!='VOID' and t.jenis_kode=='TRANSFER' and t.lintasan_transfer['tujuan']['silo_id']==103

async def test_koreksi_sopir_lama_tanpa_merekayasa_lokasi(klien):
    await master();tid=await tiket(terstruktur=False);await login(klien,'wahid')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);v=service.versi_tiket(t);lama=t.pihak_nama
    r=await klien.get(f'/timbangan/transaksi/{tid}/koreksi');assert 'Catatan lama' in r.text
    await klien.post(f'/timbangan/transaksi/{tid}/koreksi',data=dict(alasan='Sopir uji',versi=v,nama_sopir='Sopir Sunting'))
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t.pihak_nama==lama and t.lintasan_transfer is None and t.nama_sopir=='Sopir Sunting' and t.berat_barang_kg==3989.42

async def test_peran_akun_tertaut_dibaca_ulang_tanpa_hak_cookie_simulasi(klien):
    from app.models import User
    await master();tid=await tiket();await tautkan('wahid',P.SUPERADMIN);await login(klien,'wahid')
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        u=await db.get(User,a.user_id);u.role=P.OPERATOR;await db.commit()
    klien.cookies.set('produksi_lihat','superadmin')
    r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert 'Hapus permanen' not in r.text
    assert (await klien.post(f'/timbangan/transaksi/{tid}/hapus',data={})).status_code==403
    assert (await klien.post(f'/timbangan/transaksi/{tid}/periksa',data={})).status_code==403

async def test_kontrol_historis_tetap_tersedia_tanpa_hitung_ulang(klien):
    await master();tid=await tiket()
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);t.status_kontrol='PERLU_PEMERIKSAAN';t.berat_acuan_kg=4000;t.selisih_kg=-10.58;t.selisih_persen=-.2645;await db.commit()
    await login(klien)
    r=await klien.get(f'/timbangan/transaksi/{tid}?tab=jejak')
    assert 'Nilai kontrol historis tersimpan' in r.text and '-10,58 kg' in r.text
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t.status_kontrol=='PERLU_PEMERIKSAAN' and t.selisih_kg==-10.58 and t.berat_barang_kg==3989.42

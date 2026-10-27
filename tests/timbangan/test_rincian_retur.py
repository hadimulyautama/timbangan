"""Detail retur membaca data tanpa menerima stok; SQLite sementara per kasus."""
from decimal import Decimal
from uuid import uuid4
from copy import deepcopy
from sqlalchemy import select, func, text
import pytest
from test_web import app_uji, klien, login, SANDI
from app import database
from app.models import Pelanggan, User
from hmu_identitas.model import Akun
from hmu_identitas import peran as P
from app.timbangan import service, klien_produksi, rincian_retur
from app.timbangan.models import TimbanganAkun, TimbanganTransaksi, TimbanganAudit, TimbanganCetak

async def tiket(selesai=True, acuan=None):
    async with database.SessionLocal() as db:
        await db.execute(text('CREATE TABLE IF NOT EXISTS customer_returns (id INTEGER PRIMARY KEY,timbangan_transaksi_id INTEGER,kode TEXT)'))
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        p=await db.scalar(select(Pelanggan))
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(
            kunci=str(uuid4()),arah='RETUR_MASUK',jenis_kode='RETUR_PELANGGAN',
            berat_kg=Decimal('6570.1'),nomor_polisi='B 1234 UJ',nama_sopir='Sopir Uji',
            supplier_id=p.id))
        if selesai:
            t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=6500,
                muatan=[service.InputMuatan(jenis_kode='RETUR_PELANGGAN',berat_acuan_kg=acuan or 0,
                    jumlah_karung=2,tara_per_karung_kg=Decimal('.0858'))])
        return t.id

async def tautkan(siapa='wahid',role=P.ADMIN):
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username==siapa))
        u=User(nama=a.nama,role=role,status='aktif');db.add(u);await db.flush()
        shared=Akun(user_id=u.id,username=siapa,password_hash=a.password_hash,status='aktif');db.add(shared);await db.flush()
        a.akun_id=shared.id;a.user_id=u.id;await db.commit()
        return shared.id

def payload(t):
    return dict(tiket_id=t.id,kode_tiket=t.kode,pelanggan_id=t.pelanggan_id,status='diterima_otomatis',
        pengajuan_id=4,asal=dict(id=8,kode='OUT-UJI-8',pelanggan_id=t.pelanggan_id,tiket_id=None,tiket_kode=None,kiriman_id=None),
        muatan=[dict(outgoing_item_id=101,nama='Beras sintetis panjang untuk pengujian tampilan',merek='Merek uji',mutu='Medium',kemasan='Laminasi',ukuran_kg='25',jumlah_karung=2,berat_kg='50',satuan='karung',tara_toleransi_kg='.06',pemilik='Milik pabrik',gudang='Gudang uji',catatan='Uji aman'),dict(outgoing_item_id=102,nama='Broken',jumlah_karung=0,berat_kg='20',satuan='kg',tara_toleransi_kg=None,pemilik='Milik pabrik',gudang='Gudang uji')],
        total_rincian_kg='70',pemeriksaan=dict(status='sesuai',alasan='Bobot sesuai toleransi tara karung.',berat_tiket_kg='70.1',berat_rincian_kg='70',selisih_kg='.1',toleransi_kg='.12'),
        wajib_manual=False,penerimaan=dict(id=4,kode='RET-UJI-4',berat_stok_kg='70'))

async def sumber(monkeypatch,tid,status='diterima_otomatis'):
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);data=payload(t)
    data['status']=status
    if not status.startswith('diterima'):data['penerimaan']=None
    async def baca(tid,aid):return deepcopy(data)
    monkeypatch.setattr(klien_produksi,'detail_retur',baca)
    return data

@pytest.mark.parametrize('status',list(rincian_retur.LABEL)[:-2])
async def test_status_rincian_readonly_dan_tara_tetap_nol(klien,monkeypatch,status):
    tid=await tiket();await tautkan();await sumber(monkeypatch,tid,status)
    await login(klien,'wahid')
    async with database.SessionLocal() as db:
        before=[await db.scalar(select(func.count()).select_from(m)) for m in (TimbanganAudit,TimbanganCetak,TimbanganTransaksi)]
    for tab in ['ringkasan','perhitungan','jejak']:
        r=await klien.get(f'/timbangan/transaksi/{tid}?tab={tab}&kembali=/timbangan/transaksi?hal=2')
        assert r.status_code==200
        assert rincian_retur.LABEL[status] in r.text
        assert '70,10 kg' in r.text and '70,00 kg' in r.text
        assert 'Tara toleransi PadiFlow tidak mengurangi bobot tiket' in r.text
        assert 'Perhitungan retur' in r.text and 'Ringkasan retur' in r.text
        assert 'data-route' not in r.text and 'data-view=' not in r.text
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert Decimal(str(t.berat_barang_kg))==Decimal('70.1') and t.total_tara_kg==0
        assert [await db.scalar(select(func.count()).select_from(m)) for m in (TimbanganAudit,TimbanganCetak,TimbanganTransaksi)]==before

@pytest.mark.parametrize('keadaan',['terbuka','batal','ditutup','gangguan','dilarang','salah-tiket','tanpa-akun'])
async def test_kondisi_akses_dan_kegagalan(klien,monkeypatch,keadaan):
    tid=await tiket(selesai=keadaan not in ('terbuka','ditutup'))
    if keadaan!='tanpa-akun':await tautkan()
    data=await sumber(monkeypatch,tid)
    async def gagal(*a):raise klien_produksi.ProduksiTakTersedia('Uji jaringan')
    async def dilarang(*a):raise klien_produksi.ProduksiDilarang('Uji izin')
    async def salah(*a):return dict(data,tiket_id=tid+1)
    if keadaan in ('gangguan','dilarang','salah-tiket'):monkeypatch.setattr(klien_produksi,'detail_retur',{'gangguan':gagal,'dilarang':dilarang,'salah-tiket':salah}[keadaan])
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        if keadaan=='batal':t.status_transaksi='VOID';t.void_alasan='Alasan uji'
        if keadaan=='ditutup':t.status_tiket='DITUTUP_PAKSA';t.tutup_paksa_alasan='Armada uji pergi'
        await db.commit()
    await login(klien,'wahid');r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert r.status_code==200
    if keadaan in ('terbuka','batal','ditutup'):
        assert 'Hasil akhir belum tersedia' in r.text
        assert 'Cetak bukti timbang' not in r.text
    if keadaan in ('gangguan','dilarang','salah-tiket','tanpa-akun'):
        assert 'RET-UJI-4' not in r.text and '70,10 kg' in r.text
    if keadaan=='terbuka':assert 'Lanjutkan timbang kedua' in r.text

@pytest.mark.parametrize('siapa,role',[('budi',P.OPERATOR),('wahid',P.ADMIN),('wahid',P.SUPERADMIN)])
async def test_izin_tindakan_dan_pdf(klien,monkeypatch,siapa,role):
    tid=await tiket(acuan=50);await tautkan(siapa,role);await sumber(monkeypatch,tid,'perlu_koreksi')
    await login(klien,siapa)
    r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert ('data-tutup-pemeriksaan' in r.text)==P.admin_keatas(role)
    assert ('Hapus permanen' in r.text)==(role == P.SUPERADMIN)
    if P.admin_keatas(role):
        for f in ['langkah_ulang_timbang','langkah_hitung_karung','langkah_periksa_tara','langkah_periksa_dokumen','langkah_periksa_muatan','langkah_lapor','dilaporkan_ke','kategori_hasil','catatan_resolusi']:
            assert f'name="{f}"' in r.text
    else:
        assert (await klien.post(f'/timbangan/transaksi/{tid}/periksa',data={'kategori_hasil':'LAIN','catatan_resolusi':'uji'})).status_code==403
    # Endpoint cetak yang lama tetap menjadi tujuan; preview bukan sukses printer.
    r=await klien.get(f'/timbangan/transaksi/{tid}/cetak');assert r.status_code==200
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0

@pytest.mark.parametrize('keadaan',['TERBUKA','VOID','DITUTUP_PAKSA'])
async def test_seluruh_jalur_cetak_menolak_tiket_tidak_sah(klien,keadaan):
    tid=await tiket(selesai=keadaan=='VOID')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        if keadaan=='VOID':t.status_transaksi='VOID';t.void_alasan='Batal uji'
        elif keadaan=='DITUTUP_PAKSA':t.status_tiket=keadaan;t.tutup_paksa_alasan='Armada uji pergi'
        await db.commit()
    await login(klien)
    for fmt in ('80mm','ncr','epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/{fmt}',follow_redirects=False)
        assert r.status_code==303 and 'err=' in r.headers['location']
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0

@pytest.mark.parametrize('acuan',[None,50])
async def test_dokumen_angka_pencetak_kebijakan_dan_audit(klien,acuan):
    import io
    from pypdf import PdfReader
    tid=await tiket(acuan=acuan);await login(klien,'miftah')
    bukti={}
    for fmt in ('80mm','ncr','epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/{fmt}')
        assert r.status_code==200
        bukti[fmt]=r.text if fmt=='epos' else '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
        assert 'Miftah' in bukti[fmt]
        assert 'PadiFlow' not in bukti[fmt] and 'toleransi' not in bukti[fmt].lower()
    assert 'selisih' not in bukti['ncr'].lower()
    if acuan is None:assert 'selisih' not in bukti['80mm'].lower()
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
    await klien.post(f'/timbangan/transaksi/{tid}/cetak',data={'format':'80MM'})
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==1
    r=await klien.post(f'/timbangan/transaksi/{tid}/cetak',data={'format':'NCR'})
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==1
    await klien.post(f'/timbangan/transaksi/{tid}/cetak',data={'format':'NCR','alasan':'Kertas uji rusak'})
    r=await klien.get(f'/timbangan/transaksi/{tid}?tab=jejak')
    assert 'Kertas uji rusak' in r.text and 'Cetak 2' in r.text

async def test_pemeriksaan_normal_tetap_terbuka_dan_tidak_memicu_padi(klien,monkeypatch):
    tid=await tiket(acuan=50)
    from sqlalchemy import text
    async with database.SessionLocal() as db:
        await db.execute(text('CREATE TABLE IF NOT EXISTS customer_returns (id INTEGER PRIMARY KEY,timbangan_transaksi_id INTEGER,kode TEXT)'));await db.commit()
    async def dilarang(*a):raise AssertionError('Penutupan tidak boleh menerima retur')
    monkeypatch.setattr(klien_produksi,'muatan_retur',dilarang)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        await service.koreksi_transaksi(db,akun=a,trx=t,perubahan={'timbang2_kg':6520.1},alasan='Koreksi sintetis')
        assert t.status_kontrol=='NORMAL'
        assert (await service.pemeriksaan_transaksi(db,tid)).status!='SELESAI'
        before=(t.berat_barang_kg,t.status_kontrol,t.jumlah_revisi)
    await login(klien,'wahid')
    for body in ({},{'kategori_hasil':'LAIN'},{'catatan_resolusi':'Uji'}):
        r=await klien.post(f'/timbangan/transaksi/{tid}/periksa',data=body)
        assert 'Pemeriksaan ditutup.' not in str(r.url)
    body={'kategori_hasil':'LAIN','catatan_resolusi':'Resolusi uji','dilaporkan_ke':'Pemeriksa uji'}
    await klien.post(f'/timbangan/transaksi/{tid}/periksa',data=body)
    await klien.post(f'/timbangan/transaksi/{tid}/periksa',data={**body,'catatan_resolusi':'JANGAN TIMPA'})
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);p=await service.pemeriksaan_transaksi(db,tid)
        assert (t.berat_barang_kg,t.status_kontrol,t.jumlah_revisi)==before
        assert p.status=='SELESAI' and p.catatan_resolusi=='Resolusi uji' and p.ditutup_oleh_id and p.ditutup_pada

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_retur_tertaut_dilindungi_dan_sopir_boleh_dikoreksi(klien,role):
    from sqlalchemy import text
    tid=await tiket();siapa='budi' if role==P.OPERATOR else 'wahid';await tautkan(siapa,role)
    async with database.SessionLocal() as db:
        await db.execute(text('CREATE TABLE IF NOT EXISTS customer_returns (id INTEGER PRIMARY KEY,timbangan_transaksi_id INTEGER,kode TEXT)'))
        await db.execute(text("INSERT INTO customer_returns VALUES (1,:id,'RET-UJI-LINDUNG')"),{'id':tid});await db.commit()
    await login(klien,siapa)
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username==siapa));t=await db.get(TimbanganTransaksi,tid)
        for perubahan in ({'timbang2_kg':6490},{'nomor_polisi':'B 999 UJ'}):
            with pytest.raises(service.LayananError):await service.koreksi_transaksi(db,akun=a,trx=t,perubahan=perubahan,alasan='Uji perlindungan')
        with pytest.raises(service.LayananError):
            await service.koreksi_transaksi(db,akun=a,trx=t,perubahan={},muatan=[service.InputMuatan(jenis_kode='RETUR_PELANGGAN',jumlah_karung=3)],alasan='Uji muatan tertaut')
        await service.koreksi_transaksi(db,akun=a,trx=t,perubahan={'nama_sopir':'Sopir Baru Uji','catatan':'Catatan sah'},alasan='Koreksi identitas sopir')
        assert t.berat_barang_kg==70.1 and t.nama_sopir=='Sopir Baru Uji'
        kode=t.kode
    for aksi,body in [('batal',{'alasan':'Batal uji'}),('hapus',{'alasan':'Hapus uji','ketik_kode':kode})]:
        r=await klien.post(f'/timbangan/transaksi/{tid}/{aksi}',data=body)
        assert r.status_code in (200,403)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t and t.status_transaksi!='VOID'

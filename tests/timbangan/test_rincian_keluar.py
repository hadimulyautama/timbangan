"""Detail keluar: pembacaan terisolasi, snapshot, status bersama dan pagar lama."""
from copy import deepcopy
from decimal import Decimal
import pytest
from sqlalchemy import select, text, func
from test_web import app_uji, klien, login
from test_pengiriman_gabungan import payload, tiket
from app import database
from app.timbangan import service, rincian_keluar, klien_produksi
from app.timbangan.models import TimbanganAkun, TimbanganTransaksi, TimbanganAudit, TimbanganCetak

async def buat_tiket(selesai=True, beda=0, data=None):
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        t=await tiket(db,a)
        if selesai:
            p=data or payload()
            berat=Decimal(5000)+sum(Decimal(str(m['berat_kg']))+Decimal(str(m['tara_per_karung_kg']))*m['jumlah_karung'] for m in p['muatan'])+Decimal(str(beda))
            t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=berat,pengiriman_snapshot=p)
        return t.id

async def tabel_produksi(db, tid, status=('selesai','dimuat'), gabung=True):
    await db.execute(text('CREATE TABLE outgoing_records (id INTEGER PRIMARY KEY, kode TEXT, status TEXT, kiriman_id INTEGER, timbangan_transaksi_id INTEGER)'))
    if gabung:
        await db.execute(text('CREATE TABLE kiriman_keluar (id INTEGER PRIMARY KEY, timbangan_transaksi_id INTEGER)'))
        await db.execute(text('INSERT INTO kiriman_keluar VALUES (3,:tid)'),{'tid':tid})
    for i,s in enumerate(status):
        await db.execute(text('INSERT INTO outgoing_records VALUES (:id,:kode,:status,:kid,:tid)'),dict(id=i+1,kode=f'OUT-UJI-{i}',status=s,kid=3 if gabung else None,tid=None if gabung else tid))
    await db.commit()

@pytest.mark.parametrize('status,kode',[(('selesai','dimuat'),'menunggu'),(('selesai','selesai'),'terverifikasi'),(('selesai','batal'),'terverifikasi'),(('batal','batal'),'belum'),(('perintah','dimuat'),'menunggu')])
async def test_status_semua_anggota_bukan_selesai_muat(app_uji,status,kode):
    tid=await buat_tiket()
    async with database.SessionLocal() as db:
        await tabel_produksi(db,tid,status)
        hasil=await rincian_keluar.status_produksi(db,tid)
        assert hasil['kode']==kode
        assert all(p['status']!='batal' for p in hasil['perintah'])

async def test_legacy_dan_dua_perjalanan_tidak_dianggap_terverifikasi(app_uji):
    tid=await buat_tiket()
    async with database.SessionLocal() as db:
        await tabel_produksi(db,tid,('selesai',),gabung=False)
        assert (await rincian_keluar.status_produksi(db,tid))['kode']=='terverifikasi'
        await db.execute(text('INSERT INTO outgoing_records VALUES (2,\'LAIN\',\'selesai\',NULL,:tid)'),{'tid':tid})
        assert (await rincian_keluar.status_produksi(db,tid))['kode']=='tidak_pasti'

async def test_gangguan_status_tidak_merusak_pembacaan_tiket(app_uji):
    tid=await buat_tiket()
    async with database.SessionLocal() as db:
        await db.execute(text('CREATE TABLE outgoing_records (id INTEGER)'))
        await db.commit()
        assert (await rincian_keluar.status_produksi(db,tid))['kode']=='tidak_pasti'
        assert (await db.get(TimbanganTransaksi,tid)).berat_barang_kg==4000

async def test_get_snapshot_tidak_membaca_ulang_sumber_atau_menulis(klien,monkeypatch):
    tid=await buat_tiket()
    async def terlarang(*args,**kwargs):raise AssertionError('Detail final tidak memanggil sumber/writer')
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',terlarang)
    await login(klien,'miftah')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);snap=deepcopy(t.pengiriman_snapshot)
        hitung=[await db.scalar(select(func.count()).select_from(m)) for m in (TimbanganAudit,TimbanganCetak,TimbanganTransaksi)]
    for tab in ('muatan','perhitungan','jejak'):
        r=await klien.get(f'/timbangan/transaksi/{tid}',params={'tab':tab,'kembali':'/timbangan/transaksi?q=uji&halaman=2'})
        assert r.status_code==200
        assert '2 pelanggan · 4 baris barang' in r.text and '4.000 kg' in r.text
        assert 'q=uji&amp;halaman=2' in r.text
        assert 'Belum ada catatan cetak' in r.text
        assert 'Hapus permanen' not in r.text
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert t.pengiriman_snapshot==snap
        assert [await db.scalar(select(func.count()).select_from(m)) for m in (TimbanganAudit,TimbanganCetak,TimbanganTransaksi)]==hitung

@pytest.mark.parametrize('siapa', ['budi','wahid','super'])
async def test_tindakan_pemeriksaan_dan_akses_peran(klien,siapa):
    tid=await buat_tiket(beda=1000)
    if siapa=='super':
        async with database.SessionLocal() as db:
            a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'));a.role='SUPERADMIN';await db.commit()
        siapa='wahid';superadmin=True
    else:superadmin=False
    await login(klien,siapa)
    r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert r.status_code==200
    assert ('data-tutup-pemeriksaan' in r.text)==(siapa=='wahid')
    assert ('Hapus permanen' in r.text)==superadmin
    assert ('/audit">Buka jejak audit' in r.text)==superadmin
    if siapa=='wahid':
        for n in ('langkah_ulang_timbang','langkah_hitung_karung','langkah_periksa_tara','langkah_periksa_dokumen','langkah_periksa_muatan','langkah_lapor','dilaporkan_ke','kategori_hasil','catatan_resolusi'):
            assert f'name="{n}"' in r.text
    else:
        r=await klien.post(f'/timbangan/transaksi/{tid}/periksa',data={'kategori_hasil':'LAIN','catatan_resolusi':'Uji'})
        assert r.status_code==403
        assert (await klien.post(f'/timbangan/transaksi/{tid}/hapus',data={'alasan':'Uji','ketik_kode':'x'})).status_code==403

@pytest.mark.parametrize('keadaan',['terbuka','gangguan','historis','batal','ditutup'])
async def test_kondisi_tiket(klien,monkeypatch,keadaan):
    tid=await buat_tiket(selesai=keadaan not in ('terbuka','gangguan','ditutup'))
    async def sumber(*args):
        if keadaan=='gangguan':raise klien_produksi.ProduksiTakTersedia('Uji putus')
        return payload()
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',sumber)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        if keadaan=='historis':t.pengiriman_snapshot=None
        if keadaan=='batal':t.status_transaksi='VOID';t.void_alasan='Alasan sintetis'
        if keadaan=='ditutup':t.status_tiket='DITUTUP_PAKSA';t.tutup_paksa_alasan='Armada uji pergi'
        await db.commit()
    await login(klien)
    r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert r.status_code==200
    assert ('Cetak bukti timbang' in r.text)==(keadaan=='historis')
    assert ('Lanjutkan timbang kedua' in r.text)==(keadaan in ('terbuka','gangguan'))
    if keadaan=='terbuka':assert 'belum menjadi snapshot final' in r.text
    if keadaan=='gangguan':assert 'Muatan PadiFlow belum dapat diperiksa' in r.text
    if keadaan=='historis':assert 'Data historis yang tersedia' in r.text and 'Item #101' not in r.text
    else:assert 'Hasil akhir belum tersedia' in r.text

async def test_tara_lain_tidak_digandakan(app_uji):
    tid=await buat_tiket()
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        # Fixture nilai tersimpan: proyeksi hanya memisahkan total dan komponen.
        t.total_tara_kg=Decimal('21.0858');t.tara_lain_kg=Decimal('2.5858')
        d=await rincian_keluar.baca(db,t,None,[])
        assert d['tara_karung']==Decimal('18.5000')
        assert d['total_acuan']==4000
        assert [p['subtotal'] for p in d['kelompok']]==[1500,2500]

async def test_pemeriksaan_normal_tetap_terbuka_tutup_tidak_mengubah_bobot(klien):
    tid=await buat_tiket(beda=1000)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        admin=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        await service.koreksi_transaksi(db,akun=admin,trx=t,perubahan={'timbang2_kg':9018.5},alasan='Koreksi angka uji')
        assert t.status_kontrol=='NORMAL'
        assert (await service.pemeriksaan_transaksi(db,tid)).status!='SELESAI'
        before=(t.berat_barang_kg,t.status_kontrol,t.pengiriman_snapshot,t.jumlah_revisi)
    await login(klien,'wahid')
    html=(await klien.get(f'/timbangan/transaksi/{tid}')).text
    assert 'Angkanya sudah berubah sejak lembar ini dibuka' in html and 'data-tutup-pemeriksaan' in html
    for body in ({'kategori_hasil':'LAIN','catatan_resolusi':''},{'kategori_hasil':'','catatan_resolusi':'Uji'}):
        r=await klien.post(f'/timbangan/transaksi/{tid}/periksa',data=body)
        assert 'Pemeriksaan ditutup.' not in str(r.url)
    body={'kategori_hasil':'LAIN','catatan_resolusi':'Kesimpulan uji asli','langkah_ulang_timbang':'Ulang uji','dilaporkan_ke':'Admin Uji'}
    r=await klien.post(f'/timbangan/transaksi/{tid}/periksa',data=body)
    assert 'Pemeriksaan ditutup.' in str(r.url).replace('+',' ').replace('%20',' ')
    assert 'Ulang uji' in r.text and 'Kesimpulan uji asli' in r.text
    assert 'Langkah pemeriksaan tercatat' in r.text and 'data-tutup-pemeriksaan' not in r.text
    await klien.post(f'/timbangan/transaksi/{tid}/periksa',data={**body,'catatan_resolusi':'JANGAN MENIMPA'})
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        assert (t.berat_barang_kg,t.status_kontrol,t.pengiriman_snapshot,t.jumlah_revisi)==before
        p=await service.pemeriksaan_transaksi(db,tid)
        assert p.status=='SELESAI' and p.catatan_resolusi=='Kesimpulan uji asli'
        assert p.ditutup_oleh_id and p.ditutup_pada and p.dilaporkan_ke=='Admin Uji'

async def test_riwayat_cetak_dan_nilai_batal_tetap_tersedia(klien):
    from app.timbangan.db import sekarang
    tid=await buat_tiket()
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='miftah'))
        for urut,fmt in [(1,'80MM'),(2,'NCR')]:
            db.add(TimbanganCetak(transaksi_id=tid,urutan=urut,format=fmt,oleh_id=a.id,waktu=sekarang(),ulang=urut==2,alasan='Kertas uji rusak' if urut==2 else None,revisi=0))
        t=await db.get(TimbanganTransaksi,tid);t.status_transaksi='VOID';t.void_alasan='Batal uji'
        await db.commit()
    await login(klien)
    r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert 'Nilai historis sebelum pembatalan' in r.text and '4.000 kg' in r.text
    assert 'Cetak 1 · 80MM' in r.text and 'Cetak 2 · NCR' in r.text
    assert 'Kertas uji rusak' in r.text and 'Miftah' in r.text
    assert 'Cetak bukti timbang' not in r.text

async def test_hasil_nol_sah_berbeda_dengan_pembanding_historis_belum_ada(klien):
    tid=await buat_tiket()
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        t.pengiriman_snapshot=None;t.berat_acuan_kg=0;t.status_kontrol='TANPA_KONTROL';t.selisih_kg=0;t.selisih_persen=0;t.berat_barang_kg=0
        await db.commit()
        d=await rincian_keluar.baca(db,t,None,[])
        assert d['acuan'] is None and t.berat_barang_kg==0
    await login(klien)
    r=await klien.get(f'/timbangan/transaksi/{tid}')
    assert '<strong>0 kg</strong>' in r.text
    assert '<span>Total acuan muatan</span><b>Belum tersedia</b>' in r.text
    assert 'Tanpa pembanding; selisih belum tersedia.' in r.text

@pytest.mark.parametrize('keadaan',['TERBUKA','VOID','DITUTUP_PAKSA'])
async def test_semua_jalur_bukti_menolak_tiket_tidak_sah(klien,keadaan):
    tid=await buat_tiket(selesai=keadaan=='VOID')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        if keadaan=='VOID':t.status_transaksi='VOID';t.void_alasan='Batal sintetis'
        elif keadaan=='DITUTUP_PAKSA':t.status_tiket=keadaan;t.tutup_paksa_alasan='Armada sintetis pergi'
        await db.commit()
    await login(klien)
    for format in ('80mm','ncr','epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/{format}',follow_redirects=False)
        assert r.status_code==303 and 'err=' in r.headers['location']
        assert r.headers.get('content-type') not in ('application/pdf','text/xml')
    async with database.SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0

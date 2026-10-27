"""Bukti, versi dan pekerjaan cetak diuji pada SQLite terpisah per kasus."""
import io,re,json,uuid
import pytest
from pypdf import PdfReader
from sqlalchemy import select,func
from test_web import app_uji,klien,login
from test_rincian_supplier import tiket
from test_rincian_retur import tautkan
from hmu_identitas import peran as P
from app import database
from app.timbangan import cetak,pdf,epos,service
from app.timbangan.models import TimbanganCetak,TimbanganTransaksi,TimbanganAkun,TimbanganPekerjaanCetak as Job

async def siapkan(klien,tid,format='80MM',keluaran='printer',alasan=''):
    r=await klien.get(f'/timbangan/transaksi/{tid}/cetak');assert r.status_code==200,r.text
    cap=re.search(r'data-sidik="([^"]+)"',r.text).group(1)
    data=dict(kunci=uuid.uuid4().hex,sidik=cap,format=format,keluaran=keluaran,alasan=alasan)
    r=await klien.post(f'/timbangan/transaksi/{tid}/cetak/pekerjaan',json=data)
    assert r.status_code==200,r.text
    return r.json(),data

async def jumlah():
    async with database.SessionLocal() as db:return await db.scalar(select(func.count()).select_from(TimbanganCetak))

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_pratinjau_dan_dokumen_tidak_mencatat_cetak(klien,role,tmp_path):
    tid=await tiket();await tautkan('miftah',role);await login(klien,'miftah')
    r=await klien.get(f'/timbangan/transaksi/{tid}/cetak');assert r.status_code==200
    assert 'Pratinjau &amp; cetak' in r.text or 'Pratinjau & cetak' in r.text
    for fmt in ('80mm','ncr','epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak/{fmt}');assert r.status_code==200
        if fmt!='epos':
            reader=PdfReader(io.BytesIO(r.content));assert float(reader.pages[0].mediabox.width)==pytest.approx((80 if fmt=='80mm' else 215)*72/25.4,abs=.01)
            assert 'Petugas pencetak' in ''.join(p.extract_text() for p in reader.pages)
            (tmp_path/f'struk-{fmt}.pdf').write_bytes(r.content)
        else:assert '<feed unit="160"/>' in r.text
    assert await jumlah()==0

async def test_pekerjaan_ulang_dan_ack_satu_kali(klien):
    tid=await tiket();await login(klien,'wahid');j,data=await siapkan(klien,tid)
    url=f'/timbangan/transaksi/{tid}/cetak/pekerjaan';base=url+'/'+j['kunci']
    assert (await klien.post(url,json=data)).json()['kunci']==j['kunci']
    assert (await klien.post(base+'/kirim',json={})).status_code==200
    assert (await klien.post(base+'/kirim',json={})).status_code==409
    assert await jumlah()==0
    for _ in range(2):assert (await klien.post(base+'/hasil',json={'hasil':'printer_berhasil'})).json()['status']=='berhasil'
    assert await jumlah()==1
    r=await klien.get(f'/timbangan/transaksi/{tid}/cetak');cap=re.search(r'data-sidik="([^"]+)"',r.text).group(1)
    data.update(kunci=uuid.uuid4().hex,sidik=cap)
    assert (await klien.post(url,json=data)).status_code==409
    data['alasan']='Kertas sintetis perlu salinan';r=await klien.post(url,json=data);assert r.status_code==200
    key=r.json()['kunci'];await klien.post(url+'/'+key+'/kirim',json={})
    await klien.post(url+'/'+key+'/hasil',json={'hasil':'dikonfirmasi'})
    assert await jumlah()==2

@pytest.mark.parametrize('hasil',['gagal','belum_tercetak'])
async def test_gagal_tidak_sukses(klien,hasil):
    tid=await tiket();await login(klien,'wahid');j,_=await siapkan(klien,tid)
    base=f'/timbangan/transaksi/{tid}/cetak/pekerjaan/'+j['kunci']
    await klien.post(base+'/kirim',json={})
    for _ in range(2):assert (await klien.post(base+'/hasil',json={'hasil':hasil})).json()['status']==hasil
    assert await jumlah()==0

async def test_versi_berubah_sebelum_kirim_ditolak(klien):
    tid=await tiket();await login(klien,'wahid');j,_=await siapkan(klien,tid)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);t.jumlah_revisi+=1;t.nama_sopir='Sopir berubah';await db.commit()
    r=await klien.post(f'/timbangan/transaksi/{tid}/cetak/pekerjaan/{j["kunci"]}/kirim',json={})
    assert r.status_code==409 and 'berubah' in r.json()['error']
    assert await jumlah()==0

async def test_revisi_dan_alasan_terkunci_setelah_kirim(klien):
    tid=await tiket();await login(klien,'wahid');j,_=await siapkan(klien,tid)
    base=f'/timbangan/transaksi/{tid}/cetak/pekerjaan/'+j['kunci'];await klien.post(base+'/kirim',json={})
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);t.jumlah_revisi=5;await db.commit()
    r=await klien.post(base+'/hasil',json={'hasil':'dikonfirmasi','alasan':'Tidak boleh mengganti','revisi':5});assert r.status_code==200
    async with database.SessionLocal() as db:
        row=await db.scalar(select(TimbanganCetak));assert row.revisi==0 and row.alasan is None

async def test_ganti_akun_tidak_mengambil_pekerjaan(klien):
    tid=await tiket();await login(klien,'wahid');j,_=await siapkan(klien,tid)
    base=f'/timbangan/transaksi/{tid}/cetak/pekerjaan/'+j['kunci'];await klien.post(base+'/kirim',json={})
    await login(klien,'miftah')
    assert (await klien.post(base+'/hasil',json={'hasil':'dikonfirmasi'})).status_code==409
    assert await jumlah()==0
    await login(klien,'wahid');assert (await klien.post(base+'/hasil',json={'hasil':'dikonfirmasi'})).status_code==200

async def test_pdf_siap_bukan_fisik_dan_ncr_bukan_printer(klien):
    tid=await tiket();await login(klien,'wahid');j,_=await siapkan(klien,tid,'NCR','pdf')
    base=f'/timbangan/transaksi/{tid}/cetak/pekerjaan/'+j['kunci']
    r=await klien.post(base+'/kirim',json={});assert r.headers['content-type']=='application/pdf'
    assert (await klien.get(base+'/berkas')).status_code==200
    assert await jumlah()==0
    assert (await klien.post(base+'/hasil',json={'hasil':'printer_berhasil'})).status_code==409
    assert (await klien.post(base+'/hasil',json={'hasil':'dikonfirmasi'})).status_code==200

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
@pytest.mark.parametrize('status',['TERBUKA','DITUTUP_PAKSA','VOID'])
async def test_semua_url_menolak_bukti_tidak_sah(klien,role,status):
    tid=await tiket();await tautkan('miftah',role);await login(klien,'miftah')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid)
        if status=='VOID':t.status_transaksi=status
        else:t.status_tiket=status
        await db.commit()
    for path in ('','/80mm','/ncr','/epos'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak'+path,follow_redirects=False)
        assert r.status_code in (302,303),r.text
    r=await klien.post(f'/timbangan/transaksi/{tid}/cetak/pekerjaan',json={'kunci':uuid.uuid4().hex,'format':'80MM','keluaran':'printer','sidik':'x'})
    assert r.status_code==409 and await jumlah()==0

async def test_pemeriksaan_terbuka_tidak_melarang_cetak_dan_legacy_tidak_menukar_job(klien):
    tid=await tiket();await login(klien,'wahid')
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        await service.buka_pemeriksaan(db,trx=t,akun=a);await db.commit()
    j,_=await siapkan(klien,tid)
    await klien.post(f'/timbangan/transaksi/{tid}/cetak',data={'format':'NCR','alasan':'Ini dokumen berbeda'})
    assert await jumlah()==0
    base=f'/timbangan/transaksi/{tid}/cetak/pekerjaan/{j["kunci"]}'
    await klien.post(base+'/kirim',json={});await klien.post(base+'/hasil',json={'hasil':'printer_berhasil'})
    async with database.SessionLocal() as db:
        row=await db.scalar(select(TimbanganCetak));assert row.format=='80MM' and row.alasan is None

async def test_sesi_tidak_terautentikasi_dan_format_manipulasi(klien):
    tid=await tiket();url=f'/timbangan/transaksi/{tid}/cetak'
    assert (await klien.get(url,follow_redirects=False)).status_code in (302,303)
    assert (await klien.post(url+'/pekerjaan',json={},follow_redirects=False)).status_code in (302,303)
    await login(klien,'wahid')
    for form,out in [('NCR','printer'),('PALSU','pdf'),('80MM','stok')]:
        r=await klien.post(url+'/pekerjaan',json=dict(kunci=uuid.uuid4().hex,format=form,keluaran=out,sidik='x'))
        assert r.status_code==409
    assert await jumlah()==0

async def test_snapshot_rahasia_mengalahkan_master_terbaru(klien):
    from test_pengiriman_gabungan import tiket as keluar,payload
    from app.timbangan.models import TimbanganJenis
    await login(klien,'wahid')
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        t=await keluar(db,a);t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=9118.5,pengiriman_snapshot=payload());tid=t.id
        # Aturan historis rahasia tetap dipakai meski master dibuka kemudian.
        aturan=await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode=='PENGIRIMAN'));aturan.rahasia=False;await db.commit()
    for path in ('','/epos','/80mm','/ncr'):
        r=await klien.get(f'/timbangan/transaksi/{tid}/cetak'+path);assert r.status_code==200
        text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages) if path in ('/80mm','/ncr') else r.text
        assert 'Penerima Uji 0' in text and 'Penerima Uji 1' in text
        assert 'Subtotal muat' not in text and 'Total acuan' not in text and 'Menurut dokumen' not in text
    assert await jumlah()==0

async def test_akun_sebenarnya_dan_hapus_yang_sah_tetap_bekerja(klien):
    from app.timbangan.models import TimbanganAudit
    tid=await tiket();await tautkan('wahid',P.SUPERADMIN);await login(klien,'wahid')
    klien.cookies.set('produksi_lihat','operator:gudang1')
    j,_=await siapkan(klien,tid);base=f'/timbangan/transaksi/{tid}/cetak/pekerjaan/{j["kunci"]}'
    await klien.post(base+'/kirim',json={});await klien.post(base+'/hasil',json={'hasil':'dikonfirmasi'})
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='wahid'))
        row=await db.scalar(select(TimbanganCetak));job=await db.get(Job,j['kunci']);t=await db.get(TimbanganTransaksi,tid);kode=t.kode
        assert row.oleh_id==a.id and job.oleh_id==a.id and job.nama_pencetak==a.nama
    r=await klien.post(f'/timbangan/transaksi/{tid}/hapus',data={'alasan':'Hapus fixture sintetis','ketik_kode':kode})
    async with database.SessionLocal() as db:
        assert await db.get(TimbanganTransaksi,tid) is None,r.text
        assert await db.get(Job,j['kunci']) is None
        assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit).where(TimbanganAudit.aksi=='HAPUS_TRANSAKSI'))>=1

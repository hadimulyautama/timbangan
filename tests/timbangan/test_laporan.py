"""Regresi laporan melalui endpoint sebenarnya dan DB terisolasi per uji."""
import csv,io,re,html
from datetime import timedelta
from urllib.parse import urlencode
import pytest
from sqlalchemy import select,func
from test_web import app_uji,klien,login,_jadi_super  # noqa: F401
from test_riwayat import snapshot
from data_laporan import isi_laporan
from app import database
from app.timbangan import service,format as fmt
from app.timbangan.db import hari_ini
from app.timbangan.models import TimbanganPemeriksaan,TimbanganTransaksi,TimbanganAudit
from app.timbangan.routes.transaksi import KATEGORI_HASIL
from app.timbangan.web import PREFIX

async def seed(klien):
    ids,s=await isi_laporan(database.SessionLocal);await login(klien,'wahid');return ids,s

def konten(r):return r.text.split('<main class="isi">')[1].split('</main>')[0]
def daftar(teks):return [int(n) for n in re.findall('data-laporan-id="(\\d+)"',teks)]

async def test_rekap_lima_angka_dengan_retur_exclude_bebas_transfer_void(klien):
    ids,_=await seed(klien)
    async with database.SessionLocal() as db:r=await service.ringkasan_dashboard(db,service.FilterTransaksi(dari=hari_ini(),sampai=hari_ini()))
    assert (r.jumlah,r.masuk_kg,r.keluar_kg,r.perlu_periksa,r.tiket_terbuka)==(13,1250,800,4,6)
    teks=konten(await klien.get(PREFIX+'/laporan'))
    for kode,nilai in [('jumlah','13'),('masuk',fmt.ton(1250)),('keluar',fmt.ton(800)),('batas','4'),('terbuka','6')]:
        assert re.search('data-ringkasan="'+kode+'"><strong>'+re.escape(str(nilai)),teks)
    assert set(daftar(teks))=={ids[0],ids[1],ids[3],ids[4]}
    assert 'Pemeriksaan selesai' in teks and 'Sampling tara segera kedaluwarsa' in teks
    assert '/tara' in teks and 'Perbarui sampling' in teks and 'Transfer internal' in teks

async def test_tugas_semua_tanggal_urutan_backend_koreksi_normal(klien):
    ids,_=await seed(klien)
    r=await klien.get(PREFIX+'/laporan',params={'tab':'pemeriksaan','dari':str(hari_ini()),'sampai':str(hari_ini())})
    teks=konten(r);assert daftar(teks)==[ids[0],ids[9],ids[10]]
    assert 'Semua tanggal · daftar ini tidak mengikuti periode rekap.' in teks and 'Kontrol: NORMAL' in teks
    assert '#pemeriksaan' in teks and 'kembali=' in teks and 'Pemeriksaan selesai' not in teks
    assert str(hari_ini()-timedelta(days=60)) not in teks  # formatted local instead

@pytest.mark.parametrize('role',['budi','miftah','wahid','super'])
async def test_peran_url_langsung(klien,app_uji,role):
    ids,_=await isi_laporan(database.SessionLocal)
    if role=='super':await _jadi_super(app_uji)
    await login(klien,'wahid' if role=='super' else role)
    for jalur in ['/laporan','/laporan?tab=pemeriksaan','/laporan?tab=pemantauan','/monitoring','/ekspor.csv']:
        assert (await klien.get(PREFIX+jalur)).status_code==(200 if role in ('wahid','super') else 403)
    assert (await klien.get(PREFIX+f'/transaksi/{ids[0]}')).status_code==200
    if role in ('budi','miftah'):
        assert (await klien.post(PREFIX+f'/transaksi/{ids[0]}/periksa',data={'kategori_hasil':'SALAH_CATAT','catatan_resolusi':'Tidak berhak'})).status_code==403

async def test_alias_periode_kembali_dan_tanggal_lama(klien):
    ids,_=await seed(klien);q={'dari':str(hari_ini()-timedelta(days=80)),'sampai':str(hari_ini()-timedelta(days=40))}
    for route,tab in [('/laporan','rekap'),('/monitoring','pemantauan')]:
        teks=konten(await klien.get(PREFIX+route,params=q));assert f'name="tab" value="{tab}"' in teks
        for t in ['rekap','pemeriksaan','pemantauan']:assert html.escape(urlencode({'tab':t,**q})) in teks
    back=PREFIX+'/laporan?'+urlencode({'tab':'pemeriksaan',**q})
    detail=await klien.get(PREFIX+f'/transaksi/{ids[9]}',params={'kembali':back})
    assert 'href="'+html.escape(back,quote=True)+'" aria-label="Kembali"' in detail.text
    r=await klien.get(PREFIX+'/laporan?dari=x');assert f'name="dari" value="{hari_ini()-timedelta(days=30)}"' in r.text
    r=await klien.get(PREFIX+'/laporan?dari=2099-12-31&sampai=2000-01-01');assert not daftar(konten(r))
    # Sampling uses today, not an old/reversed recap period.
    assert 'Sampling tara segera kedaluwarsa' in r.text

async def test_monitoring_backend_tanpa_penerapan_status_dan_get_tanpa_mutasi(klien):
    ids,s=await seed(klien)
    async with database.SessionLocal() as db:rs=await service.monitoring_supplier(db,service.FilterTransaksi(dari=hari_ini()-timedelta(days=30),sampai=hari_ini()))
    assert len(rs)==2 and {r.supplier_id for r in rs}==set(s[:2])
    assert next(r for r in rs if r.supplier_id==s[1]).skor is None
    before=await snapshot()
    for path in ['/laporan','/laporan?tab=pemeriksaan','/laporan?tab=pemantauan','/monitoring','/ekspor.csv']:
        r=await klien.get(PREFIX+path);assert r.status_code==200
    assert await snapshot()==before
    teks=konten(await klien.get(PREFIX+'/monitoring'))
    for r in rs:
        assert f'data-pihak-id="{r.supplier_id}"' in teks and f'data-pihak-kartu="{r.supplier_id}"' in teks
        assert r.status_saat_ini in teks and r.status_disarankan in teks
        if r.skor:assert fmt.angka(r.skor.skor_total,1) in teks and fmt.angka(r.skor.rata_selisih_kg,1) in teks
        for p in r.pola:assert p.judul in teks and p.keterangan in teks
    assert 'bukan bahwa pihaknya berbuat' in teks and 'Status' in teks

@pytest.mark.parametrize('kategori',list(KATEGORI_HASIL))
async def test_tutup_kategori_opsional_audit_angka_tetap_tidak_bisa_ditimpa(klien,kategori):
    ids,_=await seed(klien);before=await snapshot()
    r=await klien.post(PREFIX+f'/transaksi/{ids[0]}/periksa',data={'kategori_hasil':kategori,'catatan_resolusi':'  Catatan sintetis  ','dilaporkan_ke':'Miftah','langkah_periksa_dokumen':'Dokumen sesuai'})
    assert 'Pemeriksaan ditutup.' in r.text
    async with database.SessionLocal() as db:
        l=await service.pemeriksaan_transaksi(db,ids[0]);record=(l.kategori_hasil,l.catatan_resolusi,l.ditutup_oleh_id,l.ditutup_pada)
        assert l.status=='SELESAI' and record[:2]==(kategori,'Catatan sintetis') and l.dilaporkan_ke=='Miftah' and l.dilaporkan_pada
        assert l.langkah_ulang_timbang is None and l.langkah_periksa_dokumen=='Dokumen sesuai'
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit).where(TimbanganAudit.aksi=='PEMERIKSAAN_SELESAI'))==1
    after=await snapshot();assert after['timbangan_transaksi']==before['timbangan_transaksi'] and after['proses_terpadu']==before['proses_terpadu']
    r=await klien.post(PREFIX+f'/transaksi/{ids[0]}/periksa',data={'kategori_hasil':'LAIN','catatan_resolusi':'Timpa'})
    assert 'sudah ditutup' in r.text
    async with database.SessionLocal() as db:
        l=await service.pemeriksaan_transaksi(db,ids[0]);assert (l.kategori_hasil,l.catatan_resolusi,l.ditutup_oleh_id,l.ditutup_pada)==record
    teks=konten(await klien.get(PREFIX+'/laporan?tab=pemeriksaan'));assert daftar(teks)==[ids[9],ids[10]]
    assert ids[0] in daftar(konten(await klien.get(PREFIX+'/laporan')))

@pytest.mark.parametrize('data',[{}, {'kategori_hasil':'SALAH_CATAT','catatan_resolusi':'   '},{'kategori_hasil':'','catatan_resolusi':'Uji'}])
async def test_validasi_wajib_tanpa_penutupan(klien,data):
    ids,_=await seed(klien)
    await klien.post(PREFIX+f'/transaksi/{ids[0]}/periksa',data=data)
    async with database.SessionLocal() as db:assert (await service.pemeriksaan_transaksi(db,ids[0])).status=='DIBUKA'

async def test_csv_asli_periode_bukan_tab_formula_dan_kosong(klien):
    ids,_=await seed(klien)
    r=await klien.get(PREFIX+'/ekspor.csv',params={'tab':'pemeriksaan','dari':str(hari_ini()),'sampai':str(hari_ini())})
    rows=list(csv.DictReader(io.StringIO(r.text)));assert len(rows)==13
    assert 'UJL-006' not in {r['kode'] for r in rows} and 'UJL-009' not in {r['kode'] for r in rows}
    assert next(r for r in rows if r['kode']=='UJL-003')['pihak']=="'=Pihak Sintetis"
    assert len(rows[0])==21 and 'attachment; filename="timbangan-' in r.headers['content-disposition']
    r=await klien.get(PREFIX+'/monitoring?dari=1999-01-01&sampai=1999-01-02');assert 'Belum cukup transaksi' in r.text

async def test_pola_dan_keterangan_backend_tersedia_di_tabel_dan_kartu(klien):
    ids,s=await seed(klien)
    from app.timbangan.db import sekarang
    async with database.SessionLocal() as db:
        sumber=await db.get(TimbanganTransaksi,ids[0])
        for i in range(4):
            db.add(TimbanganTransaksi(kode=f'UJL-POLA-{i}',tanggal=hari_ini()-timedelta(days=i+1),arah='MASUK',jenis_kode='GABAH_BASAH',supplier_id=s[0],nomor_polisi='W 123 UJ',timbang1_kg=1500,timbang1_waktu=sekarang(),timbang1_petugas_id=sumber.timbang1_petugas_id,berat_barang_kg=1000,berat_acuan_kg=1040,selisih_kg=-40-i,selisih_persen=-4,batas_bawah_kg=-20,batas_atas_kg=20,status_kontrol='PERLU_PEMERIKSAAN',status_tiket='SELESAI'))
        await db.commit()
        rs=await service.monitoring_supplier(db,service.FilterTransaksi(dari=hari_ini()-timedelta(days=30),sampai=hari_ini()))
        r=next(r for r in rs if r.supplier_id==s[0]);assert r.pola
    teks=konten(await klien.get(PREFIX+'/laporan?tab=pemantauan'))
    assert teks.index(f'data-pihak-id="{rs[0].supplier_id}"')<teks.index(f'data-pihak-id="{rs[1].supplier_id}"')
    for p in r.pola:assert teks.count(p.judul)==2 and teks.count(p.keterangan)==2
    assert fmt.angka(r.skor.skor_total,1) in teks

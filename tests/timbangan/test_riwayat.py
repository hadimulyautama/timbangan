"""Kontrak Riwayat: hasil server, angka tersimpan, konteks dan otorisasi."""
import csv
import html
import io
import re
from datetime import timedelta
from urllib.parse import parse_qs,urlsplit

import pytest
from sqlalchemy import select

from test_web import app_uji,klien,login,_jadi_super  # noqa: F401
from data_riwayat import isi_riwayat
from app import database
from app.timbangan.db import hari_ini,sekarang
from app.timbangan.models import TimbanganTransaksi,TimbanganJenis,TimbanganAkun
from app.timbangan.web import PREFIX


def ids(teks):return [int(x) for x in re.findall(r'data-riwayat-id="(\d+)"',teks)]
def main(teks):return teks.split('<main class="isi">')[1].split('</main>')[0]
def url(teks,rel):return html.unescape(re.search(r'rel="'+rel+r'" href="([^"]+)"',teks)[1])
def row(teks,tid):return re.search(r'<tr class="rh-item" data-riwayat-id="'+str(tid)+r'".*?</tr>',teks,re.S)[0]


async def test_dua_minggu_semua_petugas_semua_status_dan_paginasi_server(klien):
    semua=await isi_riwayat(database.SessionLocal)
    async with database.SessionLocal() as db:
        lama=await db.get(TimbanganTransaksi,semua[-1]);lama.tanggal=hari_ini()-timedelta(days=14)
        await db.commit()
    await login(klien)
    first=(await klien.get(PREFIX+'/transaksi')).text
    assert 'Riwayat Timbang' in first and '63 transaksi' in first
    assert f'name="dari" value="{hari_ini()-timedelta(days=13)}"' in first
    assert 'value=""' in first and first.count('data-riwayat-id=')==50
    second=(await klien.get(url(first,'next'))).text
    assert len(ids(second))==13
    assert len(set(ids(first)+ids(second)))==63
    assert semua[-1] not in ids(first)+ids(second)
    # Satu hari lebih baru mendahului id yang lebih besar dari kemarin.
    assert ids(first)==list(reversed(semua[:56]))[:50]
    assert 'Batal' in row(second,semua[4])
    for i in (0,2,7,8,9):assert semua[i] in ids(first)+ids(second)


@pytest.mark.parametrize('cari',['W 1000 UJ','UJR-0000','Pihak Sintetis 0','Sopir Regresi 0'])
async def test_pencarian_seluruh_cakupan_lama_di_server(klien,cari):
    semua=await isi_riwayat(database.SessionLocal)
    await login(klien)
    r=await klien.get(PREFIX+'/transaksi',params={'cari':cari})
    assert ids(r.text)==[semua[0]] and '1 transaksi' in r.text


async def test_kombinasi_filter_retur_master_dan_status(klien):
    semua=await isi_riwayat(database.SessionLocal)
    async with database.SessionLocal() as db:
        j=await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode=='GABAH_KERING'))
        # Master bukan proyeksi hasil. Beras PK tidak mempunyai transaksi benih.
        j.nama='Komoditas master sintetis'
        await db.commit()
    await login(klien)
    r=await klien.get(PREFIX+'/transaksi',params={'arah':'RETUR'})
    expected=[semua[i] for i in range(64) if i%7 in (3,4)]
    assert set(ids(r.text))==set(expected)
    assert {semua[3],semua[4]}<=set(ids(r.text))
    assert 'Komoditas master sintetis' in r.text and 'Beras PK' in r.text
    for status in ('NORMAL','PERLU_PEMERIKSAAN','INVESTIGASI','KURANG','KELEBIHAN','TANPA_KONTROL'):
        assert f'value="{status}"' in r.text
    r=await klien.get(PREFIX+'/transaksi',params={'arah':'RETUR','jenis':'RETUR_PELANGGAN','status':'KURANG','cari':'Pihak Sintetis 3','tiket':'SELESAI'})
    assert ids(r.text)==[semua[3]] and 'Filter (4)' in r.text


async def test_paginasi_membawa_semua_filter_dan_kembali_bukan_redirect_luar(klien):
    semua=await isi_riwayat(database.SessionLocal)
    async with database.SessionLocal() as db:
        rows=(await db.scalars(select(TimbanganTransaksi))).all()
        for t in rows:t.arah='MASUK';t.jenis_kode='GABAH_BASAH';t.status_kontrol='NORMAL';t.status_tiket='SELESAI'
        await db.commit()
    await login(klien)
    q={'cari':'Sintetis','arah':'MASUK','jenis':'GABAH_BASAH','status':'NORMAL','tiket':'SELESAI','dari':str(hari_ini()-timedelta(days=7)),'sampai':str(hari_ini())}
    first=(await klien.get(PREFIX+'/transaksi',params=q)).text
    next_url=url(first,'next');p=parse_qs(urlsplit(next_url).query)
    assert all(p[k]==[v] for k,v in q.items()) and p['hal']==['2']
    second=(await klien.get(next_url)).text;assert len(ids(second))==14
    target=html.unescape(re.search(r'class="rh-open" href="([^"]+)"',second)[1])
    back=parse_qs(urlsplit(target).query)['kembali'][0]
    assert parse_qs(urlsplit(back).query)['hal']==['2']
    detail=(await klien.get(target)).text
    assert f'href="{html.escape(back,quote=True)}" aria-label="Kembali"' in detail
    r=await klien.get(PREFIX+f'/transaksi/{semua[0]}?kembali=https://example.test/')
    assert 'href="https://example.test/" aria-label="Kembali"' not in r.text
    reset=(await klien.get(PREFIX+'/transaksi?hal=1')).text
    assert len(ids(reset))==50


async def test_angka_dan_status_tersimpan_tidak_dijadikan_tugas_palsu(klien):
    semua=await isi_riwayat(database.SessionLocal,12)
    await login(klien)
    teks=(await klien.get(PREFIX+'/transaksi')).text
    assert 'Belum tersedia' in row(teks,semua[0])
    assert '<strong>0<span' in row(teks,semua[9])
    assert '28,023' in row(teks,semua[7]) and 'Sementara' in row(teks,semua[7])
    assert 'Sementara' not in row(teks,semua[8]) and '2 kali timbang' in row(teks,semua[8])
    warning=row(teks,semua[1]);assert 'Selesai' in warning and 'PERLU PEMERIKSAAN' in warning and 'Pemeriksaan selesai' in warning
    assert 'Pemeriksaan dibuka' not in warning and '-48,5 kg' in warning
    assert 'Pemeriksaan dibuka' in row(teks,semua[3])
    assert '+12,5 kg' in row(teks,semua[8])
    assert 'Ditutup tanpa timbang kedua' in row(teks,semua[2])
    assert 'Titipan jasa giling' in row(teks,semua[6])


async def test_tindakan_hanya_yang_sah_dan_csv_tetap_periode(klien,app_uji):
    semua=await isi_riwayat(database.SessionLocal,12)
    await login(klien)
    teks=(await klien.get(PREFIX+'/transaksi')).text
    assert 'CSV periode' not in main(teks) and 'Hapus massal' not in main(teks)
    for i in (0,2,4,7):assert '>Cetak<' not in row(teks,semua[i])
    assert '/tiket/' in row(teks,semua[0]) and '/partai/' in row(teks,semua[7])
    assert '>Cetak<' in row(teks,semua[1])
    for i in (1,8):
        r=await klien.get(PREFIX+f'/transaksi/{semua[i]}/cetak')
        assert r.status_code==200 and '215 × 165 mm' in r.text
    assert (await klien.get(PREFIX+'/ekspor.csv')).status_code==403
    await klien.post(PREFIX+'/keluar');await login(klien,'wahid')
    teks=(await klien.get(PREFIX+'/transaksi?cari=tidak-ada')).text
    assert 'CSV periode' in main(teks) and 'tidak membatasi CSV' in main(teks)
    r=await klien.get(PREFIX+'/ekspor.csv',params={'dari':str(hari_ini()),'sampai':str(hari_ini()),'cari':'tidak-ada','arah':'RETUR','status':'NORMAL'})
    lines=list(csv.DictReader(io.StringIO(r.text)))
    assert len(lines)==11 and 'UJR-0004' not in {r['kode'] for r in lines}
    assert 'UJR-0000' in {r['kode'] for r in lines}
    await _jadi_super(app_uji);await klien.post(PREFIX+'/keluar');await login(klien,'wahid')
    teks=(await klien.get(PREFIX+'/transaksi')).text
    assert teks.count('data-baris-pilih ')==12 and 'Hapus massal' in teks


async def test_kosong_dan_tanggal_atau_halaman_tidak_sah(klien):
    await login(klien)
    assert 'Belum ada transaksi' in (await klien.get(PREFIX+'/transaksi')).text
    await isi_riwayat(database.SessionLocal,1)
    r=await klien.get(PREFIX+'/transaksi?cari=tidakada')
    assert 'Tidak ada transaksi yang cocok' in r.text and 'Belum ada transaksi' not in r.text
    for hal in ('x','-3','9999999999999'):
        assert len(ids((await klien.get(PREFIX+'/transaksi',params={'hal':hal})).text))==1
    r=await klien.get(PREFIX+'/transaksi?dari=bukan-tanggal&sampai=2026-10-24')
    assert r.status_code==200 and len(ids(r.text))==1
    r=await klien.get(PREFIX+'/transaksi?dari=2026-12-31&sampai=2026-01-01')
    assert r.status_code==200 and not ids(r.text)


async def snapshot():
    from app.database import Base
    async with database.SessionLocal() as db:
        hasil={}
        for nama in ['timbangan_transaksi','timbangan_penimbangan','timbangan_pemeriksaan','timbangan_cetak','timbangan_audit','proses_terpadu']:
            tabel=Base.metadata.tables[nama]
            hasil[nama]=[tuple(r) for r in (await db.execute(select(tabel))).all()]
        return hasil


async def test_membaca_riwayat_detail_dan_pemilih_cetak_tidak_memutasi(klien):
    semua=await isi_riwayat(database.SessionLocal,12)
    await login(klien);before=await snapshot()
    assert (await klien.get(PREFIX+'/transaksi')).status_code==200
    for i in range(12):assert (await klien.get(PREFIX+f'/transaksi/{semua[i]}')).status_code==200
    assert (await klien.get(PREFIX+f'/transaksi/{semua[1]}/cetak')).status_code==200
    assert await snapshot()==before


async def test_hapus_massal_sebagian_tetap_melindungi_tautan_produksi_dan_audit(klien,app_uji):
    from app.models import PurchaseBatch
    from app.timbangan.models import TimbanganAudit
    semua=await isi_riwayat(database.SessionLocal,3)
    async with database.SessionLocal() as db:
        db.add(PurchaseBatch(timbangan_transaksi_id=semua[1],kode_batch='GB-UJI-TERLINDUNGI'))
        await db.commit()
    await _jadi_super(app_uji);await login(klien,'wahid')
    r=await klien.post(PREFIX+'/transaksi/hapus-massal',data={
        'transaksi_id':[str(semua[0]),str(semua[1])],'alasan':'Catatan sintetis uji halaman','konfirmasi':'2'})
    assert '1 catatan dihapus permanen.' in r.text and '1 dilewati' in r.text
    assert 'GB-UJI-TERLINDUNGI' in r.text
    async with database.SessionLocal() as db:
        assert await db.get(TimbanganTransaksi,semua[0]) is None
        assert await db.get(TimbanganTransaksi,semua[1]) is not None
        assert await db.get(TimbanganTransaksi,semua[2]) is not None
        audit=(await db.scalars(select(TimbanganAudit).where(TimbanganAudit.aksi=='HAPUS_TRANSAKSI'))).all()
        assert len(audit)==1 and 'Catatan sintetis uji halaman' in audit[0].ringkasan
        assert 'timbang1_kg' in audit[0].nilai_sebelum


async def test_csv_menjaga_format_jam_lokal_dan_menjinakkan_isi_sel(klien):
    semua=await isi_riwayat(database.SessionLocal,1)
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,semua[0]);t.pihak_nama='=2+2'
        t.timbang1_waktu=sekarang().replace(hour=23,minute=14)
        await db.commit()
    await login(klien,'wahid')
    r=await klien.get(PREFIX+'/ekspor.csv',params={'dari':str(hari_ini()),'sampai':str(hari_ini())})
    line=list(csv.DictReader(io.StringIO(r.text)))[0]
    assert line['pihak']=="'=2+2" and line['jam1']=='23:14'
    assert line['timbang1_kg']=='15000'
    assert set(line)=={'kode','tanggal','arah','komoditas','pihak','nomor_polisi','timbang1_kg','jam1','timbang2_kg','jam2','netto_timbangan_kg','jumlah_karung','total_tara_kg','berat_barang_kg','berat_acuan_kg','selisih_kg','selisih_persen','status_kontrol','status_tiket','status_transaksi','revisi'}


async def test_nama_master_pemasok_dan_pelanggan_tanpa_snapshot_tetap_dapat_dicari(klien):
    from app.models import Supplier,Pelanggan
    semua=await isi_riwayat(database.SessionLocal,3)
    async with database.SessionLocal() as db:
        s=await db.scalar(select(Supplier));p=await db.scalar(select(Pelanggan))
        a=await db.get(TimbanganTransaksi,semua[0]);a.supplier_id=s.id;a.pihak_nama=None
        b=await db.get(TimbanganTransaksi,semua[1]);b.pelanggan_id=p.id;b.pihak_nama=None
        await db.commit()
    await login(klien)
    for nama,tid in [('H. Anton',semua[0]),('Toko Uji',semua[1])]:
        r=await klien.get(PREFIX+'/transaksi',params={'cari':nama})
        assert ids(r.text)==[tid] and '1 transaksi' in r.text

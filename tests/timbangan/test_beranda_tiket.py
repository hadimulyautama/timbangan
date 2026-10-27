"""Regresi antrean: seluruh data, urutan waktu, pengelompokan dan akses lama."""
from datetime import timedelta
import re

from sqlalchemy import select

from test_web import app_uji, klien, login  # noqa: F401
from app import database
from app.timbangan import service
from app.timbangan.db import sekarang
from app.timbangan.models import (
    CARA_PARTAI, TIKET_DITUTUP_PAKSA, TIKET_SELESAI, TRX_VOID,
    TimbanganAkun, TimbanganJenis, TimbanganPenimbangan, TimbanganTransaksi,
)
from app.timbangan.web import PREFIX


async def benih(jumlah=3, partai=1):
    """Data sintetis langsung untuk keadaan antrean; alur tulis diuji suite lama."""
    async with database.SessionLocal() as db:
        akun = await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username == 'miftah'))
        waktu = sekarang()
        for i in range(jumlah + partai):
            is_partai = i >= jumlah
            t = TimbanganTransaksi(
                kode=f'UJI-{i:04}', tanggal=waktu.date(), arah='MASUK',
                jenis_kode='GABAH_KERING', timbang1_kg=12.345 if is_partai else 15000,
                timbang1_waktu=waktu-timedelta(hours=i+1),
                timbang1_waktu_sistem=waktu-timedelta(hours=i+1),
                timbang1_petugas_id=akun.id, pihak_nama=f'Pihak Uji {i}',
                nomor_polisi=None if is_partai else f'W {1000+i} UI',
                **({'cara_timbang': CARA_PARTAI} if is_partai else {}),
            )
            db.add(t)
            await db.flush()
            if is_partai:
                db.add(TimbanganPenimbangan(transaksi_id=t.id, berat_kg=12.345,
                                            petugas_id=akun.id))
        await db.commit()


def isi_main(teks):
    return teks.split('<main class="isi">')[1].split('</main>')[0]


async def test_seluruh_antrean_lebih_dari_200_dapat_dicari_dan_dihalaman(klien):
    await benih(205, 2)
    await login(klien)
    home = isi_main((await klien.get(PREFIX+'/')).text)
    assert '<strong>205</strong> Truk' in home
    assert '<strong>2</strong> Partai kecil' in home
    assert home.index('UJI-0204') < home.index('UJI-0203')
    # Yang paling lama tidak hilang di luar potongan 200 terbaru.
    first = isi_main((await klien.get(PREFIX+'/tiket')).text)
    assert 'Truk (205)' in first and 'Partai kecil (2)' in first
    assert first.count('class="tf-ticket"') == 40
    assert first.index('UJI-0204') < first.index('UJI-0203')
    seen = []
    for page in range(1,7):
        html = isi_main((await klien.get(PREFIX+f'/tiket?halaman={page}')).text)
        seen += re.findall(r'class="tf-ticket-name">W (\d+) UI', html)
    assert len(seen) == len(set(seen)) == 205
    for cari in ('W1204UI', 'Pihak Uji 204', 'UJI-0204'):
        r = await klien.get(PREFIX+'/tiket', params={'q':cari})
        assert '1 dari 205 truk' in r.text and 'UJI-0204' in isi_main(r.text)
    part = isi_main((await klien.get(PREFIX+'/tiket?tab=partai&q=UJI-0206')).text)
    assert '1 dari 2 partai kecil' in part
    assert '12,345 kg sementara' in part and '>Lama<' not in part
    assert '/partai/' in part and '>Lanjutkan partai' in part


async def test_ringkasan_tetap_memuat_partai_tanpa_truk(klien):
    await benih(0, 2)
    await login(klien)
    home = isi_main((await klien.get(PREFIX+'/')).text)
    assert 'Tidak ada truk menunggu' in home and 'Partai masih berjalan' in home
    assert '<strong>2</strong> Partai kecil' in home
    assert 'UJI-0001' in home and '12,345 kg sementara' in home
    assert 'Lihat semua partai' in home


async def test_pencarian_sql_tetap_harfiah_dan_mencari_nama_master(klien):
    await benih(4, 0)
    async with database.SessionLocal() as db:
        rows = list((await db.scalars(select(TimbanganTransaksi).order_by(TimbanganTransaksi.id))).all())
        rows[0].pihak_nama = 'Pihak %_\\ Sintetis'
        rows[1].pihak_nama = None
        rows[1].supplier_id = 1
        await db.commit()
    await login(klien)
    for cari, kode in [('%', 'UJI-0000'), ('_', 'UJI-0000'), ('\\', 'UJI-0000'), ('anton', 'UJI-0001')]:
        r = await klien.get(PREFIX+'/tiket', params={'q': cari})
        assert '1 dari 4 truk' in r.text
        assert kode in isi_main(r.text)


async def test_tanggal_transaksi_tidak_mengalahkan_waktu_timbang(klien):
    await benih(3, 0)
    async with database.SessionLocal() as db:
        rows = list((await db.scalars(select(TimbanganTransaksi).order_by(TimbanganTransaksi.id))).all())
        # Waktu sama ditentukan id, tanggal transaksi bukan urutan antrean.
        for r in rows: r.timbang1_waktu = sekarang()-timedelta(days=2)
        rows[1].timbang1_waktu = rows[0].timbang1_waktu
        rows[2].timbang1_waktu = rows[0].timbang1_waktu-timedelta(days=1)
        rows[2].tanggal = sekarang().date()+timedelta(days=1)
        await db.commit()
    await login(klien)
    html = isi_main((await klien.get(PREFIX+'/tiket')).text)
    assert html.index('UJI-0002') < html.index('UJI-0000') < html.index('UJI-0001')


async def test_filter_kegiatan_status_dan_kondisi_kosong(klien):
    await benih(7, 1)
    async with database.SessionLocal() as db:
        rows = list((await db.scalars(select(TimbanganTransaksi).order_by(TimbanganTransaksi.id))).all())
        rows[0].jasa = True
        rows[1].arah = 'RETUR_MASUK'
        rows[2].arah = 'RETUR_KELUAR'
        rows[3].status_tiket = TIKET_SELESAI
        rows[4].status_transaksi = TRX_VOID
        rows[5].status_tiket = TIKET_DITUTUP_PAKSA
        await db.commit()
    await login(klien)
    html = isi_main((await klien.get(PREFIX+'/tiket?kegiatan=JASA')).text)
    assert '1 dari 4 truk' in html and 'UJI-0000' in html
    assert 'Titipan jasa giling' in html
    for arah,i in [('RETUR_MASUK',1), ('RETUR_KELUAR',2)]:
        r = await klien.get(PREFIX+'/tiket', params={'kegiatan':arah})
        assert f'UJI-{i:04}' in isi_main(r.text) and '1 dari 4 truk' in r.text
    assert 'Tidak ada tiket yang cocok' in (await klien.get(PREFIX+'/tiket?q=tidakada')).text
    html = isi_main((await klien.get(PREFIX+'/tiket')).text)
    for i in (3,4,5): assert f'UJI-{i:04}' not in html
    for i in (3,5):
        assert f'data-riwayat-id="{i+1}"' in (await klien.get(PREFIX+'/transaksi')).text
    assert 'data-riwayat-id="5"' in (await klien.get(PREFIX+'/transaksi')).text


async def test_master_aktif_jasa_dan_semua_pintu_lama(klien):
    await login(klien)
    async with database.SessionLocal() as db:
        j = await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode == 'GABAH_KERING'))
        j.nama = 'Komoditas Uji Baru'
        j.urutan = -10
        nonaktif = await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode == 'BERAS_PK'))
        nonaktif.status = 'nonaktif'
        no_jasa = await db.scalar(select(TimbanganJenis).where(TimbanganJenis.kode == 'GABAH_BASAH'))
        no_jasa.boleh_jasa = False
        await db.commit()
    html = isi_main((await klien.get(PREFIX+'/')).text)
    assert 'Komoditas Uji Baru' in html
    assert PREFIX+'/jasa/GABAH_BASAH' not in html
    assert PREFIX+'/timbang/BERAS_PK' not in html
    for path in ('/timbang/GABAH_KERING','/jasa/GABAH_KERING','/partai/GABAH_KERING/baru',
                 '/timbang/PENGIRIMAN','/timbang/TRANSFER','/timbang/RETUR_PELANGGAN',
                 '/timbang/RETUR_SUPPLIER','/timbang/BEBAS','/aturan'):
        assert PREFIX+path in html
        assert (await klien.get(PREFIX+path)).status_code == 200
    assert 'Titipan jasa giling' in html and 'Jasa timbang' in html


async def test_navigasi_mengikuti_peran_dan_jumlah(klien):
    await benih(2,1)
    for siapa,admin in [('budi',False),('wahid',True)]:
        await login(klien,siapa)
        html = (await klien.get(PREFIX+'/')).text
        assert 'Tiket Aktif' in html and 'Navigasi bawah' in html
        assert ('Laporan &amp; Pemeriksaan' in html) == admin
        assert 'bawah__tanda">3<' in html
        assert PREFIX+'/pengaturan' in html
        assert (await klien.get(PREFIX+'/laporan')).status_code == (200 if admin else 403)
        await klien.post(PREFIX+'/keluar')


async def test_bobot_partai_besar_tidak_kehilangan_desimal(klien):
    await benih(0, 1)
    async with database.SessionLocal() as db:
        t = await db.scalar(select(TimbanganTransaksi))
        t.timbang1_kg = 12345.678
        await db.commit()
    await login(klien)
    assert '12.345,678 kg sementara' in (await klien.get(PREFIX+'/tiket?tab=partai')).text
    assert '12.345,678 kg sementara' in (await klien.get(PREFIX+'/')).text


async def test_lama_mengikuti_setelan_sistem_dan_bukan_umur_partai(klien):
    await benih(2,1)
    from app.timbangan.models import TimbanganConfig
    async with database.SessionLocal() as db:
        db.add(TimbanganConfig(kunci='jam_tiket_menganggur',nilai='3'))
        rows = list((await db.scalars(select(TimbanganTransaksi).order_by(TimbanganTransaksi.id))).all())
        rows[0].timbang1_waktu = sekarang()-timedelta(days=2)
        rows[0].timbang1_waktu_sistem = sekarang()-timedelta(hours=1)
        rows[1].timbang1_waktu_sistem = sekarang()-timedelta(hours=4)
        rows[2].timbang1_waktu_sistem = sekarang()-timedelta(days=2)
        await db.commit()
    await login(klien)
    html = isi_main((await klien.get(PREFIX+'/tiket')).text)
    kartu = re.findall(r'<a[^>]*class="tf-ticket">(.*?)</a>',html,re.S)
    assert 'UJI-0000' in kartu[0] and '>Lama<' not in kartu[0]
    assert 'UJI-0001' in kartu[1] and '>Lama<' in kartu[1]
    part = isi_main((await klien.get(PREFIX+'/tiket?tab=partai')).text)
    assert 'UJI-0002' in part and '>Lama<' not in part

"""Fixture dan bukti biaya baca rekap, seluruhnya SQLite sementara."""
from collections import Counter
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from app import database
from app.timbangan.db import hari_ini, sekarang
from app.timbangan.models import TimbanganAkun, TimbanganTransaksi, TimbanganPemeriksaan
from test_web import app_uji, klien, login
from data_laporan import isi_laporan


async def isi_lembar(jumlah):
    ids, _ = await isi_laporan(database.SessionLocal)
    async with database.SessionLocal() as db:
        akun = await db.scalar(select(TimbanganAkun.id).order_by(TimbanganAkun.id))
        for i in range(jumlah):
            # Di luar periode rekap: tetap ikut jumlah tugas semua tanggal.
            t = TimbanganTransaksi(kode=f'UJR-{i:05}', tanggal=hari_ini()-timedelta(days=300),
                arah='MASUK', jenis_kode='GABAH_BASAH', pihak_nama='Pihak Fixture',
                timbang1_kg=1000, timbang1_waktu=sekarang(), timbang1_petugas_id=akun,
                status_tiket='SELESAI', status_transaksi='AKTIF',
                berat_barang_kg=975.125, status_kontrol='NORMAL')
            db.add(t)
            await db.flush()
            db.add(TimbanganPemeriksaan(transaksi_id=t.id, status='DIBUKA'))
        # Nilai selain SELESAI ikut daftar lama walau bukan DIBUKA.
        # Optimasi harus mengikuti kontrak daftar, bukan penghitung dashboard.
        db.add(TimbanganPemeriksaan(transaksi_id=ids[2], status='DITELUSURI'))
        await db.commit()
    return ids


@pytest.mark.skipif(os.getenv('UKUR_REKAP') != '1', reason='Pengukuran eksplisit fixture')
@pytest.mark.parametrize('jumlah', [10, 100, 1000])
async def test_ukur_rekap_baca(klien, jumlah):
    await isi_lembar(jumlah)
    await login(klien, 'wahid')
    label = 'baseline' if os.getenv('BASELINE_CARI') == '1' else 'candidate'
    output = Path(os.environ['BUKTI_CARI'])
    path = '/timbangan/laporan?tab=rekap&dari='+str(hari_ini())+'&sampai='+str(hari_ini())
    for _ in range(3):
        assert (await klien.get(path)).status_code == 200
    counts = Counter()
    sqls = []
    def sql(conn, cursor, statement, parameters, context, many):
        sqls.append(statement)
    def loaded(session, instance):
        counts[type(instance).__name__] += 1
    event.listen(Engine, 'before_cursor_execute', sql)
    event.listen(Session, 'loaded_as_persistent', loaded)
    samples = []
    try:
        for _ in range(20):
            counts.clear(); sqls.clear()
            start = time.perf_counter()
            response = await klien.get(path)
            elapsed = (time.perf_counter()-start)*1000
            assert response.status_code == 200
            assert f'{jumlah+4} lembar pemeriksaan masih terbuka' in response.text
            main = response.text.split('<main class="isi">')[1].split('</main>')[0]
            samples.append(dict(ms=elapsed, queries=len(sqls), loaded=dict(counts),
                                html_bytes=len(response.content),
                                main_sha256=hashlib.sha256(main.encode()).hexdigest()))
        (output/f'{label}-rekap-{jumlah}.html').write_text(response.text)
    finally:
        event.remove(Engine, 'before_cursor_execute', sql)
        event.remove(Session, 'loaded_as_persistent', loaded)
    times = sorted(x['ms'] for x in samples)
    result = dict(open_fixture=jumlah, samples=20, warmups=3,
        p50_ms=statistics.median(times), p95_ms=times[math.ceil(len(times)*.95)-1],
        sql_counts=sorted(set(x['queries'] for x in samples)),
        loaded_transaksi=sorted(set(x['loaded'].get('TimbanganTransaksi',0) for x in samples)),
        html_bytes=sorted(set(x['html_bytes'] for x in samples)), raw=samples,
        limitation='SQLite synthetic ASGI; ORM loaded rows, not physical DB scans; no production performance claim')
    (output/f'{label}-rekap-{jumlah}.json').write_text(json.dumps(result, indent=2)+'\n')


@pytest.mark.parametrize('tab', ['rekap', 'pemeriksaan', 'pemantauan'])
async def test_jumlah_lembar_sama_dengan_daftar_lama(klien, monkeypatch, tab):
    from app.timbangan import service
    from app.timbangan.routes import laporan
    ids = await isi_lembar(2)
    async with database.SessionLocal() as db:
        # VOID dan duplikasi tidak boleh dihilangkan oleh query count baru.
        db.add_all([TimbanganPemeriksaan(transaksi_id=ids[6], status='DIBUKA'),
                    TimbanganPemeriksaan(transaksi_id=ids[0], status='DIBUKA'),
                    TimbanganPemeriksaan(transaksi_id=999999, status='DIBUKA')])
        await db.commit()
        expected = len(await service.daftar_pemeriksaan_terbuka(db))
    async def monitoring(f):
        return []
    monkeypatch.setattr(laporan, '_monitoring_bersama', monitoring)
    if tab != 'pemeriksaan':
        async def no_full_read(db):
            raise AssertionError('Tab ini hanya memerlukan count')
        monkeypatch.setattr(service, 'daftar_pemeriksaan_terbuka', no_full_read)
    await login(klien, 'wahid')
    r = await klien.get('/timbangan/laporan', params={'tab':tab, 'dari':'1999-01-01', 'sampai':'1999-01-01'})
    assert r.status_code == 200
    assert f'aria-label="{expected} terbuka"' in r.text
    if tab == 'rekap':
        assert f'{expected} lembar pemeriksaan masih terbuka' in r.text
        assert 'data-ringkasan="jumlah"><strong>0' in r.text
    if tab == 'pemeriksaan':
        assert r.text.count('data-laporan-id=') == expected


async def test_tanpa_lembar_keadaan_kosong_sama(klien):
    await login(klien, 'wahid')
    for tab in ('rekap', 'pemeriksaan'):
        r = await klien.get('/timbangan/laporan', params={'tab':tab})
        assert r.status_code == 200
        assert 'aria-label="0 terbuka"' in r.text
        assert 'Semua pemeriksaan sudah ditutup.' in r.text


async def test_rekap_peta_status_hanya_tiket_yang_tampil(klien):
    from app.timbangan import service
    ids = await isi_lembar(100)
    await login(klien, 'wahid')
    loaded = []
    def on_load(session, instance):
        if isinstance(instance, (TimbanganTransaksi, TimbanganPemeriksaan)):
            loaded.append((type(instance).__name__, instance.id))
    event.listen(Session, 'loaded_as_persistent', on_load)
    try:
        r = await klien.get('/timbangan/laporan')
    finally:
        event.remove(Session, 'loaded_as_persistent', on_load)
    assert r.status_code == 200 and 'Pemeriksaan selesai' in r.text
    assert len([x for x in loaded if x[0] == 'TimbanganTransaksi']) <= 20
    assert len([x for x in loaded if x[0] == 'TimbanganPemeriksaan']) <= 20
    assert f'data-laporan-id="{ids[3]}"' in r.text

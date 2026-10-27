"""Uji batas sungguhan pada PostgreSQL uji; tidak memalsukan hasil query/rumus.

Jalankan dengan UJI_PG_URL loopback/uji_* dan UJI_BATAS_OUT untuk artefak.
Fixture pg/conftest mengosongkan DB uji per kasus. Jangan gunakan DB bersama
suite lain atau alamat operasional. Jumlah 10.000 berarti baris data CSV,
belum termasuk satu baris header.
"""
from collections import defaultdict
from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import csv,hashlib,io,json,logging,os,re,resource,sys
from time import perf_counter

import pytest
from sqlalchemy import event,insert,inspect,select,text

from app.timbangan import logic,service
from app.timbangan.models import (
    ROLE_ADMIN,ROLE_PETUGAS,ROLE_SUPERADMIN,TimbanganAkun,
    TimbanganFoto,TimbanganSupplierProfil,TimbanganTransaksi,
)
from app.timbangan.security import NAMA_COOKIE,buat_token
from app.models import Supplier

DARI=date(2026,10,1);SAMPAI=date(2026,10,2)
OUT=Path(os.environ.get('UJI_BATAS_OUT','../output/timbangan-laporan-20261024/batas'))


def catat(nama,data):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/(nama+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def peak_mb():
    n=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(n/(1024**2 if sys.platform=='darwin' else 1024),2)


async def isi(Sesi,jumlah):
    awal=perf_counter()
    async with Sesi() as db:
        url=db.bind.url
        assert url.host in ('localhost','127.0.0.1') and url.database.startswith('uji_')
        akun=[]
        for i,role in enumerate((ROLE_ADMIN,ROLE_SUPERADMIN,ROLE_PETUGAS)):
            a=TimbanganAkun(username=f'batas{i}',nama='Akun Sintetis',role=role,password_hash='uji-tidak-dipakai',perangkat_kode='U1')
            db.add(a);await db.flush();akun.append(a)
        nama=['=Pemasok Mayoritas Sintetis','+Pemasok Tepi Batas Sintetis','@Pemasok Tanpa Selisih Sintetis']
        pemasok=[]
        for n in nama:
            s=Supplier(nama_supplier=n);db.add(s);await db.flush();pemasok.append(s.id)
        db.add(TimbanganSupplierProfil(supplier_id=pemasok[0],status_monitoring='PANTAU'))
        db.add(TimbanganSupplierProfil(supplier_id=pemasok[1],status_monitoring='AKTIF'))
        def baris(i):
            tanggal=DARI if i%7==0 else SAMPAI
            kurang=None if i%11==0 else (-40.125 if i%2 else 12.5)
            sid=pemasok[1] if i in (7,14,21) else (None if i%13==0 else (pemasok[2] if i%17==0 else pemasok[0]))
            if sid==pemasok[2]:kurang=None
            waktu=datetime.combine(tanggal,time(0,0),tzinfo=timezone.utc)-timedelta(hours=2)+timedelta(minutes=15)
            return dict(kode=f'UJB-{i:06}',tanggal=tanggal,jenis_kode='GABAH_BASAH',arah='MASUK',supplier_id=sid,
                pihak_nama=['=Pihak, "Sintetis"\nBaris kedua','+Pihak Sintetis','-Pihak Sintetis','@Pihak Sintetis'][i%4],
                nomor_polisi='W 123 UJ',nama_sopir='Sopir Sintetis',timbang1_kg=15000,timbang1_waktu=waktu,timbang1_petugas_id=akun[0].id,
                timbang2_kg=5000 if kurang is not None else None,timbang2_waktu=waktu+timedelta(minutes=30) if kurang is not None else None,
                netto_timbangan_kg=10000 if kurang is not None else None,total_tara_kg=Decimal('24.877'),
                berat_barang_kg=Decimal('9975.123') if kurang is not None else None,berat_acuan_kg=10000 if kurang is not None else 0,
                selisih_kg=0 if kurang is None else kurang,selisih_persen=0 if kurang is None else kurang/100,
                batas_bawah_kg=-20,batas_atas_kg=20,status_kontrol=None if kurang is None else ('PERLU_PEMERIKSAAN' if kurang<0 else 'NORMAL'),
                status_tiket='TERBUKA' if kurang is None else 'SELESAI',status_transaksi='AKTIF',jumlah_revisi=1 if i%23==0 else 0)
        # execute Core mengisi default model; 1.000 per batch membatasi memori
        # benih. Seluruh angka hasil adalah snapshot sintetis, bukan transaksi
        # operasional yang dibuat melalui alur timbang.
        for start in range(1,jumlah+1,1000):
            await db.execute(insert(TimbanganTransaksi.__table__),[baris(i) for i in range(start,min(start+1000,jumlah+1))])
        aux=[baris(jumlah+i) for i in range(1,4)]
        aux[0].update(kode='UJB-VOID',status_transaksi='VOID',tanggal=SAMPAI)
        aux[1].update(kode='UJB-SEBELUM',tanggal=DARI-timedelta(days=1))
        aux[2].update(kode='UJB-SESUDAH',tanggal=SAMPAI+timedelta(days=1))
        await db.execute(insert(TimbanganTransaksi.__table__),aux)
        foto_id=await db.scalar(select(TimbanganTransaksi.id).where(TimbanganTransaksi.kode=='UJB-000007'))
        db.add(TimbanganFoto(transaksi_id=foto_id,nama_file='sintetis.jpg',konten=b'FOTO-SINTETIS'*1024,ukuran_byte=13312))
        await db.commit()
        return {'akun':akun,'pemasok':dict(zip(pemasok,nama)),'tepi':pemasok[1],'seed_seconds':round(perf_counter()-awal,3)}


async def snapshot(Sesi):
    tables=['timbangan_transaksi','timbangan_supplier_profil','timbangan_pemeriksaan','timbangan_audit','timbangan_cetak','timbangan_kiriman','proses_terpadu']
    async with Sesi() as db:
        return {t:tuple((await db.execute(text(f"SELECT count(*),md5(coalesce(string_agg(md5(row_to_json(x)::text),'' ORDER BY md5(row_to_json(x)::text)),'')) FROM {t} x"))).one()) for t in tables}


async def oracle(Sesi,limit=None):
    # SQL independen untuk keanggotaan/urutan: tidak memakai helper filter,
    # daftar_transaksi atau menghitung dari halaman hasil layanan.
    sql="""SELECT id,kode,tanggal,supplier_id,nomor_polisi,status_kontrol,
       selisih_kg,selisih_persen,berat_barang_kg,berat_acuan_kg,
       batas_bawah_kg,batas_atas_kg,jumlah_revisi FROM timbangan_transaksi
       WHERE tanggal BETWEEN :dari AND :sampai AND status_transaksi='AKTIF'
       ORDER BY tanggal DESC,id DESC"""
    if limit is not None:sql+=' LIMIT '+str(int(limit))
    async with Sesi() as db:return (await db.execute(text(sql),{'dari':DARI,'sampai':SAMPAI})).mappings().all()


def awasi(Sesi):
    """Mendeteksi DML tak sengaja selama pembacaan, selain snapshot data."""
    engine=Sesi.kw['bind'].sync_engine;writes=[]
    def check(conn,cursor,statement,parameters,context,executemany):
        m=re.match(r'\s*(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE)\b',statement,re.I)
        if m:writes.append(m[1].upper())
    event.listen(engine,'before_cursor_execute',check)
    return writes,lambda:event.remove(engine,'before_cursor_execute',check)


def acuan_skor(rows,nama):
    grouped=defaultdict(list)
    for r in rows:
        if r['supplier_id'] is not None:grouped[r['supplier_id']].append(r)
    result={}
    for sid,rs in grouped.items():
        if len(rs)<3:continue
        data=[]
        for r in rs:
            if r['selisih_kg'] is None or r['status_kontrol'] is None:continue
            minus=float(r['selisih_kg'])<0
            data.append(logic.TransaksiRingkas(tanggal=r['tanggal'],selisih_kg=float(r['selisih_kg']),selisih_persen=float(r['selisih_persen'] or 0),
                batas_kg=abs(float(r['batas_bawah_kg'])) if minus else float(r['batas_atas_kg']),berat_barang_kg=float(r['berat_barang_kg'] or 0),
                berat_acuan_kg=float(r['berat_acuan_kg'] or 0),nomor_polisi=r['nomor_polisi'],pihak_id=sid,pihak_nama=nama[sid],dikoreksi=bool(r['jumlah_revisi']),kode=r['kode']))
        # Rumus/pola yang berlaku dipanggil apa adanya, tidak disalin.
        score=logic.hitung_skor_pihak(data);patterns=logic.deteksi_pola(data)
        result[sid]=(len(data),score,patterns,logic.status_pihak_disarankan(score,patterns))
    return result


@pytest.mark.parametrize('jumlah',[49999,50000,50001])
async def test_batas_monitoring_postgres_asli(mesin,klien,monkeypatch,caplog,jumlah):
    benih=await isi(mesin,jumlah);expected=await oracle(mesin,50000);full=await oracle(mesin)
    before=await snapshot(mesin);calls=[];ids=[];original=service._data_monitoring;relasi=[]
    async def amati(db,f,*,batas=100,offset=0):
        result=await original(db,f,batas=batas,offset=offset)
        calls.append({'offset':offset,'limit':batas,'records':len(result)});ids.extend(b.id for b in result)
        return result
    monkeypatch.setattr(service,'_data_monitoring',amati)
    engine=mesin.kw['bind'].sync_engine
    def baca_relasi(conn,cursor,statement,parameters,context,executemany):
        if re.search(r'\bFROM\s+timbangan_(foto|muatan|penimbangan)\b',statement,re.I):
            relasi.append(statement)
    event.listen(engine,'before_cursor_execute',baca_relasi)
    writes,selesai=awasi(mesin);awal=perf_counter()
    with caplog.at_level(logging.WARNING,logger='timbangan.service'):
        async with mesin() as db:hasil=await service.monitoring_supplier(db,service.FilterTransaksi(dari=DARI,sampai=SAMPAI))
    seconds=perf_counter()-awal;selesai()
    event.remove(engine,'before_cursor_execute',baca_relasi)
    assert len(full)==jumlah and len(ids)==min(jumlah,50000)
    assert ids==[r['id'] for r in expected] and len(set(ids))==len(ids)
    assert len(calls)==50 and [c['offset'] for c in calls]==list(range(0,50000,1000))
    assert all(c['limit']==1000 for c in calls) and calls[-1]['records']==(999 if jumlah==49999 else 1000)
    warnings=[r for r in caplog.records if 'Monitoring pemasok berhenti' in r.getMessage()]
    assert bool(warnings)==(jumlah>50000)
    if warnings:assert '50000' in warnings[0].getMessage() and 'Persempit rentang tanggalnya.' in warnings[0].getMessage()
    ref=acuan_skor(expected,benih['pemasok']);assert {r.supplier_id for r in hasil}==set(ref)
    for r in hasil:
        n,score,pola,saran=ref[r.supplier_id]
        assert (r.jumlah_transaksi,r.skor,r.pola,r.status_disarankan)==(n,score,pola,saran)
    assert [r.skor.skor_total if r.skor else 100 for r in hasil]==sorted(r.skor.skor_total if r.skor else 100 for r in hasil)
    assert (benih['tepi'] in ref)==(jumlah<=50000)
    assert not writes and await snapshot(mesin)==before
    assert not relasi, 'Monitoring tidak perlu membaca foto, muatan atau langkah partai'
    # Endpoint asli tab Pemantauan diuji pada volume lebih
    # besar batas. Auth Admin tetap memakai token uji pada DB yang sama.
    endpoint_seconds=None
    if jumlah==50001:
        calls.clear();ids.clear();awal=perf_counter()
        h={'Cookie':NAMA_COOKIE+'='+buat_token(benih['akun'][0].id)}
        r=await klien.get('/timbangan/laporan',params={'tab':'pemantauan','dari':str(DARI),'sampai':str(SAMPAI)},headers=h)
        endpoint_seconds=perf_counter()-awal;assert r.status_code==200
        assert r.text.count('data-pihak-id=')==len(ref) and r.text.count('data-pihak-kartu=')==len(ref)
        assert f'data-pihak-id="{benih["tepi"]}"' not in r.text
        assert ids==[r['id'] for r in expected] and await snapshot(mesin)==before
    catat(f'monitoring-{jumlah}',{'status':'Lulus','synthetic_database_only':True,'input_matching':jumlah,'aux_excluded':3,'processed':len(expected),'excluded_by_cap':max(0,jumlah-50000),'pages':50,'last_page_records':999 if jumlah==49999 else 1000,'oldest_first_excluded_code':full[50000]['kode'] if jumlah>50000 else None,'boundary_supplier_qualified':benih['tepi'] in ref,'cap_warning':bool(warnings),'score_and_pattern_equal':True,'writes_during_read':writes,'snapshot_unchanged':True,'photo_blob_not_loaded':not relasi,'seed_seconds':benih['seed_seconds'],'service_seconds':round(seconds,3),'http_seconds':round(endpoint_seconds,3) if endpoint_seconds else None,'process_peak_rss_mb':peak_mb()})


@pytest.mark.parametrize('jumlah',[9999,10000,10001])
async def test_batas_csv_endpoint_asli(mesin,klien,jumlah):
    benih=await isi(mesin,jumlah);expected=await oracle(mesin,10000);before=await snapshot(mesin)
    writes,selesai=awasi(mesin);awal=perf_counter()
    # Filter ekstra sengaja tidak cocok: kontrak ekspor tetap periode saja.
    params={'dari':str(DARI),'sampai':str(SAMPAI),'tab':'pemeriksaan','cari':'TIDAK-ADA-HASIL','arah':'RETUR','status':'INVESTIGASI','jenis':'BEBAS'}
    h={'Cookie':NAMA_COOKIE+'='+buat_token(benih['akun'][0].id)}
    r=await klien.get('/timbangan/ekspor.csv',params=params,headers=h)
    seconds=perf_counter()-awal;selesai()
    assert r.status_code==200 and 'text/csv' in r.headers['content-type']
    assert r.headers['content-disposition']=='attachment; filename="timbangan-20261001-20261002.csv"'
    data=list(csv.DictReader(io.StringIO(r.text)))
    assert len(data)==min(jumlah,10000) and len(data[0])==21
    assert [d['kode'] for d in data]==[e['kode'] for e in expected] and len({d['kode'] for d in data})==len(data)
    assert not any(d['kode'] in ['UJB-VOID','UJB-SEBELUM','UJB-SESUDAH'] for d in data)
    for d,e in zip(data,expected):
        assert d['jam1']=='05:15' and d['tanggal']==str(e['tanggal'])
        if e['berat_barang_kg'] is None:assert d['berat_barang_kg']=='' and Decimal(d['selisih_kg'])==0
        else:
            assert Decimal(d['berat_barang_kg'])==Decimal(str(e['berat_barang_kg']))
            assert Decimal(d['selisih_kg'])==Decimal(str(e['selisih_kg'])) and d['jam2']=='05:45'
        assert d['pihak'].startswith("'") and d['pihak'][1] in '=+-@'
    assert any('\n' in d['pihak'] and '"' in d['pihak'] and ',' in d['pihak'] for d in data)
    assert not writes and await snapshot(mesin)==before
    operator={'Cookie':NAMA_COOKIE+'='+buat_token(benih['akun'][2].id)}
    assert (await klien.get('/timbangan/ekspor.csv',params=params,headers=operator)).status_code==403
    admin2={'Cookie':NAMA_COOKIE+'='+buat_token(benih['akun'][1].id)}
    super_r=await klien.get('/timbangan/ekspor.csv',params=params,headers=admin2)
    assert super_r.status_code==200 and super_r.content==r.content
    assert await snapshot(mesin)==before
    if jumlah==10001:
        OUT.mkdir(parents=True,exist_ok=True);(OUT/'csv-10000-baris-sintetis.csv').write_bytes(r.content)
    catat(f'csv-{jumlah}',{'status':'Lulus','synthetic_database_only':True,'input_matching':jumlah,'aux_excluded':3,'exported_data_rows':len(data),'header_rows':1,'columns':21,'excluded_by_cap':max(0,jumlah-10000),'all_codes_in_order_equal':True,'null_precision_sign_timezone_unchanged':True,'formula_guard_and_multiline_csv_valid':True,'extra_filters_ignored_as_before':True,'operator_http':403,'admin_http':200,'superadmin_content_equal':True,'writes_during_read':writes,'snapshot_unchanged':True,'response_bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest(),'seed_seconds':benih['seed_seconds'],'http_seconds':round(seconds,3),'process_peak_rss_mb':peak_mb()})

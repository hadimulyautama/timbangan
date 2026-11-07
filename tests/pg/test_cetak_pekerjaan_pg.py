"""Konkurensi cetak, rollback audit dan migrasi pada PostgreSQL loopback."""
import asyncio,uuid
import pytest
from sqlalchemy import select,func
from app.timbangan import cetak,service
from app.timbangan.models import TimbanganAkun,TimbanganCetak,TimbanganAudit,TimbanganPekerjaanCetak as Job

async def setup(mesin):
    async with mesin() as db:
        a=TimbanganAkun(username='uji'+uuid.uuid4().hex[:8],nama='Pencetak Sintetis',role='ADMIN',password_hash='x',perangkat_kode='U1');db.add(a);await db.commit()
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(kunci=uuid.uuid4().hex,arah='TRANSFER',jenis_kode='TRANSFER',berat_kg=10500,pihak_nama='Lintasan uji',nama_sopir='Sopir uji'))
        t=await service.simpan_timbang_kedua(db,akun=a,kode=t.kode,berat_kg=6500,muatan=[service.InputMuatan(jenis_kode='TRANSFER',jumlah_karung=100,tara_per_karung_kg=.0858)])
        _,_,u=await cetak.bahan(db,t.id,a)
        return a,t.id,dict(kunci=uuid.uuid4().hex,sidik=cetak.sidik(u,a),format='80MM',keluaran='printer',alasan='')

async def panggil(mesin,f,*args):
    async with mesin() as db:
        try:return await f(db,*args)
        except service.LayananError as e:
            await db.rollback();return str(e)

async def test_duabelas_kirim_dan_ack_hanya_satu(mesin):
    a,tid,d=await setup(mesin)
    jobs=await asyncio.gather(*[panggil(mesin,cetak.siapkan,tid,a,d) for _ in range(12)])
    assert all(isinstance(j,Job) for j in jobs)
    results=await asyncio.gather(*[panggil(mesin,cetak.keluarkan,tid,d['kunci'],a) for _ in range(12)])
    assert sum(isinstance(j,Job) for j in results)==1
    ack=await asyncio.gather(*[panggil(mesin,cetak.hasil,tid,d['kunci'],a,'printer_berhasil') for _ in range(12)])
    assert all(j.status=='berhasil' for j in ack)
    async with mesin() as db:
        assert await db.scalar(select(func.count()).select_from(Job))==1
        assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==1
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit).where(TimbanganAudit.aksi=='CETAK'))==1

async def test_dua_pekerjaan_beda_serial_dan_rollback_audit(mesin,monkeypatch):
    a,tid,d=await setup(mesin)
    rs=await asyncio.gather(panggil(mesin,cetak.siapkan,tid,a,d),panggil(mesin,cetak.siapkan,tid,a,dict(d,kunci=uuid.uuid4().hex)))
    jobs=[j for j in rs if isinstance(j,Job)];assert len(jobs)==1
    j=jobs[0];await panggil(mesin,cetak.keluarkan,tid,j.kunci,a)
    original=service.catat_audit
    async def gagal(*args,**kw):raise RuntimeError('UJI kegagalan audit')
    monkeypatch.setattr(service,'catat_audit',gagal)
    with pytest.raises(RuntimeError):await panggil(mesin,cetak.hasil,tid,j.kunci,a,'printer_berhasil')
    async with mesin() as db:
        assert await db.scalar(select(func.count()).select_from(TimbanganCetak))==0
        assert (await db.get(Job,j.kunci)).status=='dikirim'
    monkeypatch.setattr(service,'catat_audit',original)
    assert (await panggil(mesin,cetak.hasil,tid,j.kunci,a,'dikonfirmasi')).status=='berhasil'

async def test_kolom_model_pekerjaan_cetak(mesin):
    from sqlalchemy import inspect
    from app.database import Base
    async with mesin() as db:
        conn=await db.connection()
        columns=await conn.run_sync(lambda c:inspect(c).get_columns('timbangan_pekerjaan_cetak'))
        assert {c['name'] for c in columns}==set(Base.metadata.tables['timbangan_pekerjaan_cetak'].columns.keys())

async def test_migrasi_kolom_model_dan_dua_aplikasi(mesin):
    import ast,os
    from pathlib import Path
    from sqlalchemy import text,inspect
    from app.timbangan.skema import _head_dari_berkas
    async with mesin() as db:
        tables=await db.run_sync(lambda s:set(inspect(s.connection()).get_table_names()))
        if not {'alembic_version','alembic_version_timbangan'}<=tables:
            pytest.skip('Pemeriksaan dua rantai memerlukan profil DB hasil migrasi; fixture metadata tidak menyatakan revisi migrasi.')
        assert await db.scalar(text('select version_num from alembic_version_timbangan'))==_head_dari_berkas()
        root=Path(os.environ.get('UJI_PRODUKSI_ROOT',str(Path(__file__).resolve().parents[3]/'produksi')))
        assert (root/'migrations/versions').is_dir(), 'Set UJI_PRODUKSI_ROOT ke source PadiFlow untuk memeriksa head sebenarnya.'
        revisi=set();induk=set()
        for f in (root/'migrations/versions').glob('*.py'):
            for node in ast.parse(f.read_text()).body:
                if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('revision','down_revision') for t in node.targets):
                    key=node.targets[0].id;value=ast.literal_eval(node.value)
                    if key=='revision':revisi.add(value)
                    elif value:induk.update(value if isinstance(value,tuple) else [value])
        assert await db.scalar(text('select version_num from alembic_version')) in revisi-induk


async def test_kunci_sama_tiket_berbeda_tidak_menimpa(mesin):
    a,t1,d1=await setup(mesin);b,t2,d2=await setup(mesin);d2['kunci']=d1['kunci']
    rs=await asyncio.gather(panggil(mesin,cetak.siapkan,t1,a,d1),panggil(mesin,cetak.siapkan,t2,b,d2))
    assert sum(isinstance(j,Job) for j in rs)==1
    assert any('konteks lain' in j for j in rs if isinstance(j,str))
    async with mesin() as db:assert await db.scalar(select(func.count()).select_from(Job))==1

async def test_admin_dan_ack_pencetak_bersamaan_tidak_menggandakan_riwayat(mesin):
    a,tid,d=await setup(mesin)
    await panggil(mesin,cetak.siapkan,tid,a,d)
    await panggil(mesin,cetak.keluarkan,tid,d['kunci'],a)
    async with mesin() as db:
        admin=TimbanganAkun(username='admin'+uuid.uuid4().hex[:8],nama='Admin shift',role='ADMIN',password_hash='x');db.add(admin);await db.commit()
    async def konfirmasi_admin():
        async with mesin() as db:
            return await cetak.hasil(db,tid,d['kunci'],admin,'dikonfirmasi',alasan_penyelesaian='Pencetak berhenti, kedua rangkap diperiksa')
    rs=await asyncio.gather(konfirmasi_admin(),panggil(mesin,cetak.hasil,tid,d['kunci'],a,'printer_berhasil'))
    assert all(j.status=='berhasil' for j in rs)
    async with mesin() as db:
        lembar=(await db.scalars(select(TimbanganCetak))).all()
        assert len(lembar)==1 and lembar[0].oleh_id==a.id
        assert await db.scalar(select(func.count()).select_from(TimbanganAudit).where(TimbanganAudit.aksi=='CETAK'))==1

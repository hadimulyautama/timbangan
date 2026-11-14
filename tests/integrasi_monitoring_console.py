"""Pengandar dua interpreter, dibatasi database lokal bernama uji_."""
import asyncio,os,json,uuid
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
import httpx
from fastapi import FastAPI
url=os.environ['UJI_PG_URL'];u=make_url(url)
assert u.host in ('127.0.0.1','localhost') and u.database.startswith('uji_tf_kiriman_') and not u.query
from app import database
from app.timbangan import security as sec
from app.timbangan.web import pasang
from app.timbangan.monitoring import router
from hmu_identitas.ruang_data import klaim_sesi
x=json.loads(os.environ['UJI_MONITOR_DATA'])
async def main():
    engine=create_async_engine(url);database.SessionLocal=async_sessionmaker(engine,expire_on_commit=False)
    app=FastAPI();pasang(app);app.include_router(router)
    if x['phase']=='before':
        async with database.SessionLocal() as db:
            for value in [dict(akun_id=x['aid'],versi=1,b=1,**klaim_sesi()),dict(akun_id=x['linked'],versi=1,**klaim_sesi()),dict(akun_id=x['legacy'],versi=1,**klaim_sesi())]:assert await sec._profil_dari_sesi(db,value)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
            c.cookies.set(sec.NAMA_COOKIE,sec.buat_token_bersama(x['aid'],versi=1))
            r=await c.get('/timbangan/monitoring/konteks');assert r.status_code==200,r.text
            cap=r.json()['cap'];body=dict(cap=cap,kejadian=[dict(event_id=str(uuid.uuid4()),jenis='interaksi',layar='tiket')])
            assert (await c.post('/timbangan/monitoring/aktivitas',json=body)).status_code==202
            assert (await c.post('/timbangan/monitoring/aktivitas',json=body,headers={'Origin':'http://asing'})).status_code==403
            c.cookies.set(sec.NAMA_COOKIE,sec.buat_token(x['legacy'],versi=1))
            assert (await c.post('/timbangan/monitoring/aktivitas',json=body)).status_code==403
    else:
        async with database.SessionLocal() as db:
            for value in [dict(akun_id=x['aid'],versi=1,b=1,**klaim_sesi()),dict(akun_id=x['linked'],versi=1,**klaim_sesi()),dict(akun_id=x['legacy'],versi=1,**klaim_sesi())]:assert await sec._profil_dari_sesi(db,value) is None
        for name,pw,device in [('operator-aktif','sandi-pulih-staf-123','UT'),('legacy-monitor','sandi-pulih-lama-123','LG')]:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
                r=await c.post('/timbangan/masuk',data=dict(username=name,sandi=pw,perangkat=device));assert r.status_code==303,r.text
                assert (await c.get('/timbangan/monitoring/konteks')).status_code==200
    await engine.dispose();print(json.dumps(dict(berhasil=True)))
asyncio.run(main())

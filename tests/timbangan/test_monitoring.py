"""Metadata tidak mempercayai identitas, perusahaan, atau cap dari klien."""
import uuid
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from httpx import ASGITransport,AsyncClient
from app.timbangan.monitoring import router
from app.timbangan import security
from hmu_identitas import peran as P

@pytest.mark.asyncio
async def test_nonce_cap_dan_identitas_baru_ditolak(monkeypatch):
    monkeypatch.setenv('HMU_COMPANY_ID','1');monkeypatch.setenv('HMU_RUANG_DATA',str(uuid.uuid4()));monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI','0')
    akun=SimpleNamespace(id=3,akun_id=None,user_id=None,role=P.OPERATOR,token_version=1)
    async def identitas(request):request.state.akun=akun;return akun
    monkeypatch.setattr(security,'akun_opsional',identitas)
    app=FastAPI();app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://uji') as c:
        ctx=(await c.get('/timbangan/monitoring/konteks')).json()
        body=dict(cap=ctx['cap'],kejadian=[dict(event_id=str(uuid.uuid4()),jenis='interaksi',layar='tiket')])
        assert (await c.post('/timbangan/monitoring/aktivitas',json=body)).status_code==202
        assert (await c.post('/timbangan/monitoring/aktivitas',json={**body,'company_id':2})).status_code==422
        assert (await c.post('/timbangan/monitoring/aktivitas',json=body,headers={'Origin':'http://asing'})).status_code==403
        akun.token_version+=1
        assert (await c.post('/timbangan/monitoring/aktivitas',json=body)).status_code==403
        c.cookies.delete('tf_monitor_nonce')
        assert (await c.post('/timbangan/monitoring/aktivitas',json=body)).status_code==403


@pytest.mark.asyncio
@pytest.mark.parametrize('status,path,record',[(401,'/stok',True),(403,'/pengaturan',True),(200,'/stok',False),(304,'/stok',False),(403,'/internal/console/peta-akses',False),(401,'/monitoring/konteks',False)])
async def test_penolakan_halaman_tercatat_tanpa_mengubah_respons(monkeypatch,status,path,record):
    from hmu_identitas.monitoring import MonitoringHTTP,PengumpulPemakaian,PelakuPemakaian
    monkeypatch.setenv('HMU_COMPANY_ID','7');monkeypatch.setenv('HMU_RUANG_DATA',str(uuid.uuid4()));monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI','0')
    actor=PelakuPemakaian('staf',91,user_id=12,peran='operator');sent=[]
    async def app(scope,receive,send):
        await send(dict(type='http.response.start',status=status,headers=[(b'content-type',b'application/json')]))
        await send(dict(type='http.response.body',body=b'{"detail":"pesan tetap"}'))
    async def send(msg):sent.append(msg)
    for source in ('padiflow','teraflow'):
        collect=PengumpulPemakaian(None,source)
        await MonitoringHTTP(app,pengumpul=collect,pelaku=lambda _:actor)(dict(type='http',method='GET',path=path,state={},headers=[]),None,send)
        assert sent[-2]['status']==status and sent[-1]['body']==b'{"detail":"pesan tetap"}'
        assert collect.antrean.qsize()==int(record)
        if record:
            row=collect.antrean.get_nowait()
            assert row['company_id']==7 and row['aplikasi']==source and row['jenis_akun']=='staf' and row['akun_id']==91
            assert row['kode']==str(status) and row['metode']=='GET'

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

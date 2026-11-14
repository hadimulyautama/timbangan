"""Monitoring TeraFlow memakai identitas staf bersama; profil lama tetap terpisah."""
import hashlib,hmac,os,secrets
from pathlib import Path
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from app import database
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from hmu_identitas.monitoring import PengumpulPemakaian,PelakuPemakaian,PembukaanMasuk
from hmu_identitas.ruang_data import RuangData
pengumpul=PengumpulPemakaian(lambda:database.SessionLocal(),'teraflow',os.getenv('RAILWAY_GIT_COMMIT_SHA',''))
ASSET=Path(__import__('hmu_identitas').__file__).parent/'assets/monitoring.js'
VERSI=hashlib.sha256(ASSET.read_bytes()).hexdigest()[:12]
router=APIRouter(prefix='/timbangan/monitoring')


def pelaku_state(state):
    a=state.get('akun')
    if a:
        if a.akun_id:return PelakuPemakaian('staf',a.akun_id,a.akun.user_id if a.akun else a.user_id,P.normal(a.role))
        return PelakuPemakaian('timbangan_lama',a.id,a.user_id,P.normal(a.role))
    return state.get('monitoring_pelaku')


async def identitas(request):
    from app.timbangan.security import akun_opsional,_kunci
    from urllib.parse import urlsplit
    a=await akun_opsional(request)
    if not a:raise HTTPException(401,'Sesi tidak tersedia.')
    origin=request.headers.get('origin')
    if origin and urlsplit(origin).netloc!=request.headers.get('host'):
        raise HTTPException(403,'Asal permintaan tidak sesuai.')
    nonce=request.cookies.get('tf_monitor_nonce')
    if not nonce and request.method!='GET':raise HTTPException(403,'Konteks tidak tersedia.')
    nonce=nonce or secrets.token_urlsafe(32)
    actor=pelaku_state(request.state._state)
    versi=a.akun.token_version if a.akun_id else a.token_version
    pesan=f'{nonce}:{actor.jenis_akun}:{actor.akun_id}:{versi}'
    cap=hmac.new(_kunci(),pesan.encode(),hashlib.sha256).hexdigest()
    request.state.monitor_nonce=nonce
    return actor,cap


@router.get('/aktivitas.js')
async def skrip():return FileResponse(ASSET,media_type='application/javascript',headers={'Cache-Control':'public, max-age=3600'})

@router.get('/konteks')
async def konteks(request:Request):
    if not RuangData.lingkungan():raise HTTPException(503,'Monitoring belum dikonfigurasi.')
    a,cap=await identitas(request)
    response=JSONResponse(dict(csrf=cap,cap=cap),headers={'Cache-Control':'no-store'})
    response.set_cookie('tf_monitor_nonce',request.state.monitor_nonce,secure=request.url.scheme=='https' or bool(os.getenv('RAILWAY_ENVIRONMENT_ID')),httponly=True,samesite='strict',path='/timbangan/monitoring',max_age=600)
    return response

class Interaksi(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_id:UUID
    jenis:Literal['interaksi','galat_browser']
    kode:Literal['','TypeError','ReferenceError','RangeError','Error','promise']=''
    layar:Literal['stok','pekerjaan','barang-masuk','pengiriman','pengaturan','laporan','timbang','tiket','daftar','giling','sosoh','retur','lainnya']
class Batch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    cap:str=Field(max_length=128)
    kejadian:list[Interaksi]=Field(min_length=1,max_length=8)

@router.post('/aktivitas',status_code=202)
async def aktivitas(request:Request,data:Batch):
    if not RuangData.lingkungan():raise HTTPException(503,'Monitoring belum dikonfigurasi.')
    actor,cap=await identitas(request)
    if not hmac.compare_digest(cap,data.cap):raise HTTPException(403,'Konteks akun berubah.')
    for e in data.kejadian:pengumpul.catat(actor,jenis=e.jenis,layar=e.layar,kode=e.kode,event_id=str(e.event_id),ua=request.headers.get('user-agent',''))
    return {'diterima':True}

async def petunjuk_masuk(request,username,gerbang):
    ruang=RuangData.lingkungan()
    if not ruang:return
    try:
        from app.timbangan.models import TimbanganAkun
        async with database.SessionLocal() as db:
            row=await db.scalar(select(Akun).where(Akun.username==username))
            if row:actor=PelakuPemakaian('staf',row.id,row.user_id,P.normal(row.user.role))
            else:
                row=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username==username))
                if not row:return
                actor=PelakuPemakaian('staf',row.akun_id,row.user_id,P.normal(row.role)) if row.akun_id else PelakuPemakaian('timbangan_lama',row.id,row.user_id,P.normal(row.role))
            request.state.monitoring_pelaku=actor
            v=await db.scalar(select(PembukaanMasuk.generasi).where(PembukaanMasuk.company_id==ruang.company_id,PembukaanMasuk.jenis_akun==actor.jenis_akun,PembukaanMasuk.akun_id==actor.akun_id))
            gerbang.pakai_generasi(username,v or 0)
    except Exception:pass

def catat_login(request,kode):
    try:pengumpul.catat(getattr(request.state,'monitoring_pelaku',None) or PelakuPemakaian('anonim',0),jenis='login',layar='masuk',kode=kode,ua=request.headers.get('user-agent',''))
    except Exception:pass

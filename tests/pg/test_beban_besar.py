"""Beban TeraFlow termasuk dashboard, antrean, laporan dan formulir."""
import importlib.util
import os
import httpx
import pytest
from tests.pg.test_batas_laporan_pg import isi,DARI,SAMPAI
from app.timbangan.main import app
from app.timbangan.security import buat_token,NAMA_COOKIE

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(not os.environ.get('HMU_BEBAN_OUT'),reason='Beban besar dijalankan eksplisit')]

async def test_beban(mesin):
    n=int(os.environ.get('HMU_BEBAN_N','10000'))
    data=await isi(mesin,n)
    mod=importlib.util.spec_from_file_location('beban',os.environ['HMU_BEBAN_HARNESS'])
    harness=importlib.util.module_from_spec(mod);mod.loader.exec_module(harness)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={NAMA_COOKIE:buat_token(data['akun'][1].id)}) as admin, httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={NAMA_COOKIE:buat_token(data['akun'][2].id)}) as staff:
        paths=['/timbangan/','/timbangan/tiket','/timbangan/transaksi',f'/timbangan/laporan?dari={DARI}&sampai={SAMPAI}',f'/timbangan/monitoring?dari={DARI}&sampai={SAMPAI}','/timbangan/transaksi/7','/timbangan/timbang/GABAH_KERING']
        await harness.ukur(mesin,[('admin',admin,p) for p in paths]+[('petugas',staff,'/timbangan/tiket')],n)

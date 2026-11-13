"""Pembacaan konteks TeraFlow pada database uji kedua aplikasi; tanpa mutasi."""
import asyncio,json,os,sys
from dataclasses import asdict
from sqlalchemy.engine import make_url
from app.database import SessionLocal
from hmu_identitas.organisasi import konteks_kerja,OrganisasiTidakDiizinkan

async def main():
    url=make_url(os.environ['DATABASE_URL'])
    assert url.drivername=='postgresql+asyncpg' and url.host in ('127.0.0.1','localhost') and not url.query
    assert (url.database or '').startswith('uji_'), 'Hanya database uji lokal.'
    out=[]
    async with SessionLocal() as db:
        for args in json.loads(sys.argv[1]):
            try:out.append(dict(diizinkan=True,konteks=asdict(await konteks_kerja(db,**args))))
            except OrganisasiTidakDiizinkan:out.append(dict(diizinkan=False))
    print(json.dumps(out))

if __name__=='__main__':asyncio.run(main())

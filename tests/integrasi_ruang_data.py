"""Pagar runtime TeraFlow dibaca interpreter terpisah pada database uji."""
import asyncio,json,os
from sqlalchemy import text
from sqlalchemy.engine import make_url
from app.database import SessionLocal,dapatkan_engine
from hmu_identitas.ruang_data import RuangDataTidakCocok

async def main():
    url=make_url(os.environ['DATABASE_URL'])
    assert url.host in ('127.0.0.1','localhost') and not url.query and url.database.startswith('uji_')
    try:
        async with SessionLocal() as db:
            total=await db.scalar(text('SELECT count(*) FROM warehouses'))
        print(json.dumps(dict(diizinkan=True,gudang=total)))
    except RuangDataTidakCocok:
        print(json.dumps(dict(diizinkan=False)))
    finally:await dapatkan_engine().dispose()

if __name__=='__main__':asyncio.run(main())

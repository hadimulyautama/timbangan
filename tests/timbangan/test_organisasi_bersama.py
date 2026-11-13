"""Master organisasi tidak mengambil alih izin atau transaksi TeraFlow lama."""
import pytest
from sqlalchemy import select,func
from app import database
from app.timbangan.models import TimbanganTransaksi,TimbanganAudit
from hmu_core import Perusahaan,LokasiPabrik,PenempatanGudang,KeanggotaanPerusahaan,User,Warehouse
from hmu_identitas import peran as P
from hmu_identitas.organisasi import konteks_kerja,OrganisasiTidakDiizinkan
from test_web import app_uji,klien,login

pytestmark=pytest.mark.fondasi_multi


async def test_konteks_bersama_dan_layar_lama_tetap_berfungsi(klien):
    await login(klien)
    async with database.SessionLocal() as db:
        u=User(nama='Anggota organisasi uji',role=P.ADMIN,status='aktif')
        db.add(u);await db.flush()
        a=Perusahaan(kode='uji-a',nama='Perusahaan A');b=Perusahaan(kode='uji-b',nama='Perusahaan B')
        w=Warehouse(nama_gudang='Gudang uji',aktif=True)
        db.add_all([a,b,w]);await db.flush()
        s=LokasiPabrik(company_id=a.id,kode='pusat',nama='Pabrik A');db.add(s);await db.flush()
        db.add_all([PenempatanGudang(company_id=a.id,lokasi_pabrik_id=s.id,warehouse_id=w.id),
          KeanggotaanPerusahaan(company_id=a.id,user_id=u.id,peran=P.OPERATOR)])
        await db.commit()
        args=dict(user_id=u.id,company_id=a.id,lokasi_pabrik_id=s.id,warehouse_id=w.id)
        before=[await db.scalar(select(func.count()).select_from(t)) for t in (TimbanganTransaksi,TimbanganAudit)]
        ctx=await konteks_kerja(db,**args);assert ctx.company_id==a.id and ctx.peran==P.OPERATOR
        with pytest.raises(OrganisasiTidakDiizinkan):await konteks_kerja(db,**dict(args,company_id=b.id))
    # Gerbang lama masih bekerja tanpa memilih organisasi. Ini bukan aktivasi tenant.
    r=await klien.get('/timbangan/tiket');assert r.status_code==200
    async with database.SessionLocal() as db:
        assert [await db.scalar(select(func.count()).select_from(t)) for t in (TimbanganTransaksi,TimbanganAudit)]==before

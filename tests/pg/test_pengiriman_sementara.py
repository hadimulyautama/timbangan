"""Pengiriman tanpa nama pihak bisa disimpan sementara tanpa integrasi jaringan."""
from uuid import uuid4

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_pengiriman_sementara_tidak_memanggil_produksi(mesin, klien, monkeypatch):
    from app.timbangan import klien_produksi, security
    from app.timbangan.models import TimbanganAkun, TimbanganTransaksi, TimbanganAudit
    from hmu_identitas import sandi
    async with mesin() as db:
        akun = TimbanganAkun(username='uji_kirim', nama='Operator Uji', role='PETUGAS',
                              password_hash=sandi.hash_sandi('hanya-uji'), perangkat_kode='PU')
        db.add(akun)
        await db.commit()
        aid = akun.id
    kepala = {'Cookie': f'{security.NAMA_COOKIE}={security.buat_token(aid)}'}
    panggilan = []
    async def gagal(tid):
        panggilan.append(tid)
        raise klien_produksi.ProduksiTakTersedia('Jaringan uji terputus')
    monkeypatch.setattr(klien_produksi, 'muatan_pengiriman', gagal)
    r = await klien.post('/timbangan/timbang/PENGIRIMAN', headers=kepala, data={
        'kunci': str(uuid4()), 'berat_kg': '6000', 'nomor_polisi': 'U 1 JI',
        'nama_sopir': 'Sopir Uji'})
    assert r.status_code == 303
    async with mesin() as db:
        trx = (await db.execute(select(TimbanganTransaksi))).scalar_one()
        tid = trx.id
        assert trx.pelanggan_id is None
    r = await klien.post(f'/timbangan/tiket/{tid}', headers=kepala, data={
        'berat_kg': '6500', 'aksi': 'sementara', 'catatan': 'Menunggu armada dipilih',
        'jumlah_karung': '999', 'berat_acuan_kg': '999999'})
    assert r.status_code == 303
    assert not panggilan
    async with mesin() as db:
        trx = await db.get(TimbanganTransaksi, tid)
        assert trx.status_tiket == 'TERBUKA' and trx.pelanggan_id is None
        assert float(trx.timbang2_kg) == 6500
        assert trx.berat_barang_kg is None
        assert trx.catatan == 'Menunggu armada dipilih'
        assert float(trx.berat_acuan_kg or 0) == 0
        audit = (await db.execute(select(TimbanganAudit).where(
            TimbanganAudit.aksi == 'SIMPAN_SEMENTARA'))).scalar_one()
        assert audit.akun_id == aid
    r = await klien.post(f'/timbangan/tiket/{tid}', headers=kepala,
                         data={'berat_kg': '6500', 'aksi': 'selesai'})
    assert r.status_code == 303 and panggilan == [tid]
    async with mesin() as db:
        assert (await db.get(TimbanganTransaksi, tid)).status_tiket == 'TERBUKA'

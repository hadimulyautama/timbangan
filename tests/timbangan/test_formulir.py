"""Kontrak payload formulir: susunan boleh berubah, field/izin/alur tetap."""
import json,os
from html.parser import HTMLParser
from pathlib import Path
import pytest
from test_web import app_uji,klien,login  # noqa: F401
from app import database
from app.timbangan import service
from sqlalchemy import select
from app.timbangan.models import TimbanganAkun,TimbanganJenis

KONTRAK=Path(__file__).with_name('formulir_kontrak.json')
class Form(HTMLParser):
    def __init__(self):super().__init__();self.forms=[];self.current=None;self.stack=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.current={'action':a.get('action'),'method':a.get('method'),'fields':[]};self.forms.append(self.current)
        if tag in ('input','select','textarea','button') and self.current and a.get('name'):
            self.current['fields'].append({k:a[k] for k in ('name','type','required','formnovalidate','value') if k in a and (k!='value' or a.get('name') in ('aksi','cara_timbang'))})
    def handle_endtag(self,tag):
        if tag=='form':self.current=None

def fields(html):
    p=Form();p.feed(html)
    for f in p.forms:f['fields']=sorted(f['fields'],key=lambda x:json.dumps(x,sort_keys=True))
    return p.forms

@pytest.mark.parametrize('jalur',['/timbang/'+k for k in ['GABAH_BASAH','GABAH_KERING','BERAS_PK','BERAS_MASUK','BROKEN_MASUK','PENGIRIMAN','TRANSFER','RETUR_PELANGGAN','RETUR_SUPPLIER','BEBAS']]+['/jasa/GABAH_KERING'])
async def test_kontrak_field_payload_pertama(klien,jalur):
    await login(klien)
    r=await klien.get('/timbangan'+jalur);assert r.status_code==200
    got=fields(r.text)
    if os.environ.get('REKAM_KONTRAK_FORM')=='1':
        semua=json.loads(KONTRAK.read_text()) if KONTRAK.exists() else {};semua[jalur]=got;KONTRAK.write_text(json.dumps(semua,indent=2));return
    assert got==json.loads(KONTRAK.read_text())[jalur]

@pytest.mark.parametrize('arah,kode',[('MASUK','GABAH_BASAH'),('MASUK','GABAH_KERING'),('KELUAR','PENGIRIMAN'),('TRANSFER','TRANSFER'),('RETUR_MASUK','RETUR_PELANGGAN'),('RETUR_KELUAR','RETUR_SUPPLIER'),('BEBAS','BEBAS')])
async def test_kontrak_field_payload_kedua(klien,arah,kode,monkeypatch):
    from app.timbangan import klien_produksi
    async def gagal(*a,**kw):raise klien_produksi.ProduksiTakTersedia('Gangguan sintetis')
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',gagal)
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(kunci='form-'+kode,arah=arah,jenis_kode=kode,berat_kg=5000 if arah in ('KELUAR','RETUR_KELUAR') else 15000,pihak_nama='Pihak Sintetis' if arah=='TRANSFER' else None,supplier_id=1 if arah in ('MASUK','RETUR_MASUK','RETUR_KELUAR','BEBAS') else None,nomor_polisi='W 123 UJ',nama_sopir='Sopir Sintetis'))
        tid=t.id
    await login(klien);r=await klien.get(f'/timbangan/tiket/{tid}');assert r.status_code==200
    got=fields(r.text);key='/kedua/'+kode
    if os.environ.get('REKAM_KONTRAK_FORM')=='1':
        semua=json.loads(KONTRAK.read_text());semua[key]=got;KONTRAK.write_text(json.dumps(semua,indent=2));return
    assert got==json.loads(KONTRAK.read_text())[key]

async def tiket_uji(arah,kode):
    async with database.SessionLocal() as db:
        a=await db.scalar(select(TimbanganAkun).where(TimbanganAkun.username=='budi'))
        t=await service.simpan_timbang_pertama(db,akun=a,data=service.InputTimbang(kunci='preview-'+kode,arah=arah,jenis_kode=kode,berat_kg=5000 if arah in ('KELUAR','RETUR_KELUAR') else 15000,pihak_nama='Pihak Sintetis' if arah=='TRANSFER' else None,supplier_id=1 if arah in ('MASUK','RETUR_MASUK','RETUR_KELUAR','BEBAS') else None,nomor_polisi='W 123 UJ',nama_sopir='Sopir Sintetis',tara_lain_kg=5 if arah=='BEBAS' else 0))
        return t.id

async def pasang_muatan(monkeypatch,data=None,gagal=False):
    from app.timbangan import klien_produksi
    calls=[]
    async def baca(*a,**kw):
        if gagal:raise klien_produksi.ProduksiTakTersedia('Gangguan sintetis Produksi')
        return data or {'kode_perintah':'UJI-KR','pelanggan':'Pelanggan Sintetis','nomor_polisi':'W 123 UJ','muatan':[{'jenis_kode':'BERAS','nama':'Beras kemasan A','berat_kg':6000,'jumlah_karung':120,'tara_per_karung_kg':.11},{'jenis_kode':'BROKEN','nama':'Broken kemasan B','berat_kg':1000,'jumlah_karung':20,'tara_per_karung_kg':.07}]}
    async def tulis(*a,**kw):calls.append(True);return {'selesai':True}
    monkeypatch.setattr(klien_produksi,'muatan_pengiriman',baca);monkeypatch.setattr(klien_produksi,'selesaikan_pengiriman',tulis)
    return calls

@pytest.mark.parametrize('arah,kode',[('MASUK','GABAH_BASAH'),('MASUK','GABAH_KERING'),('MASUK','BERAS_PK'),('MASUK','BERAS_MASUK'),('MASUK','BROKEN_MASUK'),('KELUAR','PENGIRIMAN'),('TRANSFER','TRANSFER'),('RETUR_MASUK','RETUR_PELANGGAN'),('RETUR_KELUAR','RETUR_SUPPLIER'),('BEBAS','BEBAS')])
async def test_pratinjau_sama_hasil_resmi_tanpa_mutasi(klien,monkeypatch,arah,kode):
    from test_riwayat import snapshot
    from app.timbangan.models import TimbanganTransaksi,TimbanganKiriman
    from app.timbangan import format as fmt
    from sqlalchemy import func
    calls=await pasang_muatan(monkeypatch);tid=await tiket_uji(arah,kode);await login(klien)
    payload={'berat_kg':'12100' if arah=='KELUAR' else ('15000' if arah=='RETUR_KELUAR' else '5000'),'jumlah_karung':'200','tara_per_karung_kg':'0.250','berat_acuan_kg':'9960','nomor_acuan':'UJI-NOTA'}
    before=await snapshot()
    r=await klien.post(f'/timbangan/tiket/{tid}/pratinjau',data=payload)
    assert r.status_code==200,r.text;assert r.headers['cache-control']=='no-store'
    assert await snapshot()==before and not calls
    async with database.SessionLocal() as db:assert await db.scalar(select(func.count()).select_from(TimbanganKiriman))==0
    preview=r.json();assert preview['tersedia']
    await klien.post(f'/timbangan/tiket/{tid}',data={**payload,'aksi':'selesai'})
    async with database.SessionLocal() as db:
        t=await db.get(TimbanganTransaksi,tid);assert t.status_tiket=='SELESAI'
        assert preview['nilai']['Netto timbangan']==fmt.kg(t.netto_timbangan_kg)
        assert preview['nilai']['Potongan tara']==fmt.kg(t.total_tara_kg)
        assert preview['nilai']['Berat barang']==fmt.kg(t.berat_barang_kg)
        if arah.startswith('RETUR'):assert t.total_tara_kg==0
        if preview['pembanding']:assert preview['nilai']['Berat acuan']==fmt.kg(t.berat_acuan_kg)
        if arah=='KELUAR':assert len(t.muatan)==2 and float(t.total_tara_kg)==14.6

@pytest.mark.parametrize('berat',['','0','-1','NaN','Infinity','999999999999','16000'])
async def test_pratinjau_invalid_tidak_mengubah_tiket(klien,berat):
    from test_riwayat import snapshot
    tid=await tiket_uji('MASUK','GABAH_BASAH');await login(klien);before=await snapshot()
    r=await klien.post(f'/timbangan/tiket/{tid}/pratinjau',data={'berat_kg':berat,'jumlah_karung':'100','tara_per_karung_kg':'.25'})
    assert r.status_code==422 and not r.json()['tersedia'] and await snapshot()==before

@pytest.mark.parametrize('masalah',['gagal','kosong','tara'])
async def test_pratinjau_produksi_gagal_bukan_muatan_nol(klien,monkeypatch,masalah):
    from test_riwayat import snapshot
    data={'muatan':[]} if masalah=='kosong' else {'muatan':[{'jenis_kode':'BERAS','berat_kg':7000,'jumlah_karung':140,'tara_per_karung_kg':None}]}
    calls=await pasang_muatan(monkeypatch,data,gagal=masalah=='gagal');tid=await tiket_uji('KELUAR','PENGIRIMAN');await login(klien);before=await snapshot()
    r=await klien.post(f'/timbangan/tiket/{tid}/pratinjau',data={'berat_kg':'12100'})
    assert r.status_code==422 and not r.json()['tersedia'] and 'nilai' not in r.json()
    assert await snapshot()==before and not calls

@pytest.mark.parametrize('siapa',['budi','wahid','super'])
async def test_pratinjau_izin_sesuai_baca_tiket_dan_tiket_tutup(klien,app_uji,siapa):
    from test_web import _jadi_super
    from app.timbangan.models import TimbanganTransaksi
    tid=await tiket_uji('MASUK','GABAH_BASAH')
    # Tanpa sesi tidak memperoleh hasil atau data tiket.
    r=await klien.post(f'/timbangan/tiket/{tid}/pratinjau',data={'berat_kg':'5000'});assert 'tersedia' not in r.text
    if siapa=='super':await _jadi_super(app_uji)
    await login(klien,'wahid' if siapa=='super' else siapa)
    r=await klien.post(f'/timbangan/tiket/{tid}/pratinjau',data={'berat_kg':'5000','jumlah_karung':'100'});assert r.status_code==200
    for status,state in [('SELESAI','AKTIF'),('TERBUKA','VOID'),('DITUTUP_PAKSA','AKTIF')]:
        async with database.SessionLocal() as db:
            t=await db.get(TimbanganTransaksi,tid);t.status_tiket=status;t.status_transaksi=state;await db.commit()
        r=await klien.post(f'/timbangan/tiket/{tid}/pratinjau',data={'berat_kg':'5000','jumlah_karung':'100'});assert r.status_code==409 and not r.json()['tersedia']

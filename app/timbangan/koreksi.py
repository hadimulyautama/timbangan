"""Pemetaan formulir koreksi untuk simpan dan pratinjau baca saja.

Tidak menghitung di browser. Payload lama (termasuk nilai asli) tetap diterima;
field kosong mempertahankan nilai lama, dan hanya perubahan nyata dikirim ke
layanan koreksi yang memegang lock, versi, izin, audit serta sinkronisasi.
"""
from dataclasses import fields
from app.timbangan import service,logic,format as fmt
from app.timbangan.routes.pos import _angka, _karung

LABEL={'timbang1_kg':'Timbang pertama','timbang2_kg':'Timbang kedua','nomor_polisi':'Nomor polisi','nama_sopir':'Nama sopir','supplier_id':'Pihak','pelanggan_id':'Pemilik / pelanggan','catatan':'Catatan','jumlah_karung':'Jumlah karung','tara_per_karung_kg':'Tara per karung','berat_acuan_kg':'Berat menurut dokumen','nomor_acuan':'Nomor dokumen'}
NUM={'timbang1_kg','timbang2_kg','jumlah_karung','tara_per_karung_kg','berat_acuan_kg'}

def baca(trx,data):
    def nilai(n):return str(data.get(n,'') or '').strip()
    def beda(n):
        baru,asli=nilai(n),nilai('asli_'+n)
        if not baru:return False
        return (not asli or abs(_angka(baru)-_angka(asli))>1e-9) if n in NUM else baru!=asli
    perubahan={};ringkasan=[]
    def catat(n,lama,baru):
        if n in NUM:
            if lama is not None and abs(float(lama)-float(baru))<=1e-9:return
        elif lama==baru:return
        ringkasan.append({'field':n,'label':LABEL[n],'lama':tampil(lama,n),'baru':tampil(baru,n)})
        perubahan[n]=baru
    for n in ('timbang1_kg','timbang2_kg','nomor_polisi','nama_sopir'):
        if n=='timbang2_kg' and trx.timbang2_kg is None:continue
        if beda(n):catat(n,getattr(trx,n),_angka(nilai(n)) if n in NUM else (service.normalisasi_nopol(nilai(n)) if n=='nomor_polisi' else nilai(n)))
    pihak=service.pihak_untuk(trx.arah,jasa=trx.jasa)
    if nilai('supplier_id').isdigit() and pihak:
        catat(pihak[1],getattr(trx,pihak[1]),int(nilai('supplier_id')))
    if nilai('catatan'):catat('catatan',trx.catatan,nilai('catatan'))
    muatan=None
    if any(beda(n) for n in ('jumlah_karung','tara_per_karung_kg','berat_acuan_kg','nomor_acuan')):
        # Formulir lama hanya mengedit baris pertama. Salin SELURUH baris
        # beserta metadata; jangan meratakan pengiriman multi-kemasan.
        salinan=[service.InputMuatan(**{f.name:getattr(m,f.name) for f in fields(service.InputMuatan)}) for m in trx.muatan]
        if not salinan:salinan=[service.InputMuatan(jenis_kode=trx.jenis_kode)]
        pertama=salinan[0];berubah=False
        for n in ('jumlah_karung','tara_per_karung_kg','berat_acuan_kg','nomor_acuan'):
            lama=getattr(pertama,n)
            baru=nilai(n) if n=='nomor_acuan' else _angka(nilai(n),float(lama or 0))
            if n=='jumlah_karung':baru=_karung(nilai(n),float(lama or 0))
            if n=='tara_per_karung_kg' and trx.arah in (logic.RETUR_MASUK,logic.RETUR_KELUAR):baru=0
            if n=='nomor_acuan':baru=baru or lama
            sama=lama==baru if n=='nomor_acuan' else abs(float(lama or 0)-float(baru))<=1e-9
            if not sama:
                ringkasan.append({'field':n,'label':LABEL[n],'lama':tampil(lama,n),'baru':tampil(baru,n)})
                setattr(pertama,n,baru);berubah=True
        if berubah and trx.pengiriman_snapshot:
            raise service.LayananError("Rincian muatan kiriman berasal dari PadiFlow; koreksi sumber melalui PadiFlow.")
        if berubah:
            service.periksa_muatan(salinan)
            service.periksa_jumlah_karung(salinan, wajib=trx.selesai and
                                          service.periksa_jumlah_karung(trx.muatan)>0)
            muatan=salinan
    return perubahan,muatan,ringkasan

def tampil(v,n):
    if v is None or v=='':return '—'
    if n in NUM:return fmt.angka(v,4).rstrip('0').rstrip(',')+(' kg' if n!='jumlah_karung' else ' karung')
    return str(v)

async def periksa_bacaan_terbuka(db,trx,perubahan):
    # Jalur hitung ulang lama belum punya hasil bila bacaan kedua belum ada.
    # Tetap periksa bacaan pertama dengan validator fisik yang sama seperti
    # timbang pertama. Hasil sementara ini dibuang, tiket tidak diselesaikan.
    if trx.cara_timbang=='DUA_KALI' and trx.status_tiket=='TERBUKA' and 'timbang1_kg' in perubahan:
        aturan=service.aturan_dari_snapshot(trx) or await service.aturan_untuk(db,trx.jenis_kode)
        logic.hitung(aturan=aturan,berat_bermuatan_kg=perubahan['timbang1_kg'],berat_kosong_kg=None,muatan=[],kapasitas_kg=(await service.setelan.semua(db))['kapasitas_jembatan_kg'])

async def pratinjau(db,trx,perubahan,muatan):
    """Cabang cara timbang mengikuti _hitung_ulang_koreksi, tanpa menulis ORM."""
    await periksa_bacaan_terbuka(db,trx,perubahan)
    aturan=service.aturan_dari_snapshot(trx) or await service.aturan_untuk(db,trx.jenis_kode)
    baris=service._baris_logic(trx.muatan) if muatan is None else [logic.BarisMuatan(jenis_kode=m.jenis_kode,jumlah_karung=m.jumlah_karung,tara_per_karung_kg=float(m.tara_per_karung_kg),berat_acuan_kg=float(m.berat_acuan_kg),nomor_acuan=m.nomor_acuan) for m in muatan]
    pertama=float(perubahan.get('timbang1_kg',trx.timbang1_kg));kedua=perubahan.get('timbang2_kg',trx.timbang2_kg)
    if trx.cara_timbang=='PARTAI':
        bermuatan=sum(float(p.berat_kg) for p in trx.penimbangan);kosong=None
    elif trx.cara_timbang=='SEKALI':bermuatan,kosong=pertama,None
    else:
        if kedua is None or trx.status_tiket=='TERBUKA':return None
        bermuatan,kosong=service._bermuatan_dan_kosong(trx.arah,pertama,float(kedua))
    return logic.hitung(aturan=aturan,berat_bermuatan_kg=bermuatan,berat_kosong_kg=kosong,muatan=baris,tara_lain_kg=float(trx.tara_lain_kg or 0),kapasitas_kg=(await service.setelan.semua(db))['kapasitas_jembatan_kg'])

"""Dokumen timbang dari hasil tersimpan, ukuran fisik dan blok utuh.

Satu proyeksi angka dipakai bersama ePOS; tata letak tidak menghitung hasil.
NCR tetap tanpa selisih. PDF panjang membagi halaman, bukan mengecilkan teks.
"""
import io
from functools import partial
from xml.sax.saxutils import escape
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate,Frame,PageTemplate,Paragraph,Spacer,Table,TableStyle,KeepTogether,HRFlowable
from app.timbangan import format as fmt
from app.timbangan.bukti import baris_angka
from app.timbangan.pengiriman import rincian_bukti

NCR_L,NCR_T=215*mm,165*mm
STRUK_L=80*mm
TTD_STRUK_MM=20
TTD_NCR_MM=25

def _tanda_ulang(trx,cetakan_ke):
    parts=[]
    if cetakan_ke>1:parts.append(f'CETAKAN ULANG ke-{cetakan_ke}')
    if int(getattr(trx,'jumlah_revisi',0) or 0):parts.append(f'Revisi {trx.jumlah_revisi}')
    return ' · '.join(parts)

def _bukti(*,trx,aturan,pihak,petugas,muatan,perusahaan,alamat,telepon,arah_masuk,cetakan_ke=1,ncr=False,tampilkan_selisih=False):
    lebar=NCR_L if ncr else STRUK_L
    margin=(8 if ncr else 4)*mm
    isi=lebar-2*margin
    ukuran=9 if ncr else 8
    gaya=ParagraphStyle('isi',fontName='Helvetica',fontSize=ukuran,leading=ukuran*1.3,spaceAfter=0,splitLongWords=True)
    tengah=ParagraphStyle('tengah',parent=gaya,alignment=1)
    judul=ParagraphStyle('judul',parent=tengah,fontName='Helvetica-Bold',fontSize=12 if ncr else 10,leading=14)
    def p(v,style=gaya):return Paragraph(escape(str(v or '')).replace('\n','<br/>'),style)
    story=[p(perusahaan,judul),p(alamat,tengah),p(telepon,tengah),Spacer(1,3*mm),p('BUKTI TIMBANG',judul)]
    tanda=_tanda_ulang(trx,cetakan_ke)
    if tanda:story.append(p(tanda,tengah))
    story += [Spacer(1,2*mm),HRFlowable(width='100%',thickness=.8),Spacer(1,2*mm)]
    def tabel_kolom(rows,lebar_kolom):
        t=Table([[p(v) for v in row] for row in rows],colWidths=lebar_kolom,hAlign='LEFT')
        t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(-1,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),2 if ncr else 4),('TOPPADDING',(0,0),(-1,-1),1 if ncr else 2)]))
        return t
    def tabel(rows,rasio=.56):
        return tabel_kolom(rows,[isi*rasio,isi*(1-rasio)])
    ident=[('Nomor tiket',trx.kode),('Tanggal',trx.tanggal.strftime('%d-%m-%Y')),('Pengirim' if arah_masuk else 'Pihak',pihak),('Kegiatan',aturan.nama)]
    if not getattr(trx,'partai',False):ident += [('Nomor polisi',trx.nomor_polisi or '-'),('Sopir',trx.nama_sopir or '-')]
    if muatan and muatan[0].nomor_acuan:ident.append(('Nota' if arah_masuk else 'Surat jalan',muatan[0].nomor_acuan))
    if ncr:
        # Setengah NCR lebar: dua pasangan identitas per baris memberi ruang
        # untuk isi dan tanda tangan tanpa mengecilkan huruf atau kertas.
        pasangan=[[*ident[i],*(ident[i+1] if i+1<len(ident) else ('',''))]
                  for i in range(0,len(ident),2)]
        story.append(tabel_kolom(pasangan,[isi*r for r in (.16,.34,.14,.36)]))
    else:
        story.append(tabel(ident,.40))
    story += [Spacer(1,2*mm),HRFlowable(width='100%',thickness=.5)]
    rows=[(b.label+(f' · {b.jam}' if b.jam else ''),b.nilai) for b in baris_angka(trx,arah_masuk)]
    story.append(tabel(rows))
    story += [HRFlowable(width='100%',thickness=1),tabel([('BERAT BARANG',f'{fmt.angka(trx.berat_barang_kg)} kg')])]
    if tampilkan_selisih and not ncr:
        story.append(tabel([('Menurut dokumen',f'{fmt.angka(trx.berat_acuan_kg)} kg'),('Selisih',fmt.kg_tanda(trx.selisih_kg,2))]))
    rinci=rincian_bukti(trx,berat=tampilkan_selisih and not ncr)
    if rinci:
        story += [Spacer(1,3*mm),HRFlowable(width='100%',thickness=.5)]
        for line in rinci:story += [p(line),Spacer(1,1.2*mm)]
    if trx.catatan:story += [Spacer(1,3*mm),p('Catatan: '+trx.catatan)]
    partai=getattr(trx,'partai',False)
    saksi=pihak if partai else trx.nama_sopir or ''
    label=('Pengirim' if arah_masuk else 'Pihak') if partai else 'Sopir / saksi'
    # Spacer sendiri berukuran fisik: label dan nama tidak ikut dihitung.
    jarak=(TTD_NCR_MM if ncr else TTD_STRUK_MM)*mm
    sig=Table([[p('Petugas pencetak',tengah),p(label,tengah)],
               [Spacer(1,jarak),Spacer(1,jarak)],
               [p(petugas,tengah),p(saksi,tengah)]],colWidths=[isi/2,isi/2])
    sig.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),('LINEABOVE',(0,2),(-1,2),.5,colors.black),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5)]))
    blok_ttd=[Spacer(1,5*mm),sig,Spacer(1,3*mm),p('Ditandatangani kedua pihak sebagai bukti',tengah)]
    ttd=KeepTogether(blok_ttd)
    story.append(ttd)
    # Ukur seluruh flowable; tinggi struk dinamis. Dokumen sangat panjang
    # berpaginasi dengan ukuran baca tetap dan blok tanda tangan tak terbelah.
    tinggi=NCR_T
    if not ncr:
        ukur=[bagian for f in story for bagian in (blok_ttd if f is ttd else [f])]
        h=sum(f.wrap(isi,100000)[1]+f.getSpaceBefore()+f.getSpaceAfter() for f in ukur)
        tinggi=min(500*mm,max(100*mm,h+2*margin+2))
    buf=io.BytesIO()
    doc=BaseDocTemplate(buf,pagesize=(lebar,tinggi),leftMargin=margin,rightMargin=margin,topMargin=margin,bottomMargin=margin,title=trx.kode,author=perusahaan,pageCompression=1,invariant=1)
    def halaman(canvas, dok):
        if not ncr:return
        canvas.saveState()
        canvas.setFont('Helvetica',6)
        # Petunjuk distribusi lembar NCR lama tetap tersedia di setiap halaman.
        canvas.drawString(margin,3*mm,f"Lembar 1 - {'Pengirim' if arah_masuk else 'Pembeli'}   ·   Lembar 2 - Arsip pos timbang")
        if dok.page>1:
            canvas.drawString(margin,NCR_T-4*mm,f'Lampiran bukti timbang - {trx.kode} · revisi {int(getattr(trx,"jumlah_revisi",0) or 0)}')
        canvas.restoreState()
    # Frame bawaan menambah padding 6 pt di setiap sisi yang tidak ikut
    # pengukuran wrap. Lebar/tinggi layout harus sama dengan yang diukur.
    frame=Frame(margin,margin,isi,tinggi-2*margin,leftPadding=0,rightPadding=0,
                topPadding=0,bottomPadding=0,id='bukti')
    doc.addPageTemplates(PageTemplate(id='bukti',frames=[frame],onPage=halaman))
    doc.build(story,canvasmaker=partial(Canvas,invariant=1))
    return buf.getvalue()

def bukti_ncr(**kwargs):
    return _bukti(**kwargs,ncr=True)

def bukti_thermal(**kwargs):
    return _bukti(**kwargs,ncr=False)

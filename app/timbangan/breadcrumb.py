"""Satu hierarki desktop untuk seluruh jenis tiket; Kembali naik satu induk."""
import re
from urllib.parse import urlsplit,parse_qs,quote


def aman(value):
    if not isinstance(value,str) or not value.startswith('/timbangan') or value.startswith('//') or '\\' in value or any(ord(c)<32 for c in value):return None
    try:u=urlsplit(value)
    except ValueError:return None
    return value if not u.scheme and not u.netloc and (u.path=='/timbangan' or u.path.startswith('/timbangan/')) else None


def susun(path,ctx,judul):
    judul=ctx.get('judul_bagian') or judul
    prefix='/timbangan';u=urlsplit(path);p=u.path[len(prefix):].rstrip('/') or '/';q=parse_qs(u.query)
    b=ctx.get('b');trx=getattr(b,'trx',None)
    code=str(getattr(trx,'kode','') or '')
    parents=[('Beranda',prefix+'/')];leaf=judul
    def add(label,url):parents.append((label,prefix+url))
    m=re.match(r'^/transaksi/(\d+)(?:/(.+))?$',p)
    if p=='/':parents=[];leaf='Beranda'
    elif p=='/transaksi':leaf='Riwayat Timbang'
    elif m:
        add('Riwayat Timbang','/transaksi')
        if m[2]:
            target=prefix+'/transaksi/'+m[1]
            # Catatan filter daftar tetap ikut saat koreksi kembali ke detail.
            back=aman(q.get('kembali',[''])[0])
            if back and urlsplit(back).path==prefix+'/transaksi':target+='?kembali='+quote(back,safe='')
            parents.append((code or 'Detail tiket',target));leaf='Koreksi tiket' if m[2]=='koreksi' else judul
        else:leaf=code or judul
    elif p=='/tiket':leaf='Tiket Aktif'
    elif p.startswith('/tiket/') or re.match(r'^/partai/\d+$',p):
        add('Tiket Aktif','/tiket');leaf=code or judul
    elif p.startswith('/pilih/'):
        leaf=judul
    elif p.startswith(('/timbang/','/jasa/','/partai/')):
        aturan=ctx.get('aturan');arah=getattr(aturan,'arah',None) or ctx.get('arah')
        if arah:add({'MASUK':'Barang Masuk','KELUAR':'Pengiriman','TRANSFER':'Transfer internal','RETUR_MASUK':'Retur pelanggan','RETUR_KELUAR':'Retur supplier','BEBAS':'Jasa timbang'}.get(arah,'Pilih jenis timbang'),'/pilih/'+arah)
        leaf=judul
    elif p=='/laporan':leaf='Laporan & Pemeriksaan'
    elif p=='/monitoring':add('Laporan & Pemeriksaan','/laporan');leaf=judul
    elif p=='/pengaturan':leaf='Pengaturan'
    elif p in ('/printer','/akun','/aturan','/tara','/audit','/pengguna') or p.startswith('/pengguna/'):
        back=aman(ctx.get('kembali'))
        if p=='/printer' and back and re.match(r'^/timbangan/transaksi/\d+$',urlsplit(back).path):
            add('Riwayat Timbang','/transaksi');parents.append(('Detail tiket',back))
        else:
            add('Pengaturan','/pengaturan')
            if p.startswith('/pengguna/'):add('Pengguna','/pengguna')
        leaf=judul
    # Hanya query induk terdekat yang dipertahankan, tidak riwayat sebarang
    # atau URL eksternal. Ini mencegah Back berpindah keluarga halaman.
    if parents:
        name,url=parents[-1]
        candidates=sorted((x for x in [ctx.get('kembali'),q.get('kembali',[''])[0]] if aman(x)),key=lambda x:bool(urlsplit(x).query),reverse=True)
        for target in candidates:
            target=aman(target)
            if target and urlsplit(target).path==urlsplit(url).path and urlsplit(target).path!=u.path and (urlsplit(target).query or not urlsplit(url).query):
                parents[-1]=(name,target);break
    nodes=[]
    for label,url in parents:
        if url.rstrip('/')==path.rstrip('/'):continue
        if nodes and (nodes[-1]['nama'].casefold()==label.casefold() or nodes[-1]['alamat']==url):continue
        nodes.append(dict(nama=label,alamat=url))
    leaf=' '.join(str(leaf or 'Halaman').split())
    if nodes and nodes[-1]['nama'].casefold()==leaf.casefold():leaf='Detail'
    back=nodes[-1]['alamat'] if nodes else None;nodes.append(dict(nama=leaf,alamat=None))
    return dict(items=nodes,kembali=back)


from jinja2 import pass_context

@pass_context
def tampil(context,judul):
    request=context.get('request')
    path=(request.url.path+('?' +request.url.query if request.url.query else '')) if request else '/'
    if context.get('kode') in (403,404,500):judul=context.get('judul') or judul
    return susun(path,context,judul)

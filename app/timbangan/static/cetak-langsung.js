/* Cetak dari detail memakai mesin pekerjaan yang sama, tanpa navigasi halaman. */
(() => {
'use strict';
const tombol=document.querySelector('[data-cetak-langsung]');
if(!tombol||!window.TeraFlowCetak||typeof HTMLDialogElement==='undefined')return;
const basis=tombol.dataset.prefix+'/transaksi/'+encodeURIComponent(tombol.dataset.tiket)+'/cetak';
const hasil=document.querySelector('[data-cetak-langsung-hasil]');
const dialog=document.createElement('dialog');dialog.className='tf-cetak-dialog';
dialog.setAttribute('aria-labelledby','tf-cetak-judul');
dialog.innerHTML='<header><h2 id="tf-cetak-judul">Cetak struk 80 mm</h2><button type="button" class="tbl halus" aria-label="Tutup" data-tutup>×</button></header><div data-isi></div>';
document.body.append(dialog);
const isi=dialog.querySelector('[data-isi]'),tutup=dialog.querySelector('[data-tutup]');
let memuat=false;
function sibuk(){return memuat||isi.querySelector('[data-sibuk="1"]');}
function pesan(text){hasil.textContent=text;hasil.hidden=!text;}
tutup.addEventListener('click',()=>{if(!sibuk())dialog.close();});
dialog.addEventListener('cancel',e=>{if(sibuk())e.preventDefault();});
dialog.addEventListener('close',()=>tombol.focus());
async function segarkanRiwayat(){
 try{
  const r=await fetch(location.href,{credentials:'same-origin',cache:'no-store'});
  if(!r.ok||r.redirected)return;
  const doc=new DOMParser().parseFromString(await r.text(),'text/html');
  const lama=document.querySelector('[data-riwayat-cetak]'),baru=doc.querySelector('[data-riwayat-cetak]');
  if(lama&&baru)lama.replaceWith(document.importNode(baru,true));
 }catch(e){/* Cetak sudah tercatat; kegagalan membaca ulang tidak mengirim ulang. */}
}
async function muat(langsung){
 if(memuat)return;memuat=true;isi.textContent='Menyiapkan cetak…';tutup.disabled=true;
 try{
  const r=await fetch(basis+'/konteks',{credentials:'same-origin',cache:'no-store'});
  if(r.redirected)throw new Error('Sesi berubah. Masuk kembali sebelum mencetak.');
  if(!/application\/json/i.test(r.headers.get('Content-Type')||''))throw new Error('Data cetak belum terkonfirmasi. Periksa sesi dan coba lagi.');
  const data=await r.json();if(!r.ok)throw new Error(data.error||'Data cetak belum tersedia.');
  const root=document.createElement('section');root.className='cp cp-inline';root.dataset.cetakHalaman='';
  root.dataset.tujuan=basis+'/pekerjaan';root.dataset.sidik=data.sidik;root.dataset.identitas=data.identitas;
  root.innerHTML=`<p data-kode></p>
    <div hidden><input type="radio" name="cp-format" value="80MM" checked><input type="radio" name="cp-keluaran" value="printer" checked><span data-cp-label></span></div>
    <div data-keluaran hidden></div><p data-ncr-note hidden></p>
    <div data-printer-info hidden><span data-alamat-printer></span></div>
    <label class="grup" data-alasan-label hidden>Alasan cetak ulang<input class="fld" name="alasan" maxlength="2000" autocomplete="off" placeholder="Jelaskan alasan cetak ulang"></label>
    <button class="tbl blok" type="button" data-cp-jalankan>Cetak</button>
    <p class="bantu" data-cp-keterangan hidden></p>
    <p class="pesan" role="status" aria-live="polite" data-cp-status hidden></p>
    <a class="tbl halus" data-cp-pdf target="_blank" rel="noopener" hidden>Buka berkas cetakan tertunda</a>
    <section class="cp-pending" data-cp-pending hidden><h3 data-pending-judul></h3><p data-pending-teks></p><button type="button" class="tbl" data-cp-ya>Sudah tercetak</button><button type="button" class="tbl halus" data-cp-tidak>Belum tercetak</button></section>
    <button class="tbl halus" type="button" data-cp-segar hidden>Perbarui data cetak</button>`;
  root.querySelector('[data-kode]').textContent=data.kode;
  const alasan=root.querySelector('[name=alasan]');alasan.required=data.ulang;
  root.querySelector('[data-alasan-label]').hidden=!data.ulang;
  // Nilai lama dipakai hanya untuk menuntaskan pekerjaan yang telah disiapkan.
  if(data.pekerjaan){
   for(const [name,value] of [['cp-format',data.pekerjaan.format],['cp-keluaran',data.pekerjaan.keluaran]]){
    if(!root.querySelector(`[name="${name}"][value="${value}"]`)){
     const radio=document.createElement('input');radio.type='radio';radio.name=name;radio.value=value;radio.hidden=true;root.append(radio);
    }
   }
  }
  const state=document.createElement('script');state.type='application/json';state.dataset.cpJob='';state.textContent=JSON.stringify(data.pekerjaan);root.append(state);
  isi.replaceChildren(root);
  const mesin=window.TeraFlowCetak.pasang(root,{segar:berhasil=>{
   if(berhasil){pesan('Struk berhasil dicetak dan tercatat.');dialog.close();segarkanRiwayat();}
   else muat(false);
  }});
  if(!window.TeraFlowPrinter?.alamat()){
   const link=document.createElement('a');link.href=tombol.dataset.prefix+'/printer';link.textContent='Siapkan printer';root.append(link);
  }
  if(data.ulang&&!data.pekerjaan)alasan.focus();
  if(langsung&&!data.pekerjaan&&!data.ulang)mesin.jalan();
 }catch(e){isi.textContent=e.message||'Data cetak belum tersedia. Periksa jaringan, lalu coba lagi.';}
 finally{memuat=false;tutup.disabled=false;}
}
tombol.addEventListener('click',event=>{
 event.preventDefault();if(dialog.open||memuat)return;pesan('');dialog.showModal();muat(true);
});
})();

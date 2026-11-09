/* Penampil PDF bersama: dokumen asli dirender lokal, tanpa pindah halaman. */
(() => {
'use strict';
const tombol=[...document.querySelectorAll('[data-lihat-pdf]')];if(!tombol.length)return;
const aset=new URL(document.currentScript.src),libURL=new URL('vendor/pdfjs/pdf.min.mjs'+aset.search,aset),workerURL=new URL('vendor/pdfjs/pdf.worker.min.mjs'+aset.search,aset);
const dialog=document.createElement('dialog');dialog.className='tf-pdf-dialog';dialog.setAttribute('aria-labelledby','tf-pdf-judul');
dialog.innerHTML='<header><h2 id="tf-pdf-judul">Struk 80 mm</h2><div class="tf-pdf-actions"><button type="button" class="tbl halus" data-pdf-kecil aria-label="Perkecil PDF">−</button><button type="button" class="tbl halus" data-pdf-besar aria-label="Perbesar PDF">+</button><button type="button" class="tbl halus" data-pdf-tutup aria-label="Tutup PDF">×</button></div></header><div><p role="status" aria-live="polite" data-pdf-status></p><button type="button" class="tbl halus" data-pdf-ulang hidden>Coba lagi</button></div><div class="tf-pdf-view" data-pdf-view tabindex="0" aria-label="Isi PDF struk"></div>';
document.body.append(dialog);
const status=dialog.querySelector('[data-pdf-status]'),view=dialog.querySelector('[data-pdf-view]'),ulang=dialog.querySelector('[data-pdf-ulang]'),kecil=dialog.querySelector('[data-pdf-kecil]'),besar=dialog.querySelector('[data-pdf-besar]');
let pembuka=null,permintaan=null,tugas=null,pdf=null,renderAktif=null,generasi=0,putaran=0,zoom=1,modul=null;
function lepaskan(){
 generasi++;putaran++;permintaan?.abort();permintaan=null;renderAktif?.cancel();renderAktif=null;
 if(tugas)tugas.destroy().catch(()=>{});tugas=null;pdf=null;view.replaceChildren();
}
function kontrol(){kecil.disabled=!pdf||zoom<=1;besar.disabled=!pdf||zoom>=2;}
// Safari lama belum menyediakan async iterator untuk ReadableStream.
// Reader standar tetap membaca seluruh teks tanpa mengubah PDF asli.
async function teksHalaman(halaman){
 const reader=halaman.streamTextContent().getReader(),teks=[];
 try{while(true){const {value,done}=await reader.read();if(done)break;for(const item of value.items||[])teks.push(item.str||'');}}
 finally{reader.releaseLock();}
 return teks.join(' ');
}
async function gambar(){
 if(!pdf)return;
 const dok=pdf,nomor=++putaran;renderAktif?.cancel();view.replaceChildren();kontrol();
 status.textContent='Menampilkan PDF…';view.setAttribute('aria-busy','true');
 try{
  for(let i=1;i<=dok.numPages;i++){
   const halaman=await dok.getPage(i);if(nomor!==putaran||!dialog.open)return;
   const dasar=halaman.getViewport({scale:1}),lebar=Math.min(view.clientWidth-24,540)*zoom,viewport=halaman.getViewport({scale:lebar/dasar.width});
   const rasio=Math.min(devicePixelRatio||1,2,8192/viewport.height,Math.sqrt(8000000/(viewport.width*viewport.height)));
   const figure=document.createElement('figure');figure.className='tf-pdf-page';figure.setAttribute('role','group');figure.setAttribute('aria-label','Halaman '+i+' dari '+dok.numPages);
   const canvas=document.createElement('canvas');canvas.setAttribute('aria-hidden','true');canvas.width=Math.max(1,Math.floor(viewport.width*rasio));canvas.height=Math.max(1,Math.floor(viewport.height*rasio));canvas.style.width=viewport.width+'px';canvas.style.height=viewport.height+'px';
   figure.append(canvas);view.append(figure);
   renderAktif=halaman.render({canvasContext:canvas.getContext('2d'),viewport,transform:[rasio,0,0,rasio,0,0],background:'#fff'});
   await renderAktif.promise;if(nomor!==putaran||!dialog.open)return;
   const teks=await teksHalaman(halaman);if(nomor!==putaran||!dialog.open)return;
   const pembaca=document.createElement('p');pembaca.className='tf-pdf-sr';pembaca.textContent=teks;figure.append(pembaca);
   figure.dataset.pdfSelesai='1';
  }
  if(nomor===putaran){status.textContent=dok.numPages+' halaman';view.setAttribute('aria-busy','false');}
 }catch(e){if(nomor===putaran&&dialog.open){status.textContent='PDF belum dapat ditampilkan. Coba lagi.';ulang.hidden=false;view.setAttribute('aria-busy','false');}}
}
async function muat(){
 lepaskan();const nomor=generasi;zoom=1;kontrol();ulang.hidden=true;status.textContent='Memuat PDF…';view.setAttribute('aria-busy','true');permintaan=new AbortController();
 try{
  const url=new URL(pembuka.dataset.pdfUrl,location.href);
  const r=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:permintaan.signal});
  if(!r.ok||r.redirected||!/application\/pdf/i.test(r.headers.get('Content-Type')||''))throw new Error('dokumen');
  const bytes=new Uint8Array(await r.arrayBuffer());if(nomor!==generasi||!dialog.open)return;
  if(!modul)modul=import(libURL.href).catch(e=>{modul=null;throw e;});
  const mesin=await modul;if(nomor!==generasi||!dialog.open)return;
  mesin.GlobalWorkerOptions.workerSrc=workerURL.href;
  tugas=mesin.getDocument({data:bytes,isEvalSupported:false,useSystemFonts:true,enableXfa:false});
  const dok=await tugas.promise;if(nomor!==generasi||!dialog.open)return;pdf=dok;await gambar();
 }catch(e){if(nomor===generasi&&dialog.open){status.textContent='PDF belum dapat ditampilkan. Periksa jaringan atau sesi, lalu coba lagi.';ulang.hidden=false;view.setAttribute('aria-busy','false');}}
}
tombol.forEach(button=>button.addEventListener('click',()=>{if(dialog.open)return;pembuka=button;dialog.showModal();muat();}));
dialog.querySelector('[data-pdf-tutup]').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{lepaskan();pembuka?.focus();});
ulang.addEventListener('click',muat);
kecil.addEventListener('click',()=>{zoom=Math.max(1,zoom-.25);gambar();});
besar.addEventListener('click',()=>{zoom=Math.min(2,zoom+.25);gambar();});
let lebar=0,timer;new ResizeObserver(()=>{if(dialog.open&&pdf&&Math.abs(view.clientWidth-lebar)>1){lebar=view.clientWidth;clearTimeout(timer);timer=setTimeout(gambar,120);}}).observe(view);
})();

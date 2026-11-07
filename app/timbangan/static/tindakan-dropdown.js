/* Pilihan tindakan bersama; node formulir, izin, dan endpoint tetap asli. */
(() => {
'use strict';
function init(){
 const sumber=document.querySelector('[data-tindakan-sumber]'),dropdown=document.querySelector('[data-tindakan-dropdown]');
 if(!sumber||!dropdown||typeof HTMLDialogElement==='undefined')return;
 const menu=dropdown.querySelector('[data-tindakan-menu]'),pemicu=dropdown.querySelector('summary'),kode=sumber.dataset.kode;
 const dialog=document.createElement('dialog');dialog.className='tf-actions-dialog';dialog.setAttribute('aria-labelledby','tf-actions-judul');
 dialog.innerHTML='<header><h2 id="tf-actions-judul"></h2><button type="button" class="tbl halus" data-tindakan-tutup aria-label="Tutup tindakan">×</button></header><div data-tindakan-slot></div>';
 document.body.append(dialog);const slot=dialog.querySelector('[data-tindakan-slot]'),judul=dialog.querySelector('h2'),tutup=dialog.querySelector('[data-tindakan-tutup]');
 const sibuk=()=>!!slot.querySelector('[data-tf-busy="1"]');
 tutup.addEventListener('click',()=>{if(!sibuk()){dialog.close();pemicu.focus();}});
 dialog.addEventListener('cancel',e=>{if(sibuk())e.preventDefault();});
 dialog.addEventListener('close',()=>pemicu.focus());
 for(const node of [...sumber.children]){
  if(node.tagName==='A'){
   node.className='tf-actions-item';menu.append(node);node.addEventListener('click',()=>{dropdown.open=false;});
  }else if(node.tagName==='DETAILS'){
   const summary=node.querySelector(':scope>summary'),label=summary.textContent.trim().replace(/\s+/g,' '),button=document.createElement('button');
   button.type='button';button.className='tf-actions-item';button.textContent=label;button.setAttribute('aria-haspopup','dialog');
   if(node.querySelector('form')?.action.endsWith('/hapus'))button.classList.add('tf-actions-danger');
   node.hidden=true;node.open=true;slot.append(node);menu.append(button);
   button.addEventListener('click',()=>{dropdown.open=false;slot.querySelectorAll(':scope>details').forEach(x=>x.hidden=x!==node);judul.textContent=label;dialog.showModal();node.querySelector('textarea,input')?.focus();});
  }else if(node.textContent.trim()){
   node.classList.add('tf-actions-note');menu.append(node);
  }
 }
 if(!menu.children.length){dialog.remove();return;}
 // Fallback tetap tersedia bila JS tidak berjalan; saat aktif tak ada salinan tombol bawah.
 const fallback=sumber.closest('[data-rd-actions-fallback]')||sumber.closest('details');
 if(fallback)fallback.hidden=true;sumber.hidden=true;dropdown.hidden=false;
 function posisi(){if(!dropdown.open)return;const rect=dropdown.getBoundingClientRect(),lebar=Math.min(280,innerWidth-32),kiri=Math.min(Math.max(rect.left,16),innerWidth-lebar-16);menu.style.left=(kiri-rect.left)+'px';menu.style.right='auto';}
 function tutupMenu(fokus=false){dropdown.open=false;pemicu.setAttribute('aria-expanded','false');if(fokus)pemicu.focus();}
 pemicu.setAttribute('aria-expanded','false');
 pemicu.addEventListener('click',e=>{e.preventDefault();dropdown.open=!dropdown.open;pemicu.setAttribute('aria-expanded',String(dropdown.open));posisi();});
 dropdown.addEventListener('toggle',()=>{pemicu.setAttribute('aria-expanded',String(dropdown.open));posisi();});window.addEventListener('resize',posisi);
 // Capture menangani klik/sentuh luar meski komponen lain menghentikan bubbling.
 function luar(e){if(dropdown.open&&!dropdown.contains(e.target))tutupMenu();}
 document.addEventListener('pointerdown',luar,true);document.addEventListener('click',luar,true);
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&dropdown.open){e.preventDefault();tutupMenu(true);}},true);
 dropdown.addEventListener('focusout',e=>{if(e.relatedTarget&&!dropdown.contains(e.relatedTarget))tutupMenu();});
 window.addEventListener('pagehide',()=>tutupMenu());
 slot.querySelectorAll('form').forEach(form=>{
  let menunggu=false;const pesan=document.createElement('p');pesan.className='pesan pesan--err';pesan.setAttribute('role','alert');pesan.hidden=true;form.append(pesan);
  form.addEventListener('submit',async e=>{
   e.preventDefault();if(menunggu)return;menunggu=true;form.dataset.tfBusy='1';pesan.hidden=true;
   const tombol=form.querySelector('button[type=submit]');tombol.disabled=true;tutup.disabled=true;
   const batas=new AbortController(),waktu=setTimeout(()=>batas.abort(),30000);
   try{
    const r=await fetch(form.action,{method:'POST',body:new URLSearchParams(new FormData(form)),credentials:'same-origin',signal:batas.signal});
    const url=new URL(r.url),hapus=new URL(form.action).pathname.endsWith('/hapus');
    const ok=hapus?kode+' dihapus permanen.':'Transaksi dibatalkan. Datanya tetap tersimpan.';
    const path=hapus?location.pathname.replace(/\/transaksi\/\d+$/,'/transaksi'):location.pathname;
    if(r.ok&&r.redirected&&url.origin===location.origin&&url.pathname===path&&url.searchParams.get('ok')===ok){
     if(!hapus){const kembali=new URL(location.href).searchParams.get('kembali');if(kembali)url.searchParams.set('kembali',kembali);}
     location.assign(url.pathname+url.search);return;
    }
    throw new Error(url.searchParams.get('err')||'Server belum mengonfirmasi penyimpanan. Periksa sesi dan status tiket terbaru sebelum mencoba kembali.');
   }catch(err){pesan.textContent=(err.name==='TypeError'||err.name==='AbortError'?'Penyimpanan belum terkonfirmasi. Periksa tiket terbaru sebelum mencoba kembali.':err.message)+' Isian tetap tersedia di formulir ini.';pesan.hidden=false;}
   finally{clearTimeout(waktu);menunggu=false;form.dataset.tfBusy='0';tombol.disabled=false;tutup.disabled=false;}
  });
 });
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();

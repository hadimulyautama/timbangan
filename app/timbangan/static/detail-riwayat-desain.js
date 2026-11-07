/* Detail barang masuk: progressive disclosure, bukan pengambilan data baru.
 * Form pemeriksaan dan endpoint tetap asli; listener pemeriksaan.js hidup
 * pada node yang dipindahkan ke dialog, bukan pada salinannya. */
(() => {
  'use strict';
  const akar = document.querySelector('[data-riwayat-desain]');
  if (!akar || akar.dataset.rdSiap) return;
  akar.dataset.rdSiap = '1';
  function panel(kind, id, trigger) {
    const dialog = akar.querySelector('#'+id), content = akar.querySelector('[data-rd-'+kind+'-content]');
    if (!dialog || !content || typeof dialog.showModal !== 'function') return null;
    akar.querySelector('[data-rd-'+kind+'-slot]').append(content);
    akar.querySelector('[data-rd-'+kind+'-fallback]').hidden = true;
    akar.querySelectorAll(trigger).forEach(button => {
      button.hidden = false; button.setAttribute('aria-controls',id); button.setAttribute('aria-haspopup','dialog');
      button.addEventListener('click', event => {event.preventDefault();dialog._pembuka=button;dialog.showModal();});
    });
    dialog.querySelector('[data-rd-close]').addEventListener('click',()=>dialog.close());
    dialog.addEventListener('close',()=>dialog._pembuka?.focus());
    return dialog;
  }
  panel('guide','rd-panduan','[data-rd-guide]');
  panel('actions','rd-actions','[data-rd-actions-open]');
  const exam=panel('exam','rd-exam','[data-rd-exam-open]');
  function fromURL() {
    const hash=location.hash;
    if(hash==='#pemeriksaan') {
      if(exam&&!exam.open)exam.showModal();
      else if(!exam){const fallback=akar.querySelector('[data-rd-exam-fallback]');if(fallback)fallback.open=true;}
      return;
    }
    const tab=hash.startsWith('#dk-')?hash.slice(4):new URL(location.href).searchParams.get('tab');
    const id={perhitungan:'rd-perhitungan',jejak:'rd-jejak',ringkasan:'rd-penerimaan'}[tab];
    if(id)akar.querySelector('#'+id).open=true;
  }
  addEventListener('hashchange',fromURL);addEventListener('popstate',fromURL);fromURL();
  akar.addEventListener('invalid',event=>{
    let parent=event.target.parentElement;
    while(parent&&parent!==akar){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}
  },true);
  // Logika tindakan lama ditambahkan di bawah tanpa mengubah payload,
  // konfirmasi respons, batas waktu, atau retensi isian saat gagal.
  akar.querySelectorAll('[data-rd-actions-content] form').forEach(form => {
    let sibuk=false;
    const pesan=document.createElement('p');pesan.className='pesan pesan--err';
    pesan.setAttribute('role','alert');pesan.hidden=true;form.append(pesan);
    form.addEventListener('submit',async e=>{
      e.preventDefault();if(sibuk)return;sibuk=true;pesan.hidden=true;
      const tombol=form.querySelector('button[type=submit]');tombol.disabled=true;
      const batas=new AbortController();const waktu=setTimeout(()=>batas.abort(),30000);
      try {
        const r=await fetch(form.action,{method:'POST',body:new URLSearchParams(new FormData(form)),credentials:'same-origin',signal:batas.signal});
        const url=new URL(r.url);const hapus=new URL(form.action).pathname.endsWith('/hapus');
        const ok=hapus?akar.dataset.kode+' dihapus permanen.':'Transaksi dibatalkan. Datanya tetap tersimpan.';
        const path=hapus?location.pathname.replace(/\/transaksi\/\d+$/,'/transaksi'):location.pathname;
        if(r.ok&&r.redirected&&url.origin===location.origin&&url.pathname===path&&url.searchParams.get('ok')===ok){
          if(!hapus){const kembali=new URL(location.href).searchParams.get('kembali');if(kembali)url.searchParams.set('kembali',kembali);}
          location.assign(url.pathname+url.search);return;
        }
        throw new Error(url.searchParams.get('err')||'Server belum mengonfirmasi penyimpanan. Periksa sesi dan status tiket terbaru sebelum mencoba kembali.');
      } catch(err) {
        pesan.textContent=(err.name==='TypeError'||err.name==='AbortError'?'Penyimpanan belum terkonfirmasi. Periksa tiket terbaru sebelum mencoba kembali.':err.message)+' Isian tetap tersedia di formulir ini.';
        pesan.hidden=false;
      } finally {clearTimeout(waktu);sibuk=false;tombol.disabled=false;}
    });
  });
})();

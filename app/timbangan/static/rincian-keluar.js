/* Tab hanya mengatur visibilitas; tidak mengambil atau mengirim transaksi. */
(() => {
  'use strict';
  const akar = document.querySelector('[data-detail-keluar], [data-detail-retur], [data-detail-masuk]');
  if (!akar || akar.dataset.siap) return;
  akar.dataset.siap = '1';
  const tabs = [...akar.querySelectorAll('[data-dk-tab]')];
  const panels = [...akar.querySelectorAll('[data-dk-panel]')];
  akar.querySelector('.dk-tabs').setAttribute('role', 'tablist');
  tabs.forEach(t => {t.setAttribute('role','tab');t.setAttribute('aria-controls','dk-'+t.dataset.dkTab);});
  panels.forEach(p => p.setAttribute('role','tabpanel'));
  function tampil(nama, simpan=false) {
    if (!tabs.some(t => t.dataset.dkTab === nama)) nama = tabs[0].dataset.dkTab;
    tabs.forEach(t => {const aktif=t.dataset.dkTab===nama;t.setAttribute('aria-selected',String(aktif));t.tabIndex=aktif?0:-1;});
    panels.forEach(p => {p.hidden=p.dataset.dkPanel!==nama;});
    if (simpan) {
      const url = new URL(location.href);
      url.searchParams.set('tab',nama);
      url.hash = '';
      history.replaceState(history.state,'',url);
    }
  }
  function dariURL() {
    const hash=location.hash;
    tampil(hash==='#pemeriksaan'?'jejak':hash.startsWith('#dk-')?hash.slice(4):new URL(location.href).searchParams.get('tab'));
  }
  tabs.forEach((t,i) => {
    t.addEventListener('click',e=>{e.preventDefault();tampil(t.dataset.dkTab,true);});
    t.addEventListener('keydown',e=>{
      let n;
      if(e.key==='ArrowRight')n=(i+1)%tabs.length;
      else if(e.key==='ArrowLeft')n=(i+tabs.length-1)%tabs.length;
      else if(e.key==='Home')n=0;else if(e.key==='End')n=tabs.length-1;else return;
      e.preventDefault();tampil(tabs[n].dataset.dkTab,true);tabs[n].focus();
    });
  });
  akar.querySelectorAll('[data-buka-jejak]').forEach(a=>a.addEventListener('click',()=>tampil('jejak')));
  akar.addEventListener('invalid',e=>{
    const panel=e.target.closest('[data-dk-panel]');if(panel)tampil(panel.dataset.dkPanel);
    let p=e.target.parentElement;while(p&&p!==akar){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}
  },true);
  addEventListener('hashchange',dariURL);addEventListener('popstate',dariURL);
  // Form lama, endpoint dan payload tetap sama. Gagal tidak meninggalkan
  // halaman sehingga alasan/konfirmasi tidak hilang. Tidak diantrikan ulang.
  akar.querySelectorAll('.dk-lanjutan form').forEach(form => {
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
  dariURL();
})();

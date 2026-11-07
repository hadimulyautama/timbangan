/* Tab hanya mengatur visibilitas; tidak mengambil atau mengirim transaksi. */
(() => {
  'use strict';
  const akar = document.querySelector('[data-detail-keluar], [data-detail-retur], [data-detail-masuk], [data-detail-transfer]');
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
  dariURL();
})();

/* Detail riwayat timbang bersama: progressive disclosure, bukan pengambilan data baru.
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
  const exam=panel('exam','rd-exam','[data-rd-exam-open]');
  function fromURL() {
    const hash=location.hash;
    if(hash==='#pemeriksaan') {
      if(exam&&!exam.open)exam.showModal();
      else if(!exam){const fallback=akar.querySelector('[data-rd-exam-fallback]');if(fallback)fallback.open=true;}
      return;
    }
    const tab=hash.startsWith('#dk-')?hash.slice(4):new URL(location.href).searchParams.get('tab');
    const id={muatan:'rd-muatan',perhitungan:'rd-perhitungan',jejak:'rd-jejak',ringkasan:akar.querySelector('#rd-ringkasan')?'rd-ringkasan':'rd-penerimaan'}[tab];
    const target=id&&akar.querySelector('#'+id);
    if(target)target.open=true;
  }
  addEventListener('hashchange',fromURL);addEventListener('popstate',fromURL);fromURL();
  akar.addEventListener('invalid',event=>{
    let parent=event.target.parentElement;
    while(parent&&parent!==akar){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}
  },true);
})();

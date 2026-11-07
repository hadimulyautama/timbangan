/* Panduan berbagi kerangka tampilan. Form GET asli tidak diintersep. */
(() => {
  const filter=document.querySelector('#rh-filters'),trigger=document.querySelector('[data-rh-filter]');
  if(filter&&trigger){
    trigger.hidden=false;filter.querySelector('summary').hidden=true;
    trigger.setAttribute('aria-controls',filter.id);
    const sync=()=>trigger.setAttribute('aria-expanded',String(filter.open));
    trigger.addEventListener('click',()=>{filter.open=!filter.open;sync();});
    filter.addEventListener('toggle',sync);sync();
  }
  const dialog=document.querySelector('#rh-panduan'),button=document.querySelector('[data-rh-guide]'),content=document.querySelector('[data-rh-guide-content]');
  if(!dialog||!button||!content||typeof dialog.showModal!=='function')return;
  dialog.querySelector('[data-rh-guide-slot]').append(content);
  document.querySelector('[data-rh-guide-fallback]').hidden=true;
  button.hidden=false;button.setAttribute('aria-controls',dialog.id);button.setAttribute('aria-haspopup','dialog');
  button.addEventListener('click',()=>dialog.showModal());
  dialog.querySelector('[data-rh-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>button.focus());
})();

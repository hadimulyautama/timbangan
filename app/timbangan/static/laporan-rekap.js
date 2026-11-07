/* Tata letak dan Panduan saja. Form GET, ekspor dan rincian tetap asli. */
(() => {
  const root=document.querySelector('[data-rekap-desain]');if(!root)return;
  const period=root.querySelector('[data-lr-period]');
  // Cadangan server selalu terbuka agar tanggal tetap dapat dipilih tanpa JS.
  if(matchMedia('(max-width:650px)').matches)period.open=false;
  const form=period.querySelector('form'),from=form.elements.namedItem('dari'),to=form.elements.namedItem('sampai');
  function validate(){to.setCustomValidity(from.value&&to.value&&from.value>to.value?'Tanggal Sampai harus sama atau setelah Dari.':'');}
  form.addEventListener('input',validate);form.addEventListener('change',validate);
  form.addEventListener('invalid',()=>{period.open=true;},true);
  const dialog=root.querySelector('#lr-panduan'),button=root.querySelector('[data-lr-guide]');
  if(typeof dialog.showModal!=='function')return;
  dialog.querySelector('[data-lr-guide-slot]').append(root.querySelector('[data-lr-guide-content]'));
  root.querySelector('[data-lr-guide-fallback]').hidden=true;
  button.hidden=false;button.setAttribute('aria-controls',dialog.id);button.setAttribute('aria-haspopup','dialog');
  button.addEventListener('click',()=>dialog.showModal());
  dialog.querySelector('[data-lr-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>button.focus());
})();

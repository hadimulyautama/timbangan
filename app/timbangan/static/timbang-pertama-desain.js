/* Peningkatan tampilan saja: form, antrean luring, payload dan layanan tetap.
 * Konten Panduan dipindahkan sebagai node asli; tidak ada salinan isian. */
(function () {
  'use strict';
  var page = document.querySelector('.tp-page');
  if (!page || page.dataset.tpSiap) return;
  page.dataset.tpSiap = '1';
  var guide = page.querySelector('#tp-panduan');
  var button = page.querySelector('[data-tp-guide]');
  var fallback = page.querySelector('[data-tp-guide-fallback]');
  if (guide && typeof guide.showModal === 'function') {
    page.querySelector('[data-tp-guide-slot]').append(page.querySelector('[data-tp-guide-content]'));
    fallback.hidden = true;
    button.hidden = false;
    button.setAttribute('aria-controls', guide.id);
    button.setAttribute('aria-haspopup', 'dialog');
    button.addEventListener('click', function () { guide.showModal(); });
    guide.querySelector('[data-tp-guide-close]').addEventListener('click', function () { guide.close(); });
    guide.addEventListener('close', function () { button.focus(); });
  }
  var time = page.querySelector('[name=waktu]');
  var label = page.querySelector('[data-tp-time-label]');
  function waktuTampil() {
    var value = time.value;
    if (!value) { label.textContent = 'Belum diisi'; return; }
    // datetime-local adalah jam lokal yang diketik; jangan ubah lewat UTC.
    var parts = value.split('T');
    var date = parts[0].split('-');
    label.textContent = date.reverse().join('/') + (parts[1] ? ' ' + parts[1] : '');
    label.setAttribute('datetime', value);
  }
  if (time && label) {
    time.addEventListener('input', waktuTampil);
    time.addEventListener('change', waktuTampil);
    page.addEventListener('draf-dipulihkan', waktuTampil);
    waktuTampil();
  }
})();

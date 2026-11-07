/* Susunan saja. Perhitungan, request, validasi, submit dan antrean luring
 * tetap milik formulir.js, app.js dan luring.js. */
(function () {
  'use strict';
  var page = document.querySelector('.tk-page');
  if (!page || page.dataset.tkSiap) return;
  page.dataset.tkSiap = '1';
  var guide = page.querySelector('#tk-panduan');
  var button = page.querySelector('[data-tk-guide]');
  if (guide && typeof guide.showModal === 'function') {
    page.querySelector('[data-tk-guide-slot]').append(page.querySelector('[data-tk-guide-content]'));
    page.querySelector('[data-tk-guide-fallback]').hidden = true;
    button.hidden = false;
    button.setAttribute('aria-controls', guide.id);
    button.setAttribute('aria-haspopup', 'dialog');
    button.addEventListener('click', function () { guide.showModal(); });
    guide.querySelector('[data-tk-guide-close]').addEventListener('click', function () { guide.close(); });
    guide.addEventListener('close', function () { button.focus(); });
  }
  var form = page.querySelector('.fw-form');
  var time = form.elements.waktu;
  var number = form.elements.nomor_acuan;
  function labels() {
    var value = time.value, parts = value.split('T');
    var label = page.querySelector('[data-tk-time-label]');
    label.textContent = value ? parts[0].split('-').reverse().join('/') + (parts[1] ? ' ' + parts[1] : '') : 'Belum diisi';
    if (value) label.setAttribute('datetime', value);
    var documentLabel = page.querySelector('[data-tk-document-number]');
    if (documentLabel && number) documentLabel.textContent = number.value || 'Belum diisi';
  }
  form.addEventListener('input', labels);
  form.addEventListener('change', labels);
  page.addEventListener('draf-dipulihkan', labels);
  labels();
  var panel = page.querySelector('[data-fw-hasil]');
  function hierarchy() {
    // Jangan menyentuh pesan kesalahan/ketidakpastian maupun angka server.
    var heading = panel.querySelector('h2');
    if (heading && heading.textContent === 'Pratinjau perhitungan') heading.textContent = 'Hasil penimbangan';
    panel.querySelectorAll('p,small').forEach(function (node) {
      if (['Pratinjau · belum tersimpan atau diverifikasi Produksi.',
           'Belum menjadi hasil resmi. Backend menghitung dan menjalankan seluruh validasi saat disimpan.'].includes(node.textContent)) node.remove();
    });
    var total = panel.querySelector('.fw-preview-row--total');
    if (heading && total && heading.nextElementSibling !== total) heading.after(total);
  }
  hierarchy();
  new MutationObserver(hierarchy).observe(panel, { childList: true, subtree: true });
})();

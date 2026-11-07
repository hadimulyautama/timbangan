/* Susunan koreksi saja: tidak menghitung, mengirim atau mengganti payload.
 * Node asli dipindahkan dalam form yang sama; handler koreksi.js tetap. */
(function () {
  'use strict';
  var page = document.querySelector('.kc-page');
  if (!page || page.dataset.kcSiap) return;
  page.dataset.kcSiap = '1';
  page.querySelector('.cf-review').append(page.querySelector('.cf-actions'));
  var guide = page.querySelector('#kc-panduan'), button = page.querySelector('[data-kc-guide]');
  if (guide && typeof guide.showModal === 'function') {
    page.querySelector('[data-kc-guide-slot]').append(page.querySelector('[data-kc-guide-content]'));
    page.querySelector('[data-kc-guide-fallback]').hidden = true;
    button.hidden = false; button.setAttribute('aria-controls', guide.id); button.setAttribute('aria-haspopup', 'dialog');
    button.addEventListener('click', function () { guide.showModal(); });
    guide.querySelector('[data-kc-guide-close]').addEventListener('click', function () { guide.close(); });
    guide.addEventListener('close', function () { button.focus(); });
  }
  var panel = page.querySelector('[data-cf-hasil]');
  function hierarchy() {
    var values = panel.querySelector('.cf-values');
    if (!values) return; // Pesan gagal/jaringan/versi tetap terlihat utuh.
    if (page.dataset.kcOpen === 'true') {
      if (values.closest('.kc-calculation')) return;
      var details = document.createElement('details'); details.className = 'kc-calculation';
      var summary = document.createElement('summary'); summary.textContent = 'Status perhitungan'; details.append(summary);
      var heading = values.previousElementSibling, note = values.nextElementSibling;
      values.before(details);
      if (heading && heading.tagName === 'H2') details.append(heading);
      details.append(values);
      if (note && note.tagName === 'SMALL') details.append(note);
    } else if (!panel.querySelector('.kc-result-pair')) {
      var rows = Array.from(values.children);
      var before = rows.find(function (r) { return r.querySelector('span')?.textContent === 'Berat barang sebelum koreksi'; });
      var after = rows.find(function (r) { return r.querySelector('span')?.textContent === 'Berat barang setelah koreksi'; });
      if (before && after) {
        var pair = document.createElement('div'); pair.className = 'kc-result-pair'; pair.append(before, after); values.before(pair);
      }
    }
  }
  hierarchy(); new MutationObserver(hierarchy).observe(panel, { childList: true, subtree: true });
  page.addEventListener('invalid', function (event) {
    var node = event.target.parentElement;
    while (node && node !== page) { if (node.tagName === 'DETAILS') node.open = true; node = node.parentElement; }
  }, true);
})();

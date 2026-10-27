/* Koreksi tidak masuk antrean baru dan tidak dikirim ulang otomatis.
 * Nilai/selisih pratinjau seluruhnya dibaca dari backend; versi tetap versi
 * yang dibawa halaman saat dibuka, termasuk ketika terjadi konflik. */
(function () {
  'use strict';
  var page = document.querySelector('.cf-page');
  if (!page || page.dataset.cfTerpasang) return;
  page.dataset.cfTerpasang = '1';
  var form = page.querySelector('[data-correction-form]');
  var forms = Array.from(page.querySelectorAll('form'));
  var amanKeluar = false, sibuk = false, tujuanBatal = null;
  function cap(f) { return JSON.stringify(Array.from(f.querySelectorAll('input,select,textarea')).map(function (e) { return [e.name, e.type === 'checkbox' ? e.checked : e.value]; })); }
  var awal = forms.map(cap);
  function kotor() { return forms.some(function (f, i) { return cap(f) !== awal[i]; }); }
  page.querySelectorAll('.grup').forEach(function (g, i) {
    var label = g.querySelector('.lbl');
    if (!label) return;
    if (!label.id) label.id = 'cf-label-' + i;
    g.querySelectorAll('input:not([type=hidden]),select,textarea').forEach(function (el) { el.setAttribute('aria-labelledby', label.id); });
  });
  page.addEventListener('invalid', function (e) {
    var d = e.target.closest('details'); if (d) d.open = true;
    e.target.setAttribute('aria-invalid', 'true');
  }, true);
  page.addEventListener('input', function (e) { if (e.target.validity && e.target.validity.valid) e.target.removeAttribute('aria-invalid'); });
  window.addEventListener('beforeunload', function (e) {
    if (!amanKeluar && (kotor() || sibuk)) { e.preventDefault(); e.returnValue = ''; }
  });
  var dialog = page.querySelector('[data-cf-discard]');
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target === '_blank' || e.ctrlKey || e.metaKey || e.shiftKey || a.hash && a.pathname === location.pathname || amanKeluar || !kotor()) return;
    e.preventDefault(); tujuanBatal = a.href; dialog.showModal();
  }, true);
  page.querySelector('[data-cf-keep]').addEventListener('click', function () { dialog.close(); });
  page.querySelector('[data-cf-leave]').addEventListener('click', function () { amanKeluar = true; location.assign(tujuanBatal); });
  var error = page.querySelector('[data-cf-error]');
  function gagal(teks, belumPasti) {
    error.hidden = false; error.textContent = teks;
    if (belumPasti) {
      error.append(document.createTextNode(' Periksa tiket terbaru sebelum mencoba lagi. '));
      var a = document.createElement('a'); a.href = page.querySelector('[data-cf-cancel]').href;
      a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'Buka tiket terbaru'; error.append(a);
    }
    error.tabIndex = -1; error.focus();
  }
  forms.forEach(function (f) {
    f.addEventListener('submit', async function (e) {
      e.preventDefault(); if (sibuk) return;
      sibuk = true; error.hidden = true;
      var buttons = Array.from(page.querySelectorAll('button[type=submit]'));
      buttons.forEach(function (b) { b.disabled = true; });
      var controller = new AbortController(); var timer = setTimeout(function () { controller.abort(); }, 20000);
      try {
        var r = await fetch(f.action, { method: 'POST', body: new URLSearchParams(new FormData(f)), credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
        var url = new URL(r.url); var pesan = url.searchParams.get('err');
        if (pesan) { gagal(pesan, false); return; }
        var target = new URL(page.querySelector('[data-cf-cancel]').href);
        if (r.ok && url.origin === location.origin && url.pathname === target.pathname && url.searchParams.has('ok')) {
          amanKeluar = true; location.assign(url.href); return;
        }
        gagal(r.status === 401 || url.pathname.endsWith('/masuk') ? 'Sesi perlu diperiksa. Isian tetap ada; masuk kembali sebelum menyimpan.' : 'Server belum mengonfirmasi koreksi. Isian tetap ada.', true);
      } catch (_) { gagal('Penyimpanan belum terkonfirmasi. Isian dan versi tiket tetap ada.', true); }
      finally { clearTimeout(timer); sibuk = false; buttons.forEach(function (b) { b.disabled = false; }); }
    });
  });
  var panel = page.querySelector('[data-cf-hasil]');
  var timer, request, urutan = 0;
  function pesan(teks) {
    panel.replaceChildren(); var h = document.createElement('h2'); h.textContent = 'Perubahan yang akan disimpan';
    var p = document.createElement('p'); p.textContent = teks; panel.append(h, p);
  }
  function tampil(data) {
    pesan(data.perubahan.length ? 'Hanya nilai yang berubah ditampilkan.' : 'Belum ada perubahan nilai.');
    data.perubahan.forEach(function (r) {
      var d = document.createElement('div'); d.className = 'cf-change';
      var l = document.createElement('strong'); l.textContent = r.label;
      var v = document.createElement('span'); v.textContent = r.lama + ' → ' + r.baru; d.append(l, v); panel.append(d);
    });
    var h = document.createElement('h2'); h.textContent = 'Pratinjau perhitungan'; panel.append(h);
    var box = document.createElement('div'); box.className = 'cf-values';
    Object.keys(data.nilai).forEach(function (k) {
      var row = document.createElement('div'); row.className = 'cf-row';
      var l = document.createElement('span'); l.textContent = k;
      var v = document.createElement('strong'); v.textContent = data.nilai[k]; row.append(l, v); box.append(row);
    });
    panel.append(box);
    var note = document.createElement('small'); note.className = 'bantu';
    note.textContent = (data.terbuka ? 'Tiket tetap terbuka. Hasil akhir belum tersedia sampai timbang kedua. ' : '') + 'Pratinjau belum disimpan. Hasil resmi, izin, versi dan integrasi diperiksa kembali oleh server.';
    panel.append(note);
  }
  async function tinjau() {
    var id = ++urutan; if (request) request.abort();
    if (!navigator.onLine) { pesan('Pratinjau membutuhkan jaringan. Isian dan versi tiket tetap ada.'); return; }
    request = new AbortController(); var batas = setTimeout(function () { if (id === urutan) request.abort(); }, 15000);
    try {
      var r = await fetch(form.dataset.cfPreview, { method: 'POST', body: new URLSearchParams(new FormData(form)), credentials: 'same-origin', cache: 'no-store', signal: request.signal });
      if (!/application\/json/i.test(r.headers.get('content-type') || '')) throw new Error('Pratinjau belum tersedia; periksa sesi atau koneksi.');
      var d = await r.json(); if (id !== urutan) return;
      if (!r.ok || !d.tersedia) { pesan(d.pesan || 'Pratinjau belum tersedia.'); return; }
      tampil(d);
    } catch (e) { if (id === urutan) pesan('Pratinjau belum terkonfirmasi. Isian tetap ada; periksa sesi atau koneksi.'); }
    finally { clearTimeout(batas); }
  }
  function jadwalkan(e) {
    if (e && e.target && e.target.name === 'alasan') return;
    clearTimeout(timer); ++urutan; if (request) request.abort(); pesan('Memperbarui pratinjau…'); timer = setTimeout(tinjau, 400);
  }
  form.addEventListener('input', jadwalkan); form.addEventListener('change', jadwalkan);
  window.addEventListener('online', jadwalkan); window.addEventListener('offline', jadwalkan);
  jadwalkan();
})();

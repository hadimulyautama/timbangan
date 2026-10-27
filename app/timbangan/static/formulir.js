/* Hanya tampilan: tidak mengirim penimbangan atau mengubah antrean/draf.
 * Seluruh angka pratinjau dihitung endpoint baca saja dengan logic.hitung. */
(function () {
  'use strict';
  var page = document.querySelector('.fw-page');
  if (!page || page.dataset.fwTerpasang) return;
  page.dataset.fwTerpasang = '1';
  function buka(el) {
    var parent = el && el.parentElement;
    while (parent && parent !== page) {
      if (parent.tagName === 'DETAILS') parent.open = true;
      parent = parent.parentElement;
    }
  }
  page.querySelectorAll('input,select,textarea').forEach(function (el, index) {
    if (el.type === 'hidden' || el.type === 'radio' || el.type === 'checkbox') return;
    var group = el.closest('.grup');
    var label = group && group.querySelector('.lbl');
    if (label) {
      if (!label.id) label.id = 'fw-label-' + index;
      el.setAttribute('aria-labelledby', label.id);
    }
  });
  page.addEventListener('invalid', function (e) {
    buka(e.target);
    e.target.setAttribute('aria-invalid', 'true');
    var group = e.target.closest('.grup');
    if (group) {
      var message = group.querySelector('[data-fw-error]');
      if (!message) {
        message = document.createElement('p');
        message.dataset.fwError = '1';
        message.className = 'fw-field-error';
        message.setAttribute('role', 'alert');
        group.append(message);
      }
      message.textContent = e.target.validationMessage;
    }
  }, true);
  page.addEventListener('input', function (e) {
    if (e.target.validity && e.target.validity.valid) {
      e.target.removeAttribute('aria-invalid');
      var group = e.target.closest('.grup');
      var error = group && group.querySelector('[data-fw-error]');
      if (error) error.remove();
    }
  });
  // Pesan gagal antrean tetap milik luring.js; bagian opsional dibuka agar
  // isian yang harus diperiksa tidak tersembunyi setelah respons server.
  function periksaPesan() {
    var status = document.querySelector('[data-status-draf]');
    if (status && /Server belum menyimpan|Periksa pesan|gagal|ditolak/i.test(status.textContent)) {
      page.querySelectorAll('[data-fw-opsional]').forEach(function (d) { d.open = true; });
    }
  }
  var observer = new MutationObserver(periksaPesan);
  var main = page.closest('main');
  if (main) observer.observe(main, { childList: true, subtree: true, characterData: true });

  var form = page.querySelector('[data-fw-preview]');
  if (!form) return;
  var panel = form.querySelector('[data-fw-hasil]');
  var timer, request, urutan = 0, isianTerakhir = null;
  var menekan = false, gambarTertunda, batasTekanan;
  function tulis(isi, id) {
    if (id !== urutan) return;
    // Blur/change dan balasan server dapat terjadi antara sentuhan pertama
    // dan click. Mengubah tinggi panel di situ memindahkan tombol dari jari,
    // sehingga click jatuh ke elemen lain dan form tak pernah dikirim.
    if (menekan) { gambarTertunda = { isi: isi, id: id }; return; }
    panel.replaceChildren(isi);
  }
  function lepaskan() {
    clearTimeout(batasTekanan); menekan = false;
    var gambar = gambarTertunda; gambarTertunda = null;
    if (gambar) tulis(gambar.isi, gambar.id);
  }
  form.addEventListener('pointerdown', function (e) {
    var tombol = e.target.closest('button[type="submit"]');
    if (!tombol || tombol.form !== form) return;
    clearTimeout(batasTekanan); menekan = true;
  }, true);
  document.addEventListener('click', function () {
    // Default action click masih harus menjalankan validasi/submit dulu.
    if (menekan) setTimeout(lepaskan, 0);
  }, true);
  document.addEventListener('pointerup', function () {
    // Cadangan bila penunjuk dilepas di luar tombol dan tak ada click.
    // Tunggu compatibility click Safari selesai; tidak menunda penyimpanan.
    if (menekan) batasTekanan = setTimeout(lepaskan, 500);
  }, true);
  document.addEventListener('pointercancel', lepaskan, true);
  function isiPesan(teks) {
    var isi = document.createDocumentFragment();
    var title = document.createElement('h2'); title.textContent = 'Pratinjau perhitungan';
    var message = document.createElement('p'); message.textContent = teks;
    var note = document.createElement('small');
    note.textContent = 'Belum menjadi hasil resmi. Backend menghitung dan menjalankan seluruh validasi saat disimpan.';
    isi.append(title, message, note); return isi;
  }
  function pesan(teks) {
    tulis(isiPesan(teks), urutan);
  }
  async function tinjau() {
    var id = ++urutan;
    if (request) request.abort();
    if (!form.elements.berat_kg.value.trim()) { pesan('Isi berat timbang kedua untuk melihat pratinjau.'); return; }
    if (!navigator.onLine) { pesan('Pratinjau membutuhkan jaringan. Isian tetap tersedia; penyimpanan luring mengikuti antrean aplikasi.'); return; }
    request = new AbortController();
    var batas = setTimeout(function () { if (id === urutan && request) request.abort(); }, 15000);
    pesan('Menghitung pratinjau di server…');
    try {
      var r = await fetch(form.dataset.fwPreview, {
        method: 'POST', body: new URLSearchParams(new FormData(form)),
        credentials: 'same-origin', cache: 'no-store', signal: request.signal
      });
      if (!/application\/json/i.test(r.headers.get('content-type') || '')) throw new Error('Pratinjau belum tersedia. Periksa koneksi atau sesi Anda.');
      var hasil = await r.json();
      if (id !== urutan) return;
      if (!r.ok || !hasil.tersedia) { pesan(hasil.pesan || 'Pratinjau belum tersedia. Isian tetap tersimpan di layar.'); return; }
      var isi = isiPesan('Pratinjau · belum tersimpan atau diverifikasi Produksi.');
      Object.keys(hasil.nilai).forEach(function (label) {
        var row = document.createElement('div');
        row.className = 'fw-preview-row' + (label === 'Berat barang' ? ' fw-preview-row--total' : '');
        var name = document.createElement('span'); name.textContent = label;
        var value = document.createElement('strong'); value.textContent = hasil.nilai[label];
        row.append(name, value);isi.insertBefore(row, isi.lastElementChild);
      });
      if (!hasil.pembanding) {
        var tanpa = document.createElement('small');
        tanpa.textContent = 'Tanpa dokumen pembanding; selisih belum dapat dibandingkan.';
        isi.append(tanpa);
      }
      tulis(isi, id);
    } catch (e) {
      if (id !== urutan) return;
      pesan(e.name === 'AbortError' ? 'Pratinjau belum terkonfirmasi. Isian tetap tersedia; coba kembali setelah koneksi pulih.' : e.message);
    } finally { clearTimeout(batas); }
  }
  function jadwalkan(e) {
    var isian = new URLSearchParams(new FormData(form)).toString();
    // Input sudah menjadwalkan nilai ini. Change saat blur tidak boleh
    // menghapus hasil/memulai ulang request yang sama tepat saat klik simpan.
    var paksa = e && !['input', 'change'].includes(e.type);
    if (!paksa && isian === isianTerakhir) return;
    isianTerakhir = isian;
    clearTimeout(timer); ++urutan;
    if (request) request.abort();
    if (form.elements.berat_kg.value.trim()) pesan('Memperbarui pratinjau…');
    timer = setTimeout(tinjau, 450);
  }
  form.addEventListener('input', jadwalkan);
  form.addEventListener('change', jadwalkan);
  form.addEventListener('draf-dipulihkan', jadwalkan);
  form.addEventListener('submit', function () {
    // Preview adalah baca saja, bukan syarat menyimpan. Begitu validasi
    // browser lolos dan submit dimulai, hentikan permintaan/hasil lamanya.
    clearTimeout(timer); ++urutan; gambarTertunda = null;
    if (request) request.abort();
  });
  window.addEventListener('online', jadwalkan);
  window.addEventListener('offline', jadwalkan);
  jadwalkan();
})();

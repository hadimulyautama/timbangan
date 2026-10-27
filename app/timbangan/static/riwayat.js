/* Pilihan hapus hanya hidup pada halaman ini. Tidak menyimpan pilihan di
 * browser: perubahan filter/halaman tidak boleh mewarisi sasaran penghapusan. */
(function () {
  'use strict';
  var form = document.getElementById('form-hapus-massal');
  if (!form || form._riwayatSiap) return;
  form._riwayatSiap = true;
  var semua = form.querySelector('[data-pilih-semua]');
  var kotak = Array.from(form.querySelectorAll('[data-baris-pilih]'));
  var jumlah = form.querySelector('[data-jumlah-dipilih]');
  var tombol = form.querySelector('[data-tombol-hapus-massal]');
  function perbarui() {
    var n = kotak.filter(function (k) { return k.checked; }).length;
    if (jumlah) jumlah.textContent = n;
    if (tombol) tombol.disabled = n === 0;
    if (semua) { semua.checked = n > 0 && n === kotak.length; semua.indeterminate = n > 0 && n < kotak.length; }
  }
  form.addEventListener('change', function (e) {
    if (e.target === semua) kotak.forEach(function (k) { k.checked = semua.checked; });
    if (e.target === semua || e.target.matches('[data-baris-pilih]')) perbarui();
  });
  function resetPilihan() {
    kotak.forEach(function (k) { k.checked = false; });
    var konfirmasi = form.querySelector('[name=konfirmasi]');
    if (konfirmasi) konfirmasi.value = '';
    perbarui();
  }
  window.addEventListener('pageshow', resetPilihan);
  resetPilihan();
})();

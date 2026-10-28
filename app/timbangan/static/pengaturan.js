/* Bookmark lama menunjuk bagian tara kemasan pada halaman yang dulu panjang.
 * Fragmen tidak dikirim ke server: bawa ke kategori, pertahankan parameter. */
(function () {
  'use strict';
  // Dijalankan sebelum inisialisasi halaman, agar navigasi bookmark tidak
  // memutus pembacaan sesi/antrean yang baru dimulai pada WebKit.
  if (!location.pathname.endsWith('/pengaturan') || new URL(location.href).searchParams.get('bagian')) return;
  if (location.hash === '#tara-kemasan') {
    var tujuan = new URL(location.href);
    tujuan.searchParams.set('bagian', 'aturan');
    location.replace(tujuan.href);
  }
})();

/* Padanan gram hanya teks bantu. Geser titik desimal sebagai teks agar
 * 0,0858 kg tetap 85,8 gram, tanpa galat float atau perubahan input/payload.
 * Validasi dan penyimpanan tetap milik kemasan_tara.simpan (Decimal). */
(function () {
  'use strict';
  function gram(teks) {
    var s = String(teks).trim().replace(/_/g, '').replace(/,/g, '.');
    var m = /^([+-]?)(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?$/.exec(s);
    if (!m) return 'Padanan gram belum tersedia.';
    var bagian = m[2].split('.'), digit = bagian.join('');
    var posisi = bagian[0].length + Number(m[3] || 0) + 3;
    if (!Number.isFinite(posisi) || Math.abs(posisi) > 100) return 'Padanan gram belum tersedia.';
    if (posisi < 0) { digit = '0'.repeat(-posisi) + digit; posisi = 0; }
    if (posisi > digit.length) digit += '0'.repeat(posisi - digit.length);
    var utuh = (digit.slice(0, posisi) || '0').replace(/^0+(?=\d)/, '');
    var pecahan = digit.slice(posisi).replace(/0+$/, '');
    var tanda = m[1] === '-' && /[1-9]/.test(utuh + pecahan) ? '-' : '';
    return tanda + utuh.replace(/\B(?=(\d{3})+(?!\d))/g, '.') +
      (pecahan ? ',' + pecahan : '') + ' gram per karung';
  }
  function pasang() {
    document.querySelectorAll('[data-set-tara]').forEach(function (form) {
      if (form.dataset.gramSiap) return;
      form.dataset.gramSiap = '1';
      var input = form.elements.tara_per_karung_kg;
      var info = form.querySelector('[data-set-gram]');
      function tampil() { info.textContent = gram(input.value); }
      input.addEventListener('input', tampil);
      tampil();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', pasang, {once:true});
  else pasang();
})();

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

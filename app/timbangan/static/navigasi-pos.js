/* Hanya konteks navigasi baca; tidak menangani kiriman formulir. URL menyimpan
 * tab, pencarian, filter, dan halaman sehingga Back/reload tetap konsisten. */
(function () {
  'use strict';
  var path = '/timbangan/tiket';
  var key = 'tf.tiket.kembali';
  try {
    if (location.pathname === path) {
      sessionStorage.setItem(key, location.pathname + location.search);
    } else if (/^\/timbangan\/(tiket|partai)\/\d+$/.test(location.pathname)) {
      var lama = sessionStorage.getItem(key);
      var balik = document.querySelector('.bar a[aria-label="Kembali"]');
      if (balik && lama && (lama === path || lama.indexOf(path + '?') === 0)) {
        balik.href = lama;
      }
    }
  } catch (_) { /* browser Back tetap membawa URL yang sama */ }

  // Konteks Riwayat berada di URL, bukan pada pilihan hapus. Hanya tautan
  // baca ke tiket yang sama diteruskan; endpoint tulis/cetak fisik tak disentuh.
  var cocok = location.pathname.match(/^\/timbangan\/(?:transaksi|tiket|partai)\/(\d+)(?:\/(?:cetak|koreksi))?$/);
  if (!cocok) return;
  function riwayat(url) {
    if (!url) return null;
    try {
      var u = new URL(url, location.origin);
      return u.origin === location.origin && ['/timbangan/transaksi', '/timbangan/laporan', '/timbangan/monitoring'].includes(u.pathname) ? u.pathname + u.search : null;
    } catch (_) { return null; }
  }
  var kembali = riwayat(new URLSearchParams(location.search).get('kembali'));
  if (!kembali && document.referrer) {
    var sumber = new URL(document.referrer);
    if (sumber.origin === location.origin && sumber.pathname.match(new RegExp('/(?:transaksi|tiket|partai)/' + cocok[1] + '(?:/|$)'))) {
      kembali = riwayat(sumber.searchParams.get('kembali'));
    }
  }
  if (!kembali) return;
  var tombol = document.querySelector('.bar a[aria-label="Kembali"]');
  if (tombol) tombol.href = kembali;
  document.querySelectorAll('main a[href]').forEach(function (a) {
    var u = new URL(a.href, location.origin);
    if (u.origin !== location.origin) return;
    if (!u.pathname.match(new RegExp('^/timbangan/(?:transaksi|tiket|partai)/' + cocok[1] + '(?:/(?:cetak|koreksi))?$'))) return;
    u.searchParams.set('kembali', kembali);
    a.href = u.pathname + u.search + u.hash;
  });
})();

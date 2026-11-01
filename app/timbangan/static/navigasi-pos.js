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

/* Umpan balik segera untuk navigasi/formulir native; tidak mencegat simpan. */
(function () {
  'use strict';
  var status = null, timer = null;
  function selesai() {
    if (timer) clearTimeout(timer);
    timer = null;
    if (status) status.remove();
    status = null;
  }
  function tampil(tulisan) {
    selesai();
    status = document.createElement('div');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;padding:8px 16px;background:#174c41;color:#fff;text-align:center;font:500 14px/1.5 system-ui;pointer-events:none';
    status.textContent = tulisan;
    document.body.appendChild(status);
    timer = setTimeout(function () {
      if (status) status.textContent = 'Respons belum diterima. Periksa hasil sebelum mengirim ulang.';
    }, 15000);
  }
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target || a.hasAttribute('download') || a.hasAttribute('data-unduh')) return;
    var href = a.getAttribute('href');
    if (!href || href.charAt(0) === '#') return;
    var url = new URL(a.href, location.href);
    if (url.origin !== location.origin || /\.(pdf|csv)(?:$|[?#])/.test(url.href)) return;
    if (url.pathname === location.pathname && url.search === location.search && url.hash) return;
    tampil('Membuka halaman…');
  });
  document.addEventListener('submit', function (e) {
    if (e.defaultPrevented || e.target.target) return;
    tampil((e.target.method || 'get').toLowerCase() === 'get' ? 'Memuat hasil…' : 'Menyimpan…');
  });
  window.addEventListener('pageshow', selesai);
})();

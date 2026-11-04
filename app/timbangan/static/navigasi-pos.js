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
  var status = null, timer = null, kerangka = null, disentuh = false, pulihkan = [], urutan = 0;
  document.addEventListener('input', function (e) {
    if (e.target.form && e.target.form.method.toLowerCase() !== 'get') disentuh = true;
  }, true);
  function selesai() {
    urutan++;
    if (timer) clearTimeout(timer);
    timer = null;
    if (status) status.remove();
    status = null;
    if (kerangka) kerangka.remove();
    kerangka = null;
    document.body.classList.remove('tf-halaman-menunggu');
    pulihkan.forEach(function (fn) { fn(); }); pulihkan = [];
  }
  function bukaKerangka(url, nama) {
    var main = document.querySelector('main.isi');
    // Siklus hidup formulir, draf luring, dan cetak tetap milik navigasi
    // browser. Jangan membongkar DOM atau menjalankan ulang app.js lewat AJAX.
    if (!main || disentuh || document.body.matches('.tf-formulir,.tf-koreksi')) return false;
    selesai();
    kerangka = document.createElement('section');
    kerangka.className = 'tf-kerangka'; kerangka.setAttribute('aria-busy', 'true');
    kerangka.innerHTML = '<h1></h1><p role="status" aria-live="polite">Memuat data…</p><div aria-hidden="true"><i></i><i></i><i></i></div>';
    // Kerangka sudah menjadi umpan balik perpindahan. Jangan menambahkan
    // snapshot animasi native yang bisa kedaluwarsa saat datanya terlambat.
    var gaya = document.createElement('style');
    gaya.textContent = '@view-transition { navigation: none; }';
    kerangka.appendChild(gaya);
    kerangka.querySelector('h1').textContent = nama || 'Halaman';
    main.parentNode.appendChild(kerangka);
    var inert = main.inert, hidden = main.getAttribute('aria-hidden');
    main.inert = true; main.setAttribute('aria-hidden', 'true');
    pulihkan.push(function () { main.inert = inert; if (hidden === null) main.removeAttribute('aria-hidden'); else main.setAttribute('aria-hidden', hidden); });
    var title = document.querySelector('.bar__judul');
    if (title) { var lama = title.textContent; title.textContent = nama || 'Halaman'; pulihkan.push(function () { title.textContent = lama; }); }
    document.querySelectorAll('#menu-timbang a[href],.tf-bottom a[href]').forEach(function (a) {
      var lamaClass = a.className, lamaAria = a.getAttribute('aria-current');
      var aktif = a.pathname === url.pathname || a.pathname !== '/timbangan/' && url.pathname.indexOf(a.pathname + '/') === 0;
      a.classList.toggle('aktif', aktif);
      if (aktif) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
      pulihkan.push(function () { a.className = lamaClass; if (lamaAria === null) a.removeAttribute('aria-current'); else a.setAttribute('aria-current', lamaAria); });
    });
    document.body.classList.add('tf-halaman-menunggu');
    document.body.classList.remove('pd-drawer-open');
    var menu = document.querySelector('.pd-menu'); if (menu) menu.setAttribute('aria-expanded', 'false');
    timer = setTimeout(function () {
      if (!kerangka) return;
      kerangka.querySelector('p').textContent = 'Data belum diterima. Periksa koneksi Anda.';
      var batal = document.createElement('button'); batal.type = 'button'; batal.textContent = 'Kembali ke halaman sebelumnya';
      batal.addEventListener('click', selesai); kerangka.appendChild(batal);
    }, 15000);
    return true;
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
    if (url.pathname.indexOf('/timbangan/') !== 0 || /\/(masuk|keluar)$/.test(url.pathname) || url.hash) return;
    if (url.pathname === location.pathname && url.search === location.search) return;
    if (bukaKerangka(url, a.textContent.trim().replace(/\s+/g, ' ').slice(0, 90))) {
      e.preventDefault();
      var nomor = ++urutan;
      // Beri browser satu frame untuk menggambar sebelum navigasi native
      // dapat membekukan dokumen lama saat menunggu respons jaringan.
      requestAnimationFrame(function () { requestAnimationFrame(function () {
        if (nomor === urutan) location.assign(url.href);
      }); });
      return;
    }
    tampil('Membuka halaman…');
  });
  document.addEventListener('submit', function (e) {
    if (e.defaultPrevented || e.target.target) return;
    tampil((e.target.method || 'get').toLowerCase() === 'get' ? 'Memuat hasil…' : 'Menyimpan…');
  });
  window.addEventListener('pageshow', selesai);
})();

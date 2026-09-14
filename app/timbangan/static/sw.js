/* Service worker pos timbang.
 *
 * Yang di-cache HANYA kerangka aplikasi — CSS, JS, ikon, dan satu halaman
 * cadangan. Data timbangan TIDAK PERNAH di-cache: menampilkan angka
 * timbangan basi di pos timbang lebih berbahaya daripada menampilkan
 * pesan "tidak ada jaringan".
 */
/* VERSI datang dari alamat pendaftaran (`/timbangan/sw.js?v=40`), yaitu
 * `web.VERSI` server — bukan angka yang ditulis tangan di sini. Dulu
 * 'timbangan-v29' berdiri sendiri dan bisa menyimpang dari VERSI server:
 * dua sumber kebenaran untuk satu hal. */
var VERSI = 'timbangan-v' + (new URL(self.location.href).searchParams.get('v') || '0');
var PREFIX = '/timbangan';
var V = '?v=' + VERSI.slice('timbangan-v'.length);

// Alamatnya bercap versi, persis seperti yang diminta halaman — tanpa cap,
// simpanan awal tak pernah cocok dengan permintaan mana pun.
var RANGKA = [
  PREFIX + '/static/app.css' + V,
  PREFIX + '/static/app.js' + V,
  PREFIX + '/static/ikon.svg' + V,
  PREFIX + '/static/ikon-180.png' + V,
  PREFIX + '/static/ikon-192.png' + V,
  PREFIX + '/static/ikon-512.png' + V,
  PREFIX + '/static/manifest.json' + V,
  PREFIX + '/luring'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(VERSI)
      .then(function (c) { return c.addAll(RANGKA); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (nama) {
      return Promise.all(nama.map(function (n) {
        return n === VERSI ? null : caches.delete(n);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') { return; }

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) { return; }

  // Kerangka: dari cache dulu, cepat dan tahan sinyal buruk.
  if (url.pathname.indexOf(PREFIX + '/static/') === 0) {
    e.respondWith(
      caches.match(req).then(function (tersimpan) {
        return tersimpan || fetch(req).then(function (r) {
          var salinan = r.clone();
          caches.open(VERSI).then(function (c) { c.put(req, salinan); });
          return r;
        });
      })
    );
    return;
  }

  // Halaman: selalu dari jaringan. Gagal → halaman luring, bukan data basi.
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req).catch(function () {
        return caches.match(PREFIX + '/luring');
      })
    );
  }
});

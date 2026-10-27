/* Service worker pos timbang.
 *
 * Kerangka dan cadangan luring selalu tersedia. Hanya formulir timbang
 * yang pernah dibuka ikut disimpan per akun/versi untuk pemulihan draf.
 * Daftar tiket, riwayat dan laporan tetap dibaca dari server.
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
  PREFIX + '/static/komponen-portal.css' + V,
  PREFIX + '/static/komponen-portal.js' + V,
  PREFIX + '/static/teraflow-logo.png' + V,
  PREFIX + '/static/teraflow.css' + V,
  PREFIX + '/static/beranda-tiket.css' + V,
  PREFIX + '/static/navigasi-pos.js' + V,
  PREFIX + '/static/luring.js' + V,
  PREFIX + '/static/luring.css' + V,
  PREFIX + '/static/riwayat.css' + V,
  PREFIX + '/static/riwayat.js' + V,
  PREFIX + '/static/laporan.css' + V,
  PREFIX + '/static/pemeriksaan.js' + V,
  PREFIX + '/static/cetak.css' + V,
  PREFIX + '/static/cetak.js' + V,
  PREFIX + '/static/rincian-keluar.css' + V,
  PREFIX + '/static/rincian-keluar.js' + V,
  PREFIX + '/static/formulir.css' + V,
  PREFIX + '/static/formulir.js' + V,
  PREFIX + '/static/koreksi.css' + V,
  PREFIX + '/static/koreksi.js' + V,
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
        return n === VERSI || n.indexOf(VERSI + '-form-') === 0 ? null : caches.delete(n);
      }));
    }).then(pulihkanFormTerbuka).then(function () { return self.clients.claim(); })
  );
});

// Hanya HTML dari server yang boleh menjadi salinan pemulihan, tanpa nilai
// yang diketik di DOM. Dipakai navigasi dan serah-terima worker saat deploy.
async function simpanFormServer(r, alamat) {
  try {
  if (r.ok && r.headers.get('content-type')?.includes('text/html')) {
    var html = await r.clone().text();
    var akun = html.match(/data-akun-id="(\d+)"/);
    if (akun) {
      var state = await caches.open(VERSI);
      var lama = await state.match(PREFIX + '/__akun-luring');
      if (lama && await lama.text() !== akun[1]) await hapusForm();
      await state.put(PREFIX + '/__akun-luring', new Response(akun[1]));
      var versiHtml = html.match(/data-versi="(\d+)"/);
      if (html.includes('data-simpan-luring') && versiHtml) {
        // Navigasi pertama sesudah deploy masih ditangani worker lama.
        // Siapkan salinan HTML di cache VERSI HTML, bukan versi worker
        // lama, agar activate worker baru tidak membuang satu-satunya
        // formulir yang bisa memulihkan draf saat jaringan langsung putus.
        // Tetap hanya respons server sah, per akun, tanpa menyalin isian
        // DOM atau mengirim antrean. Aturan keluar/ganti akun tetap sama.
        var tujuanVersi = 'timbangan-v' + versiHtml[1];
        var stateBaru = await caches.open(tujuanVersi);
        var akunBaru = await stateBaru.match(PREFIX + '/__akun-luring');
        if (akunBaru && await akunBaru.text() !== akun[1]) await hapusForm();
        await stateBaru.put(PREFIX + '/__akun-luring', new Response(akun[1]));
        var form = await caches.open(tujuanVersi + '-form-' + akun[1]);
        await form.put(alamat.origin + alamat.pathname, r.clone());
      }
    } else if (new URL(r.url).pathname === PREFIX + '/masuk') await keluar();
  }
  } catch (_) { /* cache penuh tidak mengganti respons jaringan yang sah */ }
}

async function pulihkanFormTerbuka() {
  var daftar = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  var jalur = new Set();
  for (var klien of daftar) {
    var alamat = new URL(klien.url);
    if (alamat.origin !== self.location.origin || !/^\/timbangan\/(timbang|jasa|tiket|partai)\/[^/]+(?:\/baru)?$/.test(alamat.pathname)) continue;
    if (jalur.has(alamat.pathname)) continue;
    jalur.add(alamat.pathname);
    var batas = new AbortController();
    var timer = setTimeout(function () { batas.abort(); }, 5000);
    try {
      // GET saja, tanpa query aksi. Sesi server menentukan akun yang sah;
      // redirect masuk membersihkan salinan milik sesi yang sudah berakhir.
      var r = await fetch(alamat.origin + alamat.pathname, { credentials: 'same-origin', cache: 'no-store', signal: batas.signal });
      await simpanFormServer(r, alamat);
    } catch (_) { /* draf/antrean IndexedDB tetap utuh bila jaringan putus */ }
    finally { clearTimeout(timer); }
  }
}

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

  // Hanya formulir timbang yang pernah dibuka disimpan, per akun dan versi.
  // Riwayat, laporan dan daftar tiket tetap network-only. Salinan formulir
  // diberi banner luring oleh aplikasi; isian terbaru dipulihkan dari draf.
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req).then(async function (r) {
        await simpanFormServer(r, url);
        return r;
      }).catch(async function () {
        var state = await caches.open(VERSI), akun = await state.match(PREFIX + '/__akun-luring');
        if (akun) {
          var form = await caches.open(VERSI + '-form-' + await akun.text());
          var saved = await form.match(url.origin + url.pathname);
          if (saved) {
            var salinan = (await saved.text()).replace('<body ', '<body data-salinan-luring="1" ');
            return new Response(salinan, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
          }
        }
        return caches.match(PREFIX + '/luring');
      })
    );
  }
});

async function hapusForm() {
  var keys = await caches.keys();
  await Promise.all(keys.filter(function (k) { return k.indexOf('-form-') >= 0; }).map(function (k) { return caches.delete(k); }));
}
async function keluar() {
  await hapusForm();
  await (await caches.open(VERSI)).delete(PREFIX + '/__akun-luring');
}
self.addEventListener('message', function (e) {
  if (e.data && e.data.jenis === 'keluar') e.waitUntil(keluar());
});

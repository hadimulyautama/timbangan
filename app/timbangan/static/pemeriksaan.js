/* Alur penutupan tetap POST server yang lama. Tidak masuk antrean luring:
 * respons yang hilang berarti belum terkonfirmasi, bukan pemeriksaan selesai. */
(function () {
  'use strict';
  var form = document.querySelector('[data-tutup-pemeriksaan]');
  if (!form || form.dataset.penjagaTerpasang) return;
  form.dataset.penjagaTerpasang = '1';
  var sibuk = false;
  var hasil = form.querySelector('[data-hasil-pemeriksaan]');
  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (sibuk) return;
    sibuk = true;
    hasil.hidden = true;
    var tombol = form.querySelector('button[type=submit]');
    var controller = new AbortController();
    var batas = setTimeout(function () { controller.abort(); }, 30000);
    tombol.disabled = true;
    try {
      var respons = await fetch(form.action, {
        method: 'POST', body: new URLSearchParams(new FormData(form)),
        credentials: 'same-origin', signal: controller.signal
      });
      var tujuan = new URL(respons.url);
      // Hanya redirect sukses dari endpoint yang sama yang mengonfirmasi
      // penutupan. Halaman login/galat HTML bukan bukti berhasil.
      if (respons.ok && tujuan.origin === location.origin &&
          tujuan.pathname === location.pathname &&
          tujuan.searchParams.get('ok') === 'Pemeriksaan ditutup.') {
        var kembali = new URLSearchParams(location.search).get('kembali');
        if (kembali) tujuan.searchParams.set('kembali', kembali);
        tujuan.hash = 'pemeriksaan';
        location.assign(tujuan.pathname + tujuan.search + tujuan.hash);
        return;
      }
      var pesan = tujuan.searchParams.get('err');
      throw new Error(pesan || 'Server belum mengonfirmasi penutupan. Periksa koneksi atau sesi Anda.');
    } catch (err) {
      hasil.textContent = (err.name === 'TypeError' || err.name === 'AbortError' ?
        'Penutupan belum terkonfirmasi. Periksa koneksi lalu muat ulang rincian untuk memeriksa status sebelum mencoba kembali.' : err.message) +
        ' Isian tetap tersedia di formulir ini.';
      hasil.hidden = false;
    } finally {
      clearTimeout(batas);
      sibuk = false;
      tombol.disabled = false;
    }
  });
})();

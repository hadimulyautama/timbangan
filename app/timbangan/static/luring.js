/* Draf dan kiriman timbang disimpan sebelum jaringan disentuh.
 * IndexedDB menyatukan perubahan antar-tab. Isi kiriman yang sedang dikirim
 * tidak berubah; tanda terima server mengikat kunci, akun, jalur dan isi.
 * Tidak ada sandi, foto, pembatalan, koreksi atau penghapusan dalam antrean.
 */
(function () {
  'use strict';
  if (window.timbanganLuring) return;
  var PREFIX = '/timbangan', DB = 'timbangan-luring-v2';
  var akun = document.body.dataset.akunId || '';
  var daftarForm = Array.from(document.querySelectorAll('form[data-simpan-luring]'));
  var siap = false, tertunda = true, berjalan = false, belumTersimpan = 0;
  var gagalSimpan = false;
  var panel, pesanGlobal = '', dbPromise;
  var halaman = uuid(), tab;
  daftarForm.forEach(function (f) { f.inert = true; });
  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, function (c) {
      return (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16);
    });
  }
  try {
    if (/\/timbangan\/(masuk|keluar)$/.test(location.pathname)) {
      localStorage.removeItem('tf.luring.akun');
      if (navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ jenis: 'keluar' });
      return;
    }
    if (akun) localStorage.setItem('tf.luring.akun', akun);
    else akun = localStorage.getItem('tf.luring.akun') || '';
    tab = sessionStorage.getItem('tf.luring.tab') || uuid();
    sessionStorage.setItem('tf.luring.tab', tab);
  } catch (_) { tab = uuid(); }
  if (!akun) return;

  function bukaDB() {
    if (!dbPromise) dbPromise = new Promise(function (resolve, reject) {
      var r = indexedDB.open(DB, 1);
      r.onupgradeneeded = function () {
        r.result.createObjectStore('kiriman', { keyPath: 'kunci' });
        r.result.createObjectStore('draf', { keyPath: 'id' });
      };
      r.onsuccess = function () { resolve(r.result); };
      r.onerror = function () { reject(r.error); };
      r.onblocked = function () { reject(new Error('Penyimpanan sedang terkunci.')); };
    });
    return dbPromise;
  }
  function transaksi(stores, mode, tugas) {
    return bukaDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(stores, mode), result;
        tx.oncomplete = function () { resolve(result); };
        tx.onerror = tx.onabort = function () { reject(tx.error || new Error('Penyimpanan gagal.')); };
        try { tugas(tx, function (v) { result = v; }); } catch (e) { tx.abort(); reject(e); }
      });
    });
  }
  function baca(store, key) {
    return transaksi([store], 'readonly', function (tx, done) {
      var r = key === undefined ? tx.objectStore(store).getAll() : tx.objectStore(store).get(key);
      r.onsuccess = function () { done(r.result); };
    });
  }
  function tulis(store, data) {
    return transaksi([store], 'readwrite', function (tx) { tx.objectStore(store).put(data); });
  }
  function ubah(kunci, fn) {
    return transaksi(['kiriman'], 'readwrite', function (tx, done) {
      var store = tx.objectStore('kiriman'), r = store.get(kunci);
      r.onsuccess = function () {
        try {
          if (!r.result) return;
          var item = fn(r.result);
          if (item) { store.put(item); done(item); }
        } catch (_) { tx.abort(); }
      };
    });
  }
  function tandaTerkirim(r) {
    // Bukan salinan isi kiriman: penanda kecil ini menjaga formulir lama dan
    // tab lain tetap mengenali kunci yang sudah dikonfirmasi. Tidak ada berat,
    // pihak, baris muatan, atau FormData yang disimpan di penanda ini.
    return { kunci: r.kunci, akun: r.akun, status: 'terkirim',
      tujuan: r.tujuan, peringatan: r.peringatan, pesan: r.pesan };
  }
  function hapusDrafSama(tx, r) {
    if (!r.drafId || !r.drafData) return;
    var store = tx.objectStore('draf'), req = store.get(r.drafId);
    req.onsuccess = function () {
      try {
        if (req.result && req.result.akun === r.akun && req.result.kunci === r.kunci && JSON.stringify(req.result.data) === JSON.stringify(r.drafData)) store.delete(r.drafId);
      } catch (_) { tx.abort(); }
    };
  }
  function bersihkanTerkirim() {
    // Migrasi ringan salinan versi lama, tanpa mengubah skema IndexedDB agar
    // tab lama tetap kompatibel. Antrean belum terkonfirmasi tidak disentuh.
    return transaksi(['kiriman', 'draf'], 'readwrite', function (tx) {
      var cursor = tx.objectStore('kiriman').openCursor();
      cursor.onsuccess = function () {
        try {
          var c = cursor.result; if (!c) return;
          if (c.value.akun === akun && c.value.status === 'terkirim') {
            var ringkas = tandaTerkirim(c.value);
            if (Object.keys(c.value).some(function (k) { return !Object.prototype.hasOwnProperty.call(ringkas, k); })) {
              hapusDrafSama(tx, c.value); c.update(ringkas);
            }
          }
          c.continue();
        } catch (_) { tx.abort(); }
      };
    });
  }
  function konfirmasiLokal(item, data) {
    // Isi kiriman dan draf snapshot yang sama dibersihkan atomik HANYA
    // sesudah server mengonfirmasi kunci. Draf lain/ketikan baru tetap utuh.
    return transaksi(['kiriman', 'draf'], 'readwrite', function (tx) {
      hapusDrafSama(tx, item);
      tx.objectStore('kiriman').put(tandaTerkirim({ kunci: item.kunci, akun: item.akun,
        tujuan: tujuanAman(data.tujuan), peringatan: data.peringatan, pesan: data.pesan }));
    });
  }
  function elemen(tag, text, cls) {
    var e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e;
  }
  function tujuanAman(url) {
    var u = new URL(url || PREFIX + '/', location.origin);
    return u.origin === location.origin && u.pathname.startsWith(PREFIX + '/') ? u.pathname + u.search : PREFIX + '/';
  }
  function tombol(text, fn) {
    var e = elemen('button', text, 'tbl halus kecil'); e.type = 'button'; e.addEventListener('click', fn); return e;
  }
  function tampilkanPesan(text) { pesanGlobal = text; gambar().catch(function () {}); }
  function gagalLokal() {
    gagalSimpan = true;
    daftarForm.forEach(function (f) { f.inert = false; f._luringSiap = true; });
    pesanGlobal = 'Penyimpanan perangkat gagal atau penuh. Isian masih di layar dan belum dikirim. Jangan tutup halaman; kosongkan ruang lalu coba simpan lagi.';
    if (panel) { panel.hidden = false; panel.textContent = pesanGlobal; }
  }
  function gambar() {
    return bersihkanTerkirim().then(function () { return Promise.all([baca('kiriman'), baca('draf')]); }).then(function (data) {
      var rows = data[0].filter(function (r) { return r.akun === akun; });
      var pending = rows.filter(function (r) { return r.status !== 'terkirim'; });
      tertunda = pending.length > 0;
      var drafts = data[1].filter(function (r) { return r.akun === akun; });
      document.querySelectorAll('[data-antrean]').forEach(function (e) {
        e.textContent = pending.length ? ' · ' + pending.length + ' kiriman belum dikonfirmasi server' : '';
      });
      if (!panel || !panel.isConnected) {
        panel = elemen('section', '', 'luring-panel'); panel.dataset.luringPanel = '1';
        panel.setAttribute('aria-label', 'Penyimpanan perangkat dan sinkronisasi');
        (document.querySelector('main') || document.body).prepend(panel);
      }
      panel.replaceChildren();
      panel.hidden = !pending.length && !drafts.length;
      if (pesanGlobal) { var status = elemen('p', pesanGlobal); status.setAttribute('role', 'status'); panel.append(status); }
      if (pending.length) {
        panel.append(elemen('strong', pending.length + ' kiriman tersimpan di perangkat · belum dikonfirmasi server'));
        panel.append(tombol('Coba sinkronkan', function () { sinkronkan(); }));
      }
      pending.forEach(function (r) {
        var row = elemen('div', '', 'luring-panel__baris');
        row.append(elemen('span', (r.status === 'periksa' ? 'Perlu diperiksa: ' : 'Menunggu sinkronisasi: ') + r.label + ' · ' + (r.pesan || 'Isian tetap tersimpan.')));
        var a = elemen('a', 'Buka isian', 'tf-link');
        a.href = tujuanAman(r.jalur) + '#kiriman=' + r.kunci; row.append(a); panel.append(row);
      });
      drafts.forEach(function (r) {
        if (pending.some(function (p) { return p.kunci === r.kunci; })) return;
        var a = elemen('a', 'Pulihkan draf: ' + r.label, 'tf-link');
        a.href = tujuanAman(r.jalur) + '#draf=' + encodeURIComponent(r.id); panel.append(a);
      });
      // Antrean generasi lama tidak mempunyai identitas akun/isi yang dapat
      // diverifikasi. Jangan mengirim sebagai orang lain atau membuangnya.
      try {
        if (JSON.parse(localStorage.getItem('timbangan-antrean') || '[]').length) {
          panel.hidden = false; panel.append(elemen('p', 'Ada kiriman lama yang perlu diperiksa Admin. Salinannya tetap disimpan di perangkat.'));
        }
      } catch (_) {}
    });
  }

  function dataForm(form) { return Array.from(new FormData(form).entries()).map(function (p) { return [p[0], String(p[1])]; }); }
  function pulihkan(form, pairs) {
    var weights = pairs.filter(function (p) { return p[0] === 'berat_kg'; });
    while (form.querySelector('#tambah-berat') && form.querySelectorAll('[name=berat_kg]').length < weights.length) form.querySelector('#tambah-berat').click();
    var names = new Set(pairs.map(function (p) { return p[0]; }));
    names.forEach(function (name) {
      var values = pairs.filter(function (p) { return p[0] === name; }).map(function (p) { return p[1]; });
      var fields = Array.from(form.elements).filter(function (e) { return e.name === name && !['submit','button','reset','file'].includes(e.type); });
      fields.forEach(function (e, i) {
        if (e.type === 'checkbox' || e.type === 'radio') e.checked = values.includes(e.value);
        else e.value = values[i] === undefined ? '' : values[i];
        // Komponen pihak lama melebur teks bebas ke pencarian. Pulihkan
        // sumber nilainya juga agar ketukan berikut tidak mengosongkannya.
        if (e.tagName === 'SELECT' && e.value && e.previousElementSibling && e.previousElementSibling.classList.contains('cari')) {
          e.previousElementSibling.querySelector('input').value = e.selectedOptions[0].textContent.trim();
        }
        if (name === 'pihak_nama' && e.value) {
          var select = form.querySelector('select[data-gabung]');
          if (select && select.previousElementSibling && select.previousElementSibling.classList.contains('cari')) {
            select.previousElementSibling.querySelector('input').value = e.value;
          }
        }
      });
    });
    form.dispatchEvent(new Event('draf-dipulihkan', { bubbles: true }));
  }
  function statusForm(form, text, tujuan) {
    var box = form.previousElementSibling;
    if (!box || !box.hasAttribute('data-status-draf')) {
      box = elemen('p', '', 'bantu'); box.dataset.statusDraf = '1'; box.setAttribute('role', 'status'); form.before(box);
    }
    box.textContent = text;
    if (tujuan) {
      var a = elemen('a', 'Buka hasil', 'tf-link'); a.href = tujuanAman(tujuan);
      box.append(document.createTextNode(' '), a);
    }
  }
  function snapshot(form) {
    var pairs = dataForm(form), key = pairs.find(function (p) { return p[0] === 'kunci'; });
    return { id: akun + ':' + tab + ':' + new URL(form.action).pathname,
      akun: akun, kunci: key && key[1], jalur: new URL(form.action).pathname,
      label: document.title.split('·').slice(1).join('·').trim(), data: pairs, updated: Date.now() };
  }
  function simpanDraf(form) {
    if (!form._luringSiap || form.inert) return Promise.resolve();
    var draft = snapshot(form); belumTersimpan++;
    return tulis('draf', draft).then(function () {
      gagalSimpan = false;
      statusForm(form, 'Draf tersimpan di perangkat · belum disimpan di server.'); return gambar();
    }).catch(function (e) { gagalLokal(); throw e; }).finally(function () { belumTersimpan--; });
  }
  function siapkanForm(form) {
    var id = akun + ':' + tab + ':' + new URL(form.action).pathname;
    var match = location.hash.match(/^#(draf|kiriman)=(.+)$/);
    var load = match ? baca(match[1] === 'draf' ? 'draf' : 'kiriman', decodeURIComponent(match[2])) : baca('draf', id);
    form._luringSiap = false;
    return load.then(function (saved) {
      form.inert = false;
      if (saved && saved.akun === akun && saved.status === 'terkirim') {
        form.inert = true; statusForm(form, saved.pesan || 'Kiriman sudah dikonfirmasi tersimpan di server.', saved.tujuan); return;
      }
      if (saved && saved.data && saved.akun === akun && saved.jalur === new URL(form.action).pathname) {
        pulihkan(form, saved.data); statusForm(form, 'Isian dipulihkan dari perangkat.');
        if (saved.status === 'menunggu' || saved.status === 'sesi') form.inert = true;
      }
      var key = form.querySelector('[name=kunci]');
      if (!key) throw new Error('Kunci formulir tidak tersedia.');
      return baca('kiriman', key.value).then(function (q) {
        if (q && q.akun === akun && q.status !== 'periksa') {
          form.inert = true; statusForm(form, q.status === 'terkirim' ? (q.pesan || 'Kiriman sudah dikonfirmasi tersimpan di server.') : 'Kiriman tersimpan di perangkat, menunggu konfirmasi server.', q.status === 'terkirim' ? q.tujuan : null);
        }
      });
    }).finally(function () { form._luringSiap = true; });
  }
  function kirimForm(form, submitter) {
    if (!form._luringSiap || form.inert) return;
    form.inert = true;
    var draft = snapshot(form), pairs = draft.data.slice();
    if (submitter && submitter.name) pairs.push([submitter.name, submitter.value]);
    var now = new Date().toISOString();
    var item = { kunci: draft.kunci, akun: akun, jalur: draft.jalur, label: draft.label,
      data: pairs, drafData: draft.data, created: Date.now(), waktu: now, offline: !navigator.onLine || document.body.hasAttribute('data-salinan-luring'),
      status: 'menunggu', drafId: draft.id, halaman: halaman, pesan: '' };
    // Kiriman dan draf disahkan dalam satu transaksi lokal. Quota/error tidak
    // boleh menghasilkan pesan tersimpan, mengosongkan layar atau mengirim.
    transaksi(['kiriman', 'draf'], 'readwrite', function (tx) {
      var store = tx.objectStore('kiriman'), r = store.get(item.kunci);
      r.onsuccess = function () {
        try {
          var lama = r.result;
          if (lama && lama.status !== 'periksa') return;
          if (lama) item.created = lama.created;
          store.put(item); tx.objectStore('draf').put(draft);
        } catch (_) { tx.abort(); }
      };
    }).then(function () {
      statusForm(form, 'Tersimpan di perangkat · menunggu konfirmasi server.');
      tampilkanPesan(navigator.onLine ? 'Mengirim kiriman yang tersimpan di perangkat…' : 'Tanpa jaringan. Kiriman aman di perangkat dan akan dicoba setelah jaringan kembali.');
      sinkronkan(item.kunci);
    }).catch(function () { form.inert = false; gagalLokal(); });
  }

  async function kirim(item) {
    var controller = new AbortController(), timeout = setTimeout(function () { controller.abort(); }, 20000);
    try {
      var response = await fetch(item.jalur, { method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'X-Timbangan-Kiriman': item.kunci, 'X-Timbangan-Akun': item.akun,
          'X-Timbangan-Waktu': item.waktu, 'X-Timbangan-Luring': item.offline ? '1' : '0' },
        body: new URLSearchParams(item.data).toString(), signal: controller.signal });
      var data;
      try { data = await response.json(); } catch (_) { throw new Error('Balasan server belum dapat dikonfirmasi.'); }
      if (response.ok && data.tersimpan === true && data.kunci === item.kunci) {
        await konfirmasiLokal(item, data);
        pesanGlobal = '';
        var cocok = false;
        daftarForm.forEach(function (f) {
          if (f.querySelector('[name=kunci]').value === item.kunci) {
            cocok = true;
            statusForm(f, data.peringatan ? data.pesan : 'Kiriman sudah dikonfirmasi tersimpan di server.', data.tujuan);
          }
        });
        // Peringatan integrasi bukan kiriman tertunda. Tetap tampilkan sebagai
        // pesan hasil tersendiri bila kirimannya selesai dari halaman lain.
        if (data.peringatan && !cocok) {
          var pesan = elemen('p', data.pesan, 'pesan pesan--err'); pesan.setAttribute('role', 'alert');
          var tautan = elemen('a', 'Buka hasil', 'tf-link'); tautan.href = tujuanAman(data.tujuan);
          pesan.append(document.createTextNode(' '), tautan);
          (document.querySelector('main') || document.body).prepend(pesan);
        }
        return { berhasil: true, tujuan: tujuanAman(data.tujuan), peringatan: data.peringatan };
      }
      if (response.status >= 500 || response.status === 408 || response.status === 429) throw new Error('Server belum mengonfirmasi. Kiriman tetap di perangkat.');
      await ubah(item.kunci, function (r) {
        r.status = response.status === 401 || response.status === 403 ? 'sesi' : 'periksa'; r.lease = 0;
        r.pesan = typeof data.pesan === 'string' ? data.pesan : 'Isian ditolak server. Periksa isian; salinan tetap tersimpan.'; return r;
      });
      daftarForm.forEach(function (f) { if (f.querySelector('[name=kunci]').value === item.kunci) { f.inert = false; statusForm(f, 'Server belum menyimpan kiriman. Periksa pesan dan isian; salinan tetap di perangkat.'); } });
      return { berhenti: response.status === 401 || response.status === 403 };
    } catch (_) {
      await ubah(item.kunci, function (r) { r.lease = 0; r.offline = true; r.pesan = 'Belum ada konfirmasi server. Salinan tetap di perangkat; kunci yang sama akan dicoba lagi.'; return r; });
      return { berhenti: true };
    } finally { clearTimeout(timeout); }
  }
  async function sinkronkan(langsung) {
    if (berjalan || !navigator.onLine || !siap) return;
    berjalan = true;
    try {
      var session = await fetch(PREFIX + '/kiriman/sesi', { credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
      if (!session.ok) { tampilkanPesan('Sesi perlu diperiksa. Isian tetap di perangkat; masuk kembali untuk menyinkronkan.'); return; }
      if (String((await session.json()).akun_id) !== akun) { tampilkanPesan('Akun yang sedang masuk berbeda. Kiriman tetap milik akun pembuatnya dan belum dikirim.'); return; }
      var rows = (await baca('kiriman')).filter(function (r) { return r.akun === akun && r.status !== 'terkirim'; }).sort(function (a,b) { return a.created-b.created; });
      var terhalang = new Set();
      for (var row of rows) {
        if (row.status === 'periksa') { terhalang.add(row.jalur); continue; }
        if (terhalang.has(row.jalur)) continue;
        var item = await ubah(row.kunci, function (r) {
          if (r.status === 'terkirim' || (r.lease > Date.now() && r.pemegang !== halaman)) return null;
          r.pemegang = halaman; r.lease = Date.now()+30000; return r;
        });
        if (!item) { terhalang.add(row.jalur); continue; }
        var result = await kirim(item);
        if (result.berhasil && langsung === item.kunci && !item.offline && !result.peringatan && document.visibilityState === 'visible') {
          // Hanya keberhasilan langsung memindahkan formulir yang tadi
          // dikirim. Pemulihan latar belakang tak mengganti isian layar lain.
          location.assign(result.tujuan); return;
        }
        if (!result.berhasil) terhalang.add(row.jalur);
        if (result.berhenti) break;
      }
    } catch (_) { /* jaringan/penyimpanan gagal: semua salinan tetap ada */ }
    finally { berjalan = false; await gambar().catch(gagalLokal); }
  }

  window.timbanganLuring = { sinkronkan: sinkronkan, adaTertunda: function () { return !siap || tertunda || belumTersimpan > 0; },
    siap: function () { return siap; }, antrean: function () { return baca('kiriman'); }, draf: function () { return baca('draf'); } };
  document.addEventListener('submit', function (e) {
    if (new URL(e.target.action).pathname === PREFIX + '/keluar') {
      try { localStorage.removeItem('tf.luring.akun'); } catch (_) {}
      if (navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ jenis: 'keluar' });
    }
    if (e.defaultPrevented || !e.target.matches('form[data-simpan-luring]')) return;
    e.preventDefault(); kirimForm(e.target, e.submitter);
  });
  document.addEventListener('input', function (e) {
    var f = e.target.closest('form[data-simpan-luring]'); if (f) simpanDraf(f).catch(function () {});
  });
  document.addEventListener('change', function (e) {
    var f = e.target.closest('form[data-simpan-luring]'); if (f) simpanDraf(f).catch(function () {});
  });
  window.addEventListener('beforeunload', function (e) { if (belumTersimpan || gagalSimpan) { e.preventDefault(); e.returnValue = ''; } });
  window.addEventListener('online', function () { sinkronkan(); });
  window.addEventListener('pageshow', function () { if (siap) sinkronkan(); });
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') sinkronkan(); });
  setInterval(function () { if (document.visibilityState === 'visible') sinkronkan(); }, 15000);
  // Lesepemegang per draf mencegah tab duplikat memakai satu ruang draf.
  async function mulai() {
    await bukaDB();
    await bersihkanTerkirim();
    await Promise.all(daftarForm.map(siapan));
    function siapan(f) { return siapkanForm(f); }
    siap = true; await gambar(); sinkronkan();
  }
  if (navigator.locks) {
    navigator.locks.request('tf-draf-'+tab, { ifAvailable: true }, async function (lock) {
      if (!lock) { tab = uuid(); try { sessionStorage.setItem('tf.luring.tab', tab); } catch (_) {} }
      await mulai();
      if (lock) await new Promise(function (resolve) { window.addEventListener('pagehide', resolve, { once: true }); });
    }).catch(gagalLokal);
  } else mulai().catch(gagalLokal);
})();

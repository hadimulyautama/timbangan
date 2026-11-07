/* Timbangan — lapisan perangkat.
 *
 * Tiga tugas, tidak lebih:
 *   1. memberi tahu petugas saat jaringan hilang, dan menahan kiriman
 *      di perangkat sampai jaringan kembali;
 *   2. menerima angka timbangan dengan koma maupun titik;
 *   3. menahan kirim ganda dari ketukan dobel.
 *
 * Sengaja tanpa kerangka kerja: satu berkas, tanpa proses bangun, bisa
 * dibaca dan diperbaiki siapa pun yang memegang sistem ini nanti.
 */
(function () {
  'use strict';

  var PREFIX = '/timbangan';
  // VERSI yang sedang berjalan — ditulis server saat halaman utuh dimuat.
  var VERSI_JALAN = document.documentElement.getAttribute('data-versi') || '';
  var GUDANG = 'timbangan-antrean';   // localStorage: kiriman menunggu jaringan

  // ── Sopir menyusul nomor polisi ───────────────────────────────────
  //
  // Platnya sudah dikenal sistem pada 69% penimbangan, tetapi sopirnya tetap
  // diketik ulang. Begitu platnya dikenali, namanya diisikan — TANPA tombol,
  // karena tara per karung pun sudah terisi sendiri dari aturan komoditas dan itu
  // angka yang langsung memengaruhi hasil. Yang menjaga bukan menahan isian,
  // melainkan menyebut asalnya di bawah kolom.
  //
  // Aturan yang dipegang: sekali petugas mengetik sendiri, sistem berhenti
  // ikut campur selamanya di formulir ini. Sopir bisa berganti, dan yang
  // tahu itu orang yang sedang berdiri di jembatan — bukan riwayat.
  //
  // Daftarnya diambil dari <datalist> yang sudah ada di halaman, bukan
  // salinan kedua yang bisa berbeda suatu hari, sehingga tetap bekerja tanpa
  // jaringan.
  function bacaNomorPolisi(nilai) {
    var kata = (nilai || '').normalize('NFKC').replace(/\s+/g, '').toUpperCase();
    var cocok = kata.match(/^([A-Z]+)([0-9]+)([A-Z]+)$/);
    var rapi = cocok ? cocok.slice(1).join(' ') : null;
    return rapi && rapi.length <= 20 ? rapi : null;
  }
  document.querySelectorAll('[data-format-nopol]').forEach(function (input) {
    function periksa() {
      var asli = input.getAttribute('data-nopol-asli');
      var samaLama = asli !== null && input.value === asli;
      input.setCustomValidity(!input.value.trim() || bacaNomorPolisi(input.value) || samaLama
        ? '' : 'Format nomor polisi harus huruf, angka, lalu huruf. Contoh: AD 1234 XY.');
    }
    input.addEventListener('input', periksa);
    input.addEventListener('blur', function () {
      var rapi = bacaNomorPolisi(input.value);
      if (rapi && rapi !== input.value) {
        input.value = rapi;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      periksa();
    });
    periksa();
  });

  // Jumlah karung tidak boleh dipotong diam-diam (1,5 menjadi 1).
  // Bekerja juga ketika halaman tersimpan dibuka tanpa jaringan.
  document.querySelectorAll('[data-jumlah-karung]').forEach(function (input) {
    function periksa() {
      var mode = input.form && input.form.querySelector('[name="cara_timbang"]:checked');
      if (input.hasAttribute('data-karung-sekali')) input.required = !!mode && mode.value === 'SEKALI';
      var teks = input.value.trim().replace(/\s+/g, '');
      if (/^[1-9][0-9]{0,2}(\.[0-9]{3})+$/.test(teks)) teks = teks.replace(/\./g, '');
      var n = Number(teks);
      input.setCustomValidity(!teks ? '' : !/^\d+$/.test(teks) || n < 1 || n > 100000
        ? 'Jumlah karung harus bilangan bulat lebih dari 0, maksimal 100.000.' : '');
    }
    input.addEventListener('input', periksa);
    if (input.form) input.form.querySelectorAll('[name="cara_timbang"]').forEach(function (el) { el.addEventListener('change', periksa); });
    periksa();
  });

  function pasangSopirMenyusul() {
    var nopol = document.querySelector('[data-nopol]');
    var sopir = document.querySelector('[data-sopir-isian]');
    var asal = document.getElementById('asal-sopir');
    var daftar = document.getElementById('nopol-dikenal');
    if (!nopol || !sopir || !asal || !daftar) { return; }

    // Nilai yang sudah ada saat halaman dibuka dianggap milik petugas.
    var disentuh = sopir.value.trim() !== '';
    var dariSistem = false;

    function cariSopir(nilai) {
      var cari = bacaNomorPolisi(nilai);
      if (!cari) { return ''; }
      var opsi = daftar.options;
      for (var i = 0; i < opsi.length; i++) {
        if (bacaNomorPolisi(opsi[i].value) === cari) {
          return opsi[i].dataset.sopir || '';
        }
      }
      return '';
    }

    function tinjau() {
      if (disentuh) { return; }
      var usulan = cariSopir(nopol.value);
      if (usulan) {
        sopir.value = usulan;
        dariSistem = true;
        asal.hidden = false;
      } else if (dariSistem) {
        // Platnya diganti ke yang tak dikenal: nama titipan tadi ikut pergi,
        // supaya tidak tertinggal sebagai saksi truk yang salah.
        sopir.value = '';
        dariSistem = false;
        asal.hidden = true;
      }
    }

    nopol.addEventListener('input', tinjau);
    nopol.addEventListener('change', tinjau);
    // Mengisi lewat skrip tidak memicu 'input', jadi peristiwa ini pasti
    // datang dari orang.
    sopir.addEventListener('input', function () {
      disentuh = true;
      dariSistem = false;
      asal.hidden = true;
    });

    tinjau();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', pasangSopirMenyusul);
  } else {
    pasangSopirMenyusul();
  }

  // Antrean dan draf atomik dikelola luring.js. Kunci lama di atas hanya
  // dibaca sebagai penjaga penyegaran; kiriman lama tidak dihapus diam-diam.
  function tampilkanJumlah() { /* luring.js menampilkan jumlah dari IndexedDB */ }

  // ── Data acuan untuk saat sinyal hilang ────────────────────────────
  //
  // HANYA daftar yang berubah mingguan — pemasok, pelanggan, jenis barang,
  // kendaraan — nama saja, dari /timbangan/acuan. Disimpan selagi jaringan
  // ada; /luring menampilkannya di bawah baris cap waktu selebar layar.
  // Tiket dan angka timbang tak pernah: yang basi di pos timbang lebih
  // berbahaya daripada yang tak ada. Persetujuan pemilik 14 Sep 2026.
  var KUNCI_ACUAN = 'timbangan-acuan';

  function simpanAcuan() {
    if (!navigator.onLine) { return; }
    fetch(PREFIX + '/acuan', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.daftar) { return; }
        try { localStorage.setItem(KUNCI_ACUAN, JSON.stringify(j)); } catch (e) { /* penuh */ }
      })
      .catch(function () { /* nanti lagi */ });
  }

  function teksAman(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function gambarAcuan() {
    var wadah = document.querySelector('[data-acuan]');
    if (!wadah) { return; }
    var j = null;
    try { j = JSON.parse(localStorage.getItem(KUNCI_ACUAN) || 'null'); } catch (e) { j = null; }
    var bar = document.createElement('div');
    bar.className = 'putus';
    bar.textContent = 'Data pukul ' + (j && j.pukul ? j.pukul : '?') + ' · sedang offline';
    document.body.appendChild(bar);
    if (!j) {
      wadah.innerHTML = '<p class="redup">Belum ada daftar acuan tersimpan di ponsel ini.</p>';
      return;
    }
    var html = '<div class="acuan">';
    j.daftar.forEach(function (d) {
      if (!d.isi || !d.isi.length) { return; }
      html += '<h3>' + teksAman(d.judul) + '</h3><ul>' +
        d.isi.map(function (x) { return '<li>' + teksAman(x) + '</li>'; }).join('') + '</ul>';
    });
    wadah.innerHTML = html + '</div>';
  }

  // ── Penanda luring ─────────────────────────────────────────────────

  function perbaruiStatusJaringan() {
    document.body.classList.toggle('luring', !navigator.onLine || document.body.hasAttribute('data-salinan-luring'));
    if (navigator.onLine && window.timbanganLuring) { window.timbanganLuring.sinkronkan(); }
  }

  window.addEventListener('online', perbaruiStatusJaringan);
  window.addEventListener('offline', perbaruiStatusJaringan);

  // ── Angka timbangan ────────────────────────────────────────────────

  // Petugas mengetik '13.600', '13,600', '13600', atau '0.250' — semuanya sah.
  // Aturannya sama persis dengan `_angka()` di sisi server: satu titik dengan
  // tiga angka di belakangnya adalah pemisah ribuan HANYA bila angka di
  // depannya bukan nol. '0.250' adalah seperempat kilogram, bukan 250.
  function bakukanAngka(teks) {
    var s = String(teks || '').replace(/\s/g, '');
    if (s.indexOf(',') >= 0) { return s.replace(/\./g, '').replace(',', '.'); }
    var titik = s.split('.').length - 1;
    if (titik > 1) { return s.replace(/\./g, ''); }
    if (titik === 1) {
      var bagian = s.split('.');
      var depanBermakna = bagian[0].replace(/^[-+]/, '').replace(/^0+/, '') !== '';
      if (bagian[1].length === 3 && depanBermakna) { return s.replace('.', ''); }
    }
    return s;
  }

  document.addEventListener('blur', function (e) {
    if (!e.target.matches || !e.target.matches('[data-berat]')) { return; }
    // Koreksi mempertahankan ejaan asli sampai parser server membacanya.
    // Mengubah 9.990,500 menjadi 9990.500 membuat titiknya terbaca ribuan
    // pada kiriman berikutnya, padahal pengguna tidak mengubah nilainya.
    if (e.target.closest('[data-correction-form]')) { return; }
    var bersih = bakukanAngka(e.target.value);
    if (bersih !== '' && !isNaN(Number(bersih))) { e.target.value = bersih; }
  }, true);

  // ── Penahan kirim ganda ────────────────────────────────────────────

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (e.defaultPrevented) { return; }
    if (form.matches('[data-simpan-luring]') && window.timbanganLuring) { return; }
    if (form.dataset.terkirim === '1') { e.preventDefault(); return; }
    form.dataset.terkirim = '1';

    /* Tombol yang ditekan ikut menentukan APA yang dikerjakan — "Simpan
     * sementara" dan "Selesaikan penimbangan" adalah tombol kirim yang sama
     * formulirnya, dibedakan oleh name/value-nya. Menonaktifkannya di baris
     * berikut membuat nilai itu hilang dari kiriman, sehingga "simpan
     * sementara" diam-diam berubah menjadi "selesaikan". Salin dulu. */
    var penekan = e.submitter;
    if (penekan && penekan.name) {
      var salinan = document.createElement('input');
      salinan.type = 'hidden';
      salinan.name = penekan.name;
      salinan.value = penekan.value;
      form.appendChild(salinan);
    }

    form.querySelectorAll('button[type=submit]').forEach(function (t) {
      t.disabled = true;
      if (t.dataset.sibuk) {
        t.textContent = t.dataset.sibuk;
        t.classList.add('tbl--sibuk');
      }
    });
    // Bila navigasi gagal (jaringan putus di tengah), tombol dibuka kembali
    // supaya petugas tidak terjebak di layar yang tidak bisa apa-apa.
    setTimeout(function () {
      form.dataset.terkirim = '';
      form.querySelectorAll('button[type=submit]').forEach(function (t) {
        t.disabled = false;
        t.classList.remove('tbl--sibuk');
      });
    }, 8000);
  });

  // ── Peringatan angka janggal ───────────────────────────────────────

  // Bukan penolakan: alat memang membaca kelipatan 10 kg, jadi angka yang
  // bukan kelipatan itu patut ditanya, bukan dilarang.
  document.addEventListener('input', function (e) {
    if (!e.target.matches || !e.target.matches('[data-berat]')) { return; }
    var kotak = e.target.closest('.grup');
    if (!kotak) { return; }
    var catatan = kotak.querySelector('[data-janggal]');
    if (!catatan) {
      catatan = document.createElement('div');
      catatan.className = 'bantu peringatan';
      catatan.setAttribute('data-janggal', '');
      kotak.appendChild(catatan);
    }
    var n = Number(bakukanAngka(e.target.value));
    var kelipatan = Number(document.body.dataset.kelipatan || 10);
    catatan.textContent = (n && kelipatan && n % kelipatan !== 0)
      ? 'Angka ini bukan kelipatan ' + kelipatan + ' kg — pastikan sudah benar.'
      : '';
  });

  // ── Pilihan panjang jadi kolom ketik ───────────────────────────────
  //
  // Daftar supplier ikut Kledo, jadi isinya ratusan nama. Menggulir daftar
  // sepanjang itu di ponsel, sambil truk menunggu, adalah cara membuat orang
  // salah pilih.
  //
  // Peningkatan bertahap: <select> tetap dirender server dan tetap menjadi
  // pemegang nilai yang dikirim. Bila berkas ini gagal dimuat, petugas masih
  // mendapat dropdown biasa yang berfungsi penuh — bukan layar mati.
  //
  // Penyaringan memakai daftar yang SUDAH ada di halaman; tidak ada panggilan
  // ke server, jadi tetap bekerja tanpa sinyal.

  function pasangPencarian(pilih) {
    var opsi = [];
    Array.prototype.forEach.call(pilih.querySelectorAll('option'), function (o) {
      if (!o.value) { return; }
      var induk = o.parentNode;
      opsi.push({
        nilai: o.value,
        label: o.textContent.trim(),
        kelompok: induk.tagName === 'OPTGROUP' ? induk.label : ''
      });
    });
    // Kolom teks bebas yang hendak DILEBUR ke dalam kotak ini, bila ada.
    // Dulu keduanya berdiri sendiri: satu daftar pihak terdaftar, satu kolom
    // "bila belum terdaftar" — dua kolom untuk satu pertanyaan, plus satu
    // paragraf penjelasan yang harus dibaca petugas sambil truk menunggu.
    var gabung = pilih.dataset.gabung
      ? document.getElementById(pilih.dataset.gabung) : null;

    // Daftar pendek masih nyaman sebagai dropdown biasa — KECUALI bila ia
    // harus melebur, karena hasilnya tetap dua kolom dan justru itu yang
    // sedang dihilangkan.
    if (opsi.length < 12 && !gabung) { return; }

    var bungkus = document.createElement('div');
    bungkus.className = 'cari';
    var kotak = document.createElement('input');
    kotak.type = 'text';
    kotak.className = 'fld teks';
    kotak.setAttribute('autocomplete', 'off');
    kotak.setAttribute('enterkeyhint', 'search');
    kotak.placeholder = pilih.dataset.cari || 'Ketik untuk mencari…';
    // Select disembunyikan setelah ditingkatkan menjadi pencarian. Pindahkan
    // validasi ke kotak yang dapat difokuskan, tetapi sahkan hanya ID pilihan.
    var wajib = pilih.required;
    if (wajib) { pilih.required = false; kotak.required = true; }
    var hasil = document.createElement('div');
    hasil.className = 'cari__hasil';

    bungkus.appendChild(kotak);
    bungkus.appendChild(hasil);
    pilih.parentNode.insertBefore(bungkus, pilih);
    pilih.style.display = 'none';

    // Nama yang dipilih DUDUK DI KOLOMNYA SENDIRI.
    //
    // Dulu kotak ketik justru dikosongkan setelah memilih, lalu namanya
    // muncul di baris terpisah "Terpilih: …". Nama yang baru saja diketik
    // lenyap dari tempat mengetiknya dan pindah ke tempat lain — dua elemen
    // untuk satu fakta.
    function tampilkanTerpilih() {
      var ada = opsi.filter(function (o) { return o.nilai === pilih.value; })[0];
      if (ada) { kotak.value = ada.label; }
    }

    // PENTING: begitu tulisan di kotak tidak lagi sama persis dengan nama yang
    // terpilih, pilihannya dibatalkan. Tanpa ini layar bisa menampilkan satu
    // nama sementara yang terkirim id lama — persis jenis kekeliruan yang
    // paling berbahaya di sini, karena tidak terlihat oleh siapa pun.
    function selaraskan() {
      if (pilih.value) {
        var ada = opsi.filter(function (o) { return o.nilai === pilih.value; })[0];
        if (!ada || kotak.value.trim() !== ada.label) { pilih.value = ''; }
      }
      // Tulisan yang tidak cocok dengan siapa pun di daftar BUKAN kesalahan:
      // ia nama pihak yang belum terdaftar, dan dikirim apa adanya. Yang
      // menolak isian kosong tetap `_wajib_pihak` di layanan, karena "salah
      // satu dari dua" tidak bisa dinyatakan HTML.
      if (gabung) { gabung.value = pilih.value ? '' : kotak.value.trim(); }
      if (wajib) {
        kotak.setCustomValidity(pilih.value ? '' : 'Pilih kontak dari daftar Kledo.');
      }
    }

    function cocok(o, kata) {
      return o.label.toLowerCase().indexOf(kata) >= 0;
    }

    function gambar() {
      var kata = kotak.value.trim().toLowerCase();
      hasil.innerHTML = '';
      if (!kata) { return; }

      var ketemu = opsi.filter(function (o) { return cocok(o, kata); });
      if (!ketemu.length) {
        var kosong = document.createElement('div');
        kosong.className = 'cari__kosong';
        kosong.textContent = 'Tidak ada yang cocok dengan "' + kotak.value.trim() + '"';
        hasil.appendChild(kosong);
        return;
      }

      var kelompokTerakhir = null;
      ketemu.slice(0, 25).forEach(function (o) {
        if (o.kelompok && o.kelompok !== kelompokTerakhir) {
          kelompokTerakhir = o.kelompok;
          var judul = document.createElement('div');
          judul.className = 'kelompok';
          judul.textContent = o.kelompok;
          hasil.appendChild(judul);
        }
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = o.label;
        b.addEventListener('click', function () {
          pilih.value = o.nilai;
          kotak.value = o.label;
          if (gabung) { gabung.value = ''; }
          if (wajib) { kotak.setCustomValidity(''); }
          hasil.innerHTML = '';
        });
        hasil.appendChild(b);
      });
      if (ketemu.length > 25) {
        var sisa = document.createElement('div');
        sisa.className = 'cari__kosong';
        sisa.textContent = ketemu.length - 25 + ' lainnya — ketik lebih lengkap';
        hasil.appendChild(sisa);
      }
    }

    kotak.addEventListener('input', function () {
      selaraskan();
      gambar();
    });
    // Menyentuh kolom yang sudah berisi nama berarti hendak menggantinya:
    // tampilkan lagi daftarnya tanpa memaksa menghapus dulu.
    kotak.addEventListener('focus', gambar);
    kotak.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        // Jangan mengirim formulir hanya karena petugas menekan Enter di
        // kolom cari; pilih hasil teratas bila ada.
        e.preventDefault();
        var pertama = hasil.querySelector('button');
        if (pertama) { pertama.click(); }
      } else if (e.key === 'Escape') {
        hasil.innerHTML = '';
      }
    });
    document.addEventListener('click', function (e) {
      if (!bungkus.contains(e.target)) { hasil.innerHTML = ''; }
    });

    if (gabung) {
      // Kolom teksnya tidak dihapus dari DOM — ia tetap yang dikirim ke
      // server, hanya tidak lagi punya rupa sendiri.
      var grupTeks = gabung.closest ? gabung.closest('.grup') : null;
      if (grupTeks) { grupTeks.style.display = 'none'; }
      // Nilai yang sudah ada (mis. formulir kembali setelah galat) naik ke
      // kotak, supaya yang diketik petugas tidak lenyap.
      if (gabung.value.trim() && !pilih.value) { kotak.value = gabung.value; }
    }

    tampilkanTerpilih();
    selaraskan();
    pilih.addEventListener('change', function () {
      tampilkanTerpilih();
      selaraskan();
    });
  }

  document.querySelectorAll('select[data-cari]').forEach(pasangPencarian);

  // Nama sopir boleh baru. Nilai tetap milik input asli agar pemulihan draf,
  // antrean luring, dan isian dari kendaraan memakai kolom yang sama.
  function pasangPilihanTeks(kotak) {
    var daftar = document.getElementById(kotak.getAttribute('list'));
    if (!daftar) return;
    var nopol = kotak.hasAttribute('data-pilihan-nopol');
    var bungkus = kotak.parentNode;
    var opsi = Array.prototype.map.call(daftar.options, function (o) {
      return { nama: o.value, cari: bakukan(o.value + ' ' + (o.dataset.alias || '')) };
    });
    var hasil = document.createElement('div');
    hasil.className = 'cari__hasil';
    hasil.id = kotak.id + '-hasil';
    hasil.setAttribute('role', 'listbox');
    hasil.setAttribute('aria-label', nopol ? 'Nomor polisi tersimpan' : 'Nama sopir tersimpan');
    bungkus.appendChild(hasil);
    // Datalist tetap menjadi cadangan bila JavaScript tidak berjalan.
    kotak.removeAttribute('list');
    kotak.setAttribute('role', 'combobox');
    kotak.setAttribute('aria-autocomplete', 'list');
    kotak.setAttribute('aria-controls', hasil.id);
    kotak.setAttribute('aria-expanded', 'false');
    var aktif = -1;

    function bakukan(teks) {
      return teks.normalize('NFKC').trim().replace(/\s+/g, nopol ? '' : ' ').toLowerCase();
    }
    function tutup() {
      hasil.replaceChildren();
      aktif = -1;
      kotak.setAttribute('aria-expanded', 'false');
      kotak.removeAttribute('aria-activedescendant');
    }
    function pilih(nama) {
      kotak.value = nama;
      kotak.dispatchEvent(new Event('input', { bubbles: true }));
      kotak.dispatchEvent(new Event('change', { bubbles: true }));
      tutup();
    }
    function gambar() {
      tutup();
      var kata = bakukan(kotak.value);
      var cocok = opsi.filter(function (o) { return !kata || o.cari.indexOf(kata) >= 0; });
      cocok.slice(0, 25).forEach(function (o, i) {
        var b = document.createElement('button');
        b.type = 'button';
        b.tabIndex = -1;
        b.id = hasil.id + '-' + i;
        b.setAttribute('role', 'option');
        b.setAttribute('aria-selected', 'false');
        b.textContent = o.nama;
        b.addEventListener('mousedown', function (e) { e.preventDefault(); });
        b.addEventListener('click', function () { pilih(o.nama); });
        hasil.appendChild(b);
      });
      if (!cocok.length || cocok.length > 25) {
        var pesan = document.createElement('div');
        pesan.className = 'cari__kosong';
        pesan.setAttribute('role', 'status');
        if (cocok.length > 25) {
          pesan.textContent = (cocok.length - 25) + ' lainnya — ketik lebih lengkap';
        } else if (nopol) {
          pesan.textContent = !kata ? 'Belum ada nomor polisi tersimpan.'
            : (bacaNomorPolisi(kotak.value) ? 'Belum ada di daftar. Kendaraan baru disimpan bersama tiket.'
              : 'Ketik nomor lengkap: huruf, angka, lalu huruf.');
        } else {
          pesan.textContent = kata ? 'Belum ada di daftar. Nama baru disimpan bersama tiket.' : 'Belum ada nama sopir tersimpan.';
        }
        hasil.appendChild(pesan);
      }
      kotak.setAttribute('aria-expanded', 'true');
    }
    kotak.addEventListener('focus', gambar);
    kotak.addEventListener('input', gambar);
    kotak.addEventListener('keydown', function (e) {
      if (e.isComposing) return;
      var terbuka = kotak.getAttribute('aria-expanded') === 'true';
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!terbuka) gambar();
        var tombol = hasil.querySelectorAll('[role="option"]');
        if (!tombol.length) return;
        aktif = e.key === 'ArrowDown' ? (aktif + 1) % tombol.length
          : (aktif <= 0 ? tombol.length - 1 : aktif - 1);
        tombol.forEach(function (b, i) {
          b.classList.toggle('sorot', i === aktif);
          b.setAttribute('aria-selected', String(i === aktif));
        });
        kotak.setAttribute('aria-activedescendant', tombol[aktif].id);
        tombol[aktif].scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter' && terbuka) {
        e.preventDefault();
        var pilihan = hasil.querySelector('[aria-selected="true"]');
        // Tanpa pilihan eksplisit, pertahankan ketikan sebagai calon nama
        // baru. Jangan menggantinya dengan hasil parsial pertama.
        if (pilihan) pilihan.click();
        else tutup();
      } else if (e.key === 'Escape') {
        if (terbuka) e.preventDefault();
        tutup();
      }
    });
    kotak.addEventListener('blur', function () {
      setTimeout(function () { if (!bungkus.contains(document.activeElement)) tutup(); }, 0);
    });
    document.addEventListener('click', function (e) {
      if (!bungkus.contains(e.target)) tutup();
    });
  }
  document.querySelectorAll('[data-pilihan-sopir], [data-pilihan-nopol]').forEach(pasangPilihanTeks);

  // ── Mulai ──────────────────────────────────────────────────────────

  perbaruiStatusJaringan();
  tampilkanJumlah();
  gambarAcuan();
  if (!document.querySelector('[data-acuan]')) {
    simpanAcuan();
    setInterval(simpanAcuan, 30 * 60 * 1000);
  }

  if ('serviceWorker' in navigator) {
    // `?v=` = VERSI server: deploy mengubah alamatnya, worker baru terpasang,
    // cache lama dibuang. Satu sumber kebenaran, bukan angka di dalam sw.js.
    navigator.serviceWorker.register(PREFIX + '/sw.js?v=' + VERSI_JALAN, { scope: PREFIX + '/' })
      .catch(function () { /* tanpa service worker aplikasi tetap jalan */ });
  }

  window.timbangan = window.timbangan || {};

  /* Baris tabel yang bisa dibuka.
   *
   * Tautan "Ubah" tetap ada supaya bisa dijangkau papan ketik dan pembaca
   * layar; ini hanya memperlebar sasaran sentuh ke seluruh baris — di layar
   * ponsel tombol sekecil itu sering meleset.
   */
  document.addEventListener('click', function (e) {
    if (!e.target.closest) { return; }
    var baris = e.target.closest('tr[data-buka]');
    if (!baris) { return; }
    // Jangan rebut klik yang memang punya tujuan sendiri.
    if (e.target.closest('a, button, input, select, label')) { return; }
    // Jangan pindah halaman saat orang sedang menyorot teks untuk disalin.
    var sorot = window.getSelection && window.getSelection().toString();
    if (sorot) { return; }
    window.location.href = baris.getAttribute('data-buka');
  });


  /* Unduhan tanpa meninggalkan halaman.
   *
   * Di aplikasi yang dipasang ke layar utama iOS tidak ada bilah peramban.
   * Menautkan langsung ke berkas — bahkan dengan target="_blank" — membuat
   * iOS menggantikan seluruh layar dengan pratinjau berkas yang hanya
   * menawarkan "Open in…", tanpa satu pun jalan kembali; aplikasi harus
   * ditutup paksa. Maka berkasnya diambil di latar lalu diserahkan ke lembar
   * Bagikan, yang muncul sebagai lapisan di ATAS halaman: setelah ditutup,
   * petugas kembali persis ke daftar yang tadi dilihatnya.
   *
   * Di peramban meja yang tidak punya lembar bagikan, jalannya kembali ke
   * unduhan biasa lewat blob. Bila keduanya gagal, barulah tautannya
   * dibuka apa adanya — lebih baik tersangkut daripada tidak dapat berkas.
   */
  /* Hanya iOS/iPadOS yang dicegat.
   *
   * Di sanalah jalan buntunya nyata: aplikasi yang dipasang ke layar utama
   * tidak punya bilah peramban, sehingga berkas menggantikan seluruh layar
   * tanpa tombol cetak, bagikan, maupun kembali. Lembar Bagikan iOS memuat
   * pilihan Cetak, jadi alur mencetak tetap utuh.
   *
   * Di Mac dan peramban meja JANGAN dicegat: di sana tautan biasa membuka
   * tab dengan penampil PDF lengkap beserta tombol cetaknya — sedangkan
   * lembar Bagikan macOS TIDAK punya pilihan Cetak sama sekali (hanya
   * AirDrop, Mail, Messages). Mencegatnya di sana justru menghapus satu-
   * satunya cara mencetak.
   *
   * iPadOS mengaku sebagai Mac di user agent; yang membedakannya titik
   * sentuh. Mac tidak punya.
   */
  function perlu_lembar_bagikan() {
    var ua = navigator.userAgent || '';
    var iOS = /iP(hone|ad|od)/.test(ua) ||
              (/Mac/.test(ua) && navigator.maxTouchPoints > 1);
    return iOS && !!navigator.share;
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest) { return; }
    var tautan = e.target.closest('a[data-unduh]');
    if (!tautan) { return; }
    if (!tautan.hasAttribute('data-bagikan') && !perlu_lembar_bagikan()) { return; }   // biarkan tautan bekerja apa adanya
    e.preventDefault();
    unduhBerkas(tautan);
  });

  function unduhBerkas(tautan) {
    if (tautan.dataset.sibuk === '1') { return; }
    var kotakUnduh = document.querySelector('[data-hasil-unduh]');
    if (kotakUnduh) { kotakUnduh.hidden = true; }
    // Yang diganti hanya elemen berlabel `data-teks` bila ada. Tautan pilihan
    // cetak berisi ikon dan keterangan; mengganti seluruh isinya dengan kata
    // "Menyiapkan…" akan menghapus semuanya, dan tidak kembali utuh bila
    // pengguna membatalkan lembar bagikan.
    var label = tautan.querySelector('[data-teks]') || tautan;
    var semula = label.textContent;
    tautan.dataset.sibuk = '1';
    label.textContent = 'Menyiapkan…';

    var selesai = function () {
      tautan.dataset.sibuk = '';
      label.textContent = semula;
    };

    fetch(tautan.href, { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) { throw new Error('gagal ' + r.status); }
        // Nama berkas diambil dari jawaban server, bukan disusun ulang di
        // sini — supaya hanya ada satu tempat yang menentukannya.
        var cd = r.headers.get('Content-Disposition') || '';
        if (new URL(tautan.href).pathname.endsWith('/ekspor.csv') &&
            (!/attachment/i.test(cd) || !/text\/csv/i.test(r.headers.get('Content-Type') || ''))) {
          // Sesi habis dapat berakhir pada HTML login dengan HTTP 200.
          // Halaman itu bukan berkas CSV yang berhasil diunduh.
          throw new Error('Ekspor belum tersedia; periksa sesi dan coba lagi.');
        }
        if (tautan.dataset.dokumen === 'pdf' && !/application\/pdf/i.test(r.headers.get('Content-Type') || '')) throw new Error('PDF belum tersedia; periksa sesi dan versi tiket.');
        var cocok = cd.match(/filename="?([^"]+)"?/);
        return r.blob().then(function (blob) {
          return { blob: blob, nama: cocok ? cocok[1] : (tautan.dataset.nama || 'unduhan.csv') };
        });
      })
      .then(function (hasil) {
        var jenis = hasil.blob.type || 'text/csv';
        var berkas;
        try {
          berkas = new File([hasil.blob], hasil.nama, { type: jenis });
        } catch (err) { berkas = null; }

        if (berkas && navigator.share && navigator.canShare &&
            navigator.canShare({ files: [berkas] })) {
          return navigator.share({ files: [berkas], title: hasil.nama });
        }
        var url = URL.createObjectURL(hasil.blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = hasil.nama;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
      })
      .then(selesai)
      .catch(function (err) {
        selesai();
        // Pengguna menutup lembar bagikan — bukan kegagalan.
        if (err && err.name === 'AbortError') { return; }
        if (kotakUnduh) {
          kotakUnduh.textContent = kotakUnduh.dataset.pesan || 'Unduhan belum berhasil. Periksa jaringan lalu coba lagi; filter riwayat tetap tersimpan pada halaman ini.';
          kotakUnduh.hidden = false;
          return;
        }
        window.location.href = tautan.href;
      });
  }

  // ── Printer struk (ePOS-Print) ─────────────────────────────────────
  //
  // Server tidak bisa mencetak: ia berjalan di Railway, printer berdiri di
  // jaringan gudang. Jadi perangkat inilah kurirnya — ia mengambil perintah
  // cetak dari server, lalu menyerahkannya ke printer di jaringan setempat.
  //
  // Dua hal yang harus diberikan sekali per perangkat, dan keduanya diminta
  // browser, bukan aplikasi:
  //   1. sertifikat printer diterima (alamatnya dibuka sekali di tab lain);
  //   2. izin "akses jaringan lokal" diklik saat browser bertanya.
  // Tanpa keduanya permintaan tidak gagal dengan pesan — ia menggantung.
  // Itulah sebabnya ada tenggat waktu di bawah, dan sebabnya pesan gagal
  // menunjuk ke halaman penyiapan alih-alih berkata "terjadi kesalahan".

  var PRINTER = 'timbangan-printer';   // localStorage: alamat printer perangkat
  var TENGGAT_MS = 20000;

  function alamatPrinter() {
    try {
      var simpanan = (localStorage.getItem(PRINTER) || '').trim();
      if (simpanan) { return simpanan.replace(/\/+$/, ''); }
    } catch (e) { /* penyimpanan diblokir — pakai bawaan dari server */ }
    return (document.body.dataset.printer || '').trim().replace(/\/+$/, '');
  }

  function simpanPrinter(alamat) {
    try {
      alamat = (alamat || '').trim().replace(/\/+$/, '');
      if (alamat) { localStorage.setItem(PRINTER, alamat); }
      else { localStorage.removeItem(PRINTER); }
      return true;
    } catch (e) { return false; }
  }

  // Kode kesalahan printer diterjemahkan ke hal yang bisa DIKERJAKAN petugas.
  // "EPTR_REC_EMPTY" tidak berarti apa pun bagi orang yang sedang berdiri di
  // samping truk; "kertas habis" berarti sesuatu.
  var ARTI_GAGAL = {
    EPTR_COVER_OPEN: 'Penutup printer terbuka. Tutup, lalu cetak lagi.',
    EPTR_REC_EMPTY: 'Kertas habis. Ganti gulungannya, lalu cetak lagi.',
    EPTR_AUTOMATICAL: 'Printer berhenti karena kesalahan alat. ' +
      'Matikan dan nyalakan kembali.',
    EPTR_UNRECOVERABLE: 'Printer perlu dimatikan dan dinyalakan kembali.',
    EPTR_REC_ERROR: 'Kepala cetak terlalu panas. Tunggu sebentar, lalu ulangi.',
    DeviceNotFound: 'Printer menjawab, tetapi kepala cetaknya tidak dikenali. ' +
      'Periksa nama perangkat di halaman penyiapan printer.',
    PrintSystemError: 'Printer menolak perintah cetak. Coba matikan dan ' +
      'nyalakan kembali.',
    SchemaError: 'Perintah cetak ditolak printer. Laporkan ke Admin — ' +
      'ini kekeliruan aplikasi, bukan kekeliruan alat.'
  };

  function KirimGagal(pesan, penyiapan) {
    var e = new Error(pesan);
    e.penyiapan = !!penyiapan;   // arahkan ke halaman penyiapan printer
    return e;
  }

  // Respons ePOS harus berasal dari HTTP berhasil dan XML yang sah.
  // Teks HTML atau XML terpotong dapat memuat success="true" tanpa ACK cetak.
  function bacaJawabanPrinter(teks) {
    var xml = new DOMParser().parseFromString(teks, 'text/xml');
    if (xml.doctype || xml.getElementsByTagName('parsererror').length ||
        xml.getElementsByTagNameNS('*', 'parsererror').length) {
      throw new Error('Jawaban printer bukan XML ePOS yang sah.');
    }
    var akar = xml.documentElement;
    var eposNS = 'http://www.epson-pos.com/schemas/2011/03/epos-print';
    var jawaban = akar;
    if (akar && akar.localName === 'Envelope' &&
        (akar.namespaceURI === 'http://schemas.xmlsoap.org/soap/envelope/' ||
         akar.namespaceURI === 'http://www.w3.org/2003/05/soap-envelope')) {
      var tubuh = akar.getElementsByTagNameNS(akar.namespaceURI, 'Body');
      if (tubuh.length !== 1 || tubuh[0].parentNode !== akar ||
          tubuh[0].children.length !== 1) {
        throw new Error('Amplop jawaban printer tidak sah.');
      }
      jawaban = tubuh[0].children[0];
    }
    if (!jawaban || jawaban.localName !== 'response' ||
        (jawaban.namespaceURI && jawaban.namespaceURI !== eposNS) ||
        jawaban.children.length ||
        !/^(true|false|1|0)$/.test(jawaban.getAttribute('success') || '')) {
      throw new Error('Jawaban printer bukan respons ePOS yang sah.');
    }
    return { berhasil: /^(true|1)$/.test(jawaban.getAttribute('success')),
             kode: jawaban.getAttribute('code') || '' };
  }

  // Tenggat mencakup header DAN seluruh isi ACK. Putus koneksi setelah
  // pengiriman tetap belum pasti: kertas mungkin sudah keluar, jangan retry.
  function mintaPrinter(tujuan, perintah, batas, alamat) {
    var henti = new AbortController();
    var habis = false;
    var jam = setTimeout(function () { habis = true; henti.abort(); }, batas);
    return fetch(tujuan, {
      method: 'POST',
      headers: { 'Content-Type': 'text/xml; charset=utf-8' },
      body: perintah,
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      signal: henti.signal
    }).then(function (r) {
      if (!r.ok) { throw new Error('HTTP printer ' + r.status + '.'); }
      return r.text();
    }).then(bacaJawabanPrinter).then(function (jawaban) {
      clearTimeout(jam);
      return jawaban;
    }, function (err) {
      clearTimeout(jam);
      henti.abort();
      var gagal = KirimGagal(habis
        ? 'Printer tidak menjawab dalam ' + (batas / 1000) +
          ' detik. Periksa izin jaringan lokal dan sambungan printer.'
        : 'Hasil printer belum dapat dipastikan di ' + alamat + '. ' +
          (err && err.message ? err.message : ''), true);
      gagal.belumPasti = true;
      throw gagal;
    });
  }

  function tujuanPrinter(alamat, devid, tenggat) {
    return alamat + '/cgi-bin/epos/service.cgi?devid=' +
      encodeURIComponent(devid) + '&timeout=' + tenggat;
  }

  // XML kosong hanya membaca status: tidak ada teks, feed atau cut.
  // HANYA pemeriksaan ini boleh diulang ketika koneksi putus.
  var STATUS_PRINTER = '<?xml version="1.0" encoding="utf-8"?>' +
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">' +
    '<s:Body><epos-print xmlns="http://www.epson-pos.com/schemas/2011/03/' +
    'epos-print"/></s:Body></s:Envelope>';

  function izinJaringanPrinter() {
    try {
      return navigator.permissions.query({ name: 'local-network-access' })
        .then(function (p) { return p.state; }, function () { return 'tidak dikenal'; });
    } catch (e) { return Promise.resolve('tidak dikenal'); }
  }

  function pastikanPrinter(alamat, devid) {
    if (!alamat) {
      return Promise.reject(KirimGagal('Printer belum disetel di perangkat ini.', true));
    }
    if (location.protocol === 'https:' && !/^https:/i.test(alamat)) {
      return Promise.reject(KirimGagal('Alamat printer harus https:// pada aplikasi ini.', true));
    }
    return izinJaringanPrinter().then(function (izin) {
      if (izin === 'denied') {
        throw KirimGagal('Izin jaringan lokal ditolak. Izinkan akses jaringan lokal ' +
          'pada setelan situs di browser ini. Wi-Fi yang sama belum memberi izin browser.', true);
      }
      function periksa(ulangan) {
        return mintaPrinter(tujuanPrinter(alamat, devid, 3000), STATUS_PRINTER, 6000, alamat)
          .catch(function () {
            if (!ulangan) {
              return new Promise(function (lanjut) { setTimeout(lanjut, 500); })
                .then(function () { return periksa(true); });
            }
            throw KirimGagal('Printer belum dapat dihubungi di ' + alamat + '. ' +
              'Struk belum dikirim. Sambungan sudah dicoba kembali otomatis. ' +
              'Periksa printer menyala dan alamatnya benar; jika browser meminta ' +
              'sertifikat atau izin jaringan lokal, selesaikan izin tersebut. ' +
              'Wi-Fi yang sama saja belum cukup.', true);
          }).then(function (jawaban) {
            if (!jawaban.berhasil) {
              throw KirimGagal(ARTI_GAGAL[jawaban.kode] ||
                'Layanan printer belum siap' + (jawaban.kode ? ' (' + jawaban.kode + ')' : '') +
                '. Struk belum dikirim.', false);
            }
            return jawaban;
          });
      }
      return periksa(false);
    });
  }

  /* Pulihkan sambungan sebelum setiap cetakan, termasuk setelah HP tidur.
   * Setelah XML struk dikirim, jawaban hilang tetap BELUM PASTI, tanpa retry. */
  function cetakKePrinter(sumber, perintahSiap) {
    var alamat = alamatPrinter();
    var devid = document.body.dataset.printerDevid || 'local_printer';
    return pastikanPrinter(alamat, devid).then(function () {
      return perintahSiap != null ? perintahSiap : fetch(sumber, { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) { throw new Error('Gagal menyiapkan struk (' + r.status + ').'); }
          return r.text();
        });
    }).then(function (perintah) {
      return mintaPrinter(tujuanPrinter(alamat, devid, 10000), perintah, TENGGAT_MS, alamat);
    }).then(function (jawaban) {
      if (jawaban.berhasil) { return true; }
      var kode = jawaban.kode;
      var gagal = new Error(ARTI_GAGAL[kode] || ('Hasil printer belum dapat dipastikan' + (kode ? ' ('+kode+')' : '') + '.'));
      gagal.belumPasti = !ARTI_GAGAL[kode];
      throw gagal;
    });
  }

  window.TeraFlowPrinter = { alamat: alamatPrinter, kirim: cetakKePrinter };

  /* Tombol cetak. `data-cetak` berisi alamat penyusun perintah di server. */
  document.addEventListener('click', function (e) {
    if (!e.target.closest) { return; }
    var tombol = e.target.closest('[data-cetak]');
    if (!tombol) { return; }
    e.preventDefault();
    if (tombol.dataset.sibuk === '1') { return; }

    // Alasan diperiksa SEBELUM perintah dikirim. Pemeriksaan sesudahnya
    // hanya melindungi audit, sedangkan kertas telanjur dapat keluar.
    var formCetak = document.querySelector('form[data-catat-cetak]');
    var alasanCetak = formCetak && formCetak.querySelector('input[name="alasan"]');
    if (alasanCetak && alasanCetak.required && !alasanCetak.value.trim()) {
      lapor('Isi alasan cetak ulang sebelum mengirim ke printer.', 'err');
      alasanCetak.focus();
      alasanCetak.reportValidity();
      return;
    }
    var catatTombol = formCetak && formCetak.querySelector('button[type="submit"]');
    var bacaSaja = alasanCetak && alasanCetak.readOnly;
    var nonaktif = catatTombol && catatTombol.disabled;
    if (alasanCetak) alasanCetak.readOnly = true;
    if (catatTombol) catatTombol.disabled = true;

    var label = tombol.querySelector('[data-teks]') || tombol;
    var semula = label.textContent;
    tombol.dataset.sibuk = '1';
    label.textContent = 'Mencetak…';
    lapor('');

    function pulihkanCetak() {
      tombol.dataset.sibuk = '';
      label.textContent = semula;
      if (alasanCetak) alasanCetak.readOnly = bacaSaja;
      if (catatTombol) catatTombol.disabled = nonaktif;
    }
    cetakKePrinter(tombol.dataset.cetak)
      .then(function () {
        lapor('Struk keluar di printer.', 'ok', false, {tindakan:'cetak',berhasil:true});
        if (catatCetak()) {
          // Kunci tetap dipegang selama POST audit dan perpindahan halaman.
          // Klik sesudah ACK printer pun tidak boleh mengirim kertas lagi.
          label.textContent = 'Mencatat cetakan…';
        } else pulihkanCetak();
      })
      .catch(function (err) {
        pulihkanCetak();
        lapor(err.belumPasti
          ? 'Hasil cetak belum dapat dipastikan. Periksa kertas sebelum mencoba lagi. ' + err.message
          : err.message, 'err', err.penyiapan, {tindakan:'cetak',berhasil:false,belumPasti:!!err.belumPasti});
      });
  });

  function lapor(pesan, nada, penyiapan, keadaanPrinter) {
    // Halaman penyiapan merangkum hasil tanpa membaca/menebak teks atau ACK.
    if (document.querySelector('[data-pos-printer]')) {
      document.dispatchEvent(new CustomEvent('teraflow:printer', {detail:{jenis:'hasil',pesan:pesan||'',nada:nada,penyiapan:!!penyiapan,keadaan:keadaanPrinter||null}}));
    }
    var kotak = document.querySelector('[data-hasil-cetak]');
    if (!kotak) { if (pesan) { alert(pesan); } return; }
    kotak.textContent = '';
    kotak.hidden = !pesan;
    if (!pesan) { return; }
    kotak.className = 'pesan pesan--' + (nada === 'ok' ? 'ok' : 'err');
    kotak.appendChild(document.createTextNode(pesan + ' '));
    if (penyiapan) {
      var a = document.createElement('a');
      a.href = PREFIX + '/printer';
      a.textContent = 'Buka penyiapan printer';
      kotak.appendChild(a);
    }
  }

  /* Kertas sudah keluar, jadi jejak audit harus menyebutkannya.
   *
   * Cetak ulang memakai alasan petugas yang sudah diperiksa sebelum kirim.
   * Pencatatan tetap melalui endpoint lama setelah ACK printer diterima. */
  function catatCetak() {
    var form = document.querySelector('form[data-catat-cetak]');
    if (!form) { return false; }
    var pilihan = form.querySelector('select[name="format"]');
    if (pilihan) { pilihan.value = '80MM'; }
    var alasan = form.querySelector('input[name="alasan"]');
    if (alasan && alasan.required && !alasan.value.trim()) {
      alasan.focus();
      return false;
    }
    form.submit();
    return true;
  }

  /* Penyiapan printer: simpan alamat, lalu uji. */
  document.addEventListener('click', function (e) {
    if (!e.target.closest) { return; }
    var tombol = e.target.closest('[data-simpan-printer]');
    if (!tombol) { return; }
    e.preventDefault();
    var isian = document.querySelector('input[name="printer_url"]');
    if (!isian) { return; }
    if (!simpanPrinter(isian.value)) {
      lapor('Perangkat ini menolak menyimpan setelan. ' +
            'Matikan mode penyamaran, lalu ulangi.', 'err');
      return;
    }
    var laporan = document.querySelector('[data-laporan-printer]');
    if (laporan) { laporan.hidden = true; laporan.textContent = ''; }
    lapor('Alamat printer disimpan di browser ini. Sambungan belum diperiksa.',
          'ok');
    document.querySelectorAll('[data-alamat-printer]').forEach(function (el) {
      el.textContent = alamatPrinter() || '(belum disetel)';
    });
    document.querySelectorAll('a[data-buka-printer]').forEach(function (a) {
      a.href = alamatPrinter() || '#';
    });
  });

  document.addEventListener('DOMContentLoaded', function () {
    var isian = document.querySelector('input[name="printer_url"]');
    if (isian && !isian.value) { isian.value = alamatPrinter(); }
    document.querySelectorAll('[data-alamat-printer]').forEach(function (el) {
      el.textContent = alamatPrinter() || '(belum disetel)';
    });
    document.querySelectorAll('a[data-buka-printer]').forEach(function (a) {
      a.href = alamatPrinter() || '#';
    });
  });


  // ── Pemeriksa sambungan printer ────────────────────────────────────
  //
  // Kegagalan menghubungi printer punya tiga sebab yang TERASA SAMA dari
  // layar — tombol ditekan, tidak ada yang keluar:
  //   · sertifikat printer belum diterima di perangkat ini;
  //   · izin akses jaringan lokal belum diklik;
  //   · perangkat memang tidak satu jaringan dengan printer.
  // Izin yang diketahui ditampilkan terpisah. Selain itu browser tidak
  // selalu membedakan TLS/CORS/jaringan; uji ePOS kosonglah bukti kesiapan.

  function periksaPrinter() {
    var alamat = alamatPrinter();
    var hasil = [];
    function catat(judul, nada, kata) { hasil.push({ judul: judul, nada: nada, kata: kata }); }
    if (!alamat) {
      catat('Alamat printer', 'err', 'Belum disetel di perangkat ini.');
      return Promise.resolve(hasil);
    }
    catat('Alamat printer', 'ok', alamat);
    if (!/^https:/i.test(alamat)) {
      catat('Awalan alamat', 'err', 'Gunakan alamat printer yang diawali https://.');
      return Promise.resolve(hasil);
    }
    return izinJaringanPrinter().then(function (izin) {
      catat('Izin jaringan lokal', izin === 'granted' ? 'ok' : izin === 'denied' ? 'err' : 'netral',
        izin === 'granted' ? 'Sudah diberikan.' : izin === 'denied'
          ? 'Ditolak. Izinkan akses jaringan lokal pada setelan situs browser ini.'
          : 'Browser belum melaporkan izin. Jawab Izinkan bila diminta.');
      return pastikanPrinter(alamat, document.body.dataset.printerDevid || 'local_printer');
    }).then(function () {
      catat('Layanan cetak', 'ok', 'Menjawab berhasil. Perangkat ini siap mencetak.');
      return hasil;
    }).catch(function (e) {
      // Browser menyamarkan TLS, CORS dan jaringan sebagai TypeError.
      // Jangan menyimpulkan sertifikat ditolak atau beda Wi-Fi dari itu.
      catat(e.penyiapan ? 'Sambungan printer' : 'Layanan cetak', 'err', e.message);
      return hasil;
    });
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest) { return; }
    var tombol = e.target.closest('[data-periksa-printer]');
    if (!tombol) { return; }
    e.preventDefault();
    if (tombol.dataset.sibuk === '1') { return; }
    var kotak = document.querySelector('[data-laporan-printer]');
    if (!kotak) { return; }
    var semula = tombol.textContent;
    tombol.dataset.sibuk = '1';
    tombol.textContent = 'Memeriksa…';
    kotak.hidden = false;
    kotak.textContent = 'Memeriksa…';

    periksaPrinter().then(function (hasil) {
      tombol.dataset.sibuk = '';
      tombol.textContent = semula;
      kotak.textContent = '';
      hasil.forEach(function (b) {
        var baris = document.createElement('div');
        baris.className = 'baris';
        baris.style.alignItems = 'flex-start';
        var kiri = document.createElement('span');
        var tanda = document.createElement('b');
        tanda.textContent = b.nada === 'ok' ? '✓ ' : (b.nada === 'err' ? '✕ ' : '· ');
        tanda.style.color = b.nada === 'ok' ? 'var(--aman)'
          : (b.nada === 'err' ? 'var(--bahaya)' : 'var(--tinta-2)');
        kiri.appendChild(tanda);
        kiri.appendChild(document.createTextNode(b.judul + ' — '));
        var ket = document.createElement('span');
        ket.className = 'bantu';
        ket.textContent = b.kata;
        kiri.appendChild(ket);
        baris.appendChild(kiri);
        kotak.appendChild(baris);
      });
      if (document.querySelector('[data-pos-printer]')) {
        document.dispatchEvent(new CustomEvent('teraflow:printer', {detail:{jenis:'pemeriksaan',hasil:hasil}}));
      }
    });
  });


  /* ── Layar yang menyegarkan diri ────────────────────────────────────
   *
   * Petugas mencatat penimbangan dari HP-nya, dan di layar orang lain yang
   * sedang membuka halaman yang sama tak terjadi apa-apa — ia harus
   * MEMATIKAN aplikasinya dulu baru perubahannya terlihat.
   *
   * Sebabnya bukan service worker. Yang disimpannya hanya kerangka aplikasi,
   * dan tiap navigasi selalu ke jaringan. Sebabnya lebih sederhana: tak ada
   * satu pun pemicu penyegaran. Halaman digambar sekali lalu diam selamanya,
   * dan aplikasi terpasang tak pernah dimuat ulang saat dibuka kembali dari
   * latar belakang — ia melanjutkan halaman yang sama.
   *
   * **Bedanya dengan Pos Produksi, dan ini yang menentukan bentuknya.** Di
   * sana ada pindah.js yang bisa menukar isi halaman tanpa memuat ulang. Di
   * sini tidak: halaman berpindah secara penuh, jadi menyegarkan berarti
   * `location.reload()` — dan reload MEMBUANG yang sedang diketik.
   *
   * Petugas mengisi borang sambil truk menunggu di jembatan. Satu reload yang
   * menghapus nomor polisi dan bobot yang baru diketik jauh lebih buruk
   * daripada angka yang telat semenit. Maka penyegaran otomatis di sini
   * OPT-IN per halaman, bukan berlaku di mana-mana: hanya halaman yang
   * menandai dirinya `data-segar-otomatis`, dan itu hanya layar BACA —
   * beranda, daftar, monitoring, laporan.
   */
  (function () {
    var badan = document.body;
    if (!badan || !badan.dataset || !badan.dataset.segarOtomatis) { return; }

    /* Dirapatkan dari 60 detik sejak denyutnya cuma BERTANYA, bukan
       mengunduh halaman. Tetap lebih longgar daripada Pos Produksi: di sini
       perubahan berarti memuat ulang seluruh halaman, jadi terlalu rapat
       membuat layar berkedip lebih sering daripada perlu. */
    var DENYUT = 15000;
    var kotor = false;    // ada yang sudah diketik di halaman ini
    var denyut = null;

    /* Sekali disentuh, halaman ini tak lagi boleh disegarkan sampai orangnya
       pergi sendiri. Borang saring memang memakai GET — isinya kembali dari
       alamat — tetapi yang BELUM dikirim tidak ada di alamat mana pun. */
    document.addEventListener('input', function (e) { if (!e.target.form || (e.target.form.method || 'get').toLowerCase() !== 'get') kotor = true; }, true);
    document.addEventListener('change', function (e) { if (!e.target.form || (e.target.form.method || 'get').toLowerCase() !== 'get') kotor = true; }, true);

    function adaAntrean() {
      /* Antrean luring berisi = sinyal sedang buruk. Reload saat itu bisa
         mendarat di halaman luring, dan petugas kehilangan layarnya karena
         kami mencoba menolongnya. */
      if (window.timbanganLuring && window.timbanganLuring.adaTertunda()) { return true; }
      try {
        var isi = JSON.parse(localStorage.getItem(GUDANG) || '[]');
        return isi.length > 0;
      } catch (e) { return true; }   // ragu = jangan ganggu
    }

    function bolehSegar() {
      if (document.visibilityState !== 'visible') { return false; }
      if (kotor) { return false; }
      var f = document.activeElement;
      if (f && /^(INPUT|SELECT|TEXTAREA)$/.test(f.tagName)) { return false; }
      if (adaAntrean()) { return false; }
      return true;
    }

    /* Diperiksa dulu, baru dimuat ulang.
     *
     * Reload yang tak mengubah apa pun tetap terlihat: layar berkedip,
     * gulungan kembali ke atas. Berkedip tiap menit tanpa alasan mengajari
     * orang bahwa aplikasinya rewel. Jadi isinya diambil diam-diam dan
     * dibandingkan; kalau sama persis, tak terjadi apa-apa. */
    /* Penanda keadaan: bertanya dulu, mengunduh belakangan.
     *
     * `null` berarti BELUM TAHU, dan itu diperlakukan sebagai "mungkin
     * berubah" — halamannya tetap diperiksa. Keadaan itu terjadi tepat
     * sesudah aplikasi dibuka, dan di situlah justru yang paling mungkin
     * basi: telepon bisa saja sejam di dalam kantong.
     *
     * Gagal bertanya juga `null`: jaringan putus, atau sesi habis dan yang
     * datang halaman masuk, bukan JSON. Yang terakhir penting — kalau
     * pengalihan ke halaman masuk ditafsirkan sebagai "ada perubahan",
     * layarnya akan memuat ulang tanpa henti. */
    var penanda = null;

    function tanyaPenanda() {
      return fetch(PREFIX + '/keadaan', { credentials: 'same-origin', cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          if (!j || !j.n) { return null; }
          if (j.versi && VERSI_JALAN && String(j.versi) !== VERSI_JALAN) { tawarkanVersi(); }
          return String(j.n);
        })
        .catch(function () { return null; });
    }

    /* Pil versi baru: server sudah memegang berkas lain. Satu ketukan yang
       memuat ulang — TIDAK sendiri: petugas yang sedang mengisi timbang
       akan kehilangan isiannya. */
    function tawarkanVersi() {
      if (document.querySelector('.pil-versi')) { return; }
      var pil = document.createElement('button');
      pil.type = 'button';
      pil.className = 'pil-versi';
      pil.textContent = 'Versi baru — ketuk untuk muat ulang';
      pil.addEventListener('click', function () { location.reload(); });
      document.body.appendChild(pil);
    }

    /* ── Pil "perubahan baru" ──
       Layar TIDAK memuat ulang sendiri di bawah jari petugas (dulu:
       location.reload() diam-diam — baris bergeser tepat saat ditekan). Pil
       ini yang muncul; ketukannya yang memuat ulang. Kecuali layar tanpa
       sasaran ketukan (`data-segar-sendiri`). */
    var jumlahPerubahan = 0;

    function tawarkanPerubahan() { periksaIsi(); }

    function adaPerubahan() { periksaIsi(); }

    function periksa() {
      if (!bolehSegar()) { return; }
      statistik.tanya++;
      tanyaPenanda().then(function (p) {
        var sama = (p !== null && penanda !== null && p === penanda);
        if (p !== null) { penanda = p; }
        if (!sama) { periksaIsi(); }   // tak sama: baru halamannya diambil
      });
    }

    /* ── Kanal dorong (SSE) — jalur pertama; denyut jadi jalur kedua ── */
    var jalur = 'denyut';
    var aliran = null;
    var jedaSambung = 1000;
    var sambungUlang = null;
    var statistik = { tanya: 0, dorongan: 0 };

    function sambungAliran() {
      if (aliran || !window.EventSource || document.visibilityState !== 'visible') { return; }
      var es = new EventSource(PREFIX + '/aliran');
      aliran = es;
      es.onmessage = function (e) {
        var j = null;
        try { j = JSON.parse(e.data); } catch (x) { j = null; }
        if (!j || !j.n) { return; }
        jalur = 'sse';
        jedaSambung = 1000;
        statistik.dorongan++;
        if (j.versi && VERSI_JALAN && String(j.versi) !== VERSI_JALAN) { tawarkanVersi(); }
        var p = String(j.n);
        if (penanda !== null && p !== penanda) { adaPerubahan(); }
        penanda = p;
      };
      es.onerror = function () {
        es.close();
        if (aliran === es) { aliran = null; }
        jalur = 'denyut';
        if (sambungUlang) { return; }
        sambungUlang = setTimeout(function () { sambungUlang = null; sambungAliran(); }, jedaSambung);
        jedaSambung = Math.min(jedaSambung * 2, 30000);
      };
    }

    function putuskanAliran() {
      if (aliran) { aliran.close(); aliran = null; }
      jalur = 'denyut';
    }
    window.timbangan.jalur = function () { return jalur; };
    window.timbangan.statistik = function () { return { tanya: statistik.tanya, dorongan: statistik.dorongan }; };

    var membacaIsi = false;
    function periksaIsi() {
      if (membacaIsi || !bolehSegar()) { return; }
      membacaIsi = true;
      var alamatSegar = location.href, akunSegar = badan.dataset.akunId;
      var sekarang = document.querySelector('.bingkai');
      if (!sekarang) { membacaIsi=false; return; }
      sekarang = sekarang.cloneNode(true);
      sekarang.querySelectorAll('[data-luring-panel]').forEach(function (e) { e.remove(); });
      var lama = sekarang.innerHTML;

      fetch(location.href, { credentials: 'same-origin', cache: 'no-store' })
        .then(function (r) { return r.ok && !r.redirected ? r.text() : null; })
        .then(function (teks) {
          if (!teks || location.href !== alamatSegar) { return; }
          // Diperiksa LAGI: orangnya bisa mulai mengetik tepat selagi
          // permintaan ini di jalan.
          if (!bolehSegar()) { return; }
          var doc = new DOMParser().parseFromString(teks, 'text/html');
          var baru = doc.querySelector('.bingkai');
          if (baru) baru.querySelectorAll('[data-luring-panel]').forEach(function (e) { e.remove(); });
          if (!baru || baru.innerHTML === lama) { return; }
          if (!doc.body || doc.body.dataset.akunId !== akunSegar || !window.KEADAAN_BACA) return;
          var root=document.querySelector('.bingkai'),keadaan=KEADAAN_BACA.ambil(root);
          KEADAAN_BACA.tukar(root,baru);
          KEADAAN_BACA.pulihkan(root,keadaan);
          document.title=doc.title;
          var pil=document.querySelector('.pil-perubahan');if(pil)pil.remove();
          window.dispatchEvent(new Event('teraflow:data'));
        })
        .catch(function () { /* data terakhir tetap terlihat saat jaringan terputus */ }).finally(function () { membacaIsi=false; });
    }

    function mulaiDenyut() {
      if (denyut) { return; }
      denyut = setInterval(function () { if (jalur !== 'sse') { periksa(); } }, DENYUT);
    }

    function hentikanDenyut() {
      if (denyut) { clearInterval(denyut); denyut = null; }
    }

    /* Kembali ke depan — inilah yang menjawab keluhannya. Telepon dikantongi,
       dikeluarkan lagi, dan yang pertama dilihat orang harus keadaan
       sekarang, bukan keadaan saat ia mengantonginya. */
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') { periksa(); mulaiDenyut(); jedaSambung = 1000; sambungAliran(); }
      else { hentikanDenyut(); putuskanAliran(); }
    });

    /* Sebagian peramban mengembalikan halaman dari simpanan maju-mundurnya
       tanpa memicu visibilitychange sama sekali. */
    window.addEventListener('pageshow', function (e) {
      if (e.persisted) { kotor = false; periksa(); }
    });

    if (document.visibilityState === 'visible') { mulaiDenyut(); sambungAliran(); }
  })();

})();

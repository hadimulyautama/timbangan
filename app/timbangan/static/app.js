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
  var GUDANG = 'timbangan-antrean';   // localStorage: kiriman menunggu jaringan

  // ── Antrean kiriman ────────────────────────────────────────────────

  function bacaAntrean() {
    try { return JSON.parse(localStorage.getItem(GUDANG) || '[]'); }
    catch (e) { return []; }
  }

  function tulisAntrean(daftar) {
    try { localStorage.setItem(GUDANG, JSON.stringify(daftar)); }
    catch (e) { /* penyimpanan penuh atau diblokir — abaikan diam-diam */ }
    tampilkanJumlah();
  }

  function tampilkanJumlah() {
    var n = bacaAntrean().length;
    document.querySelectorAll('[data-antrean]').forEach(function (el) {
      el.textContent = n ? '· ' + n + ' menunggu terkirim' : '';
    });
  }

  function antrekan(kiriman) {
    var daftar = bacaAntrean();
    // Dikunci pada kode transaksi: mengantre dua kali tidak menggandakan.
    var i = daftar.findIndex(function (k) {
      return k.kode === kiriman.kode && k.url === kiriman.url;
    });
    if (i >= 0) { daftar[i] = kiriman; } else { daftar.push(kiriman); }
    tulisAntrean(daftar);
  }

  function kirimAntrean() {
    var daftar = bacaAntrean();
    if (!daftar.length || !navigator.onLine) { return; }

    var kiriman = daftar[0];
    fetch(kiriman.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(kiriman.data),
      credentials: 'same-origin'
    }).then(function (r) {
      // 4xx berarti server menolak isinya — mengirim ulang selamanya tidak
      // akan menolong, jadi baris itu dibuang agar antrean tidak macet.
      if (r.ok || (r.status >= 400 && r.status < 500)) {
        tulisAntrean(bacaAntrean().slice(1));
        kirimAntrean();
      }
    }).catch(function () { /* masih tanpa jaringan — coba lagi nanti */ });
  }

  // ── Penanda luring ─────────────────────────────────────────────────

  function perbaruiStatusJaringan() {
    document.body.classList.toggle('luring', !navigator.onLine);
    if (navigator.onLine) { kirimAntrean(); }
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
    var bersih = bakukanAngka(e.target.value);
    if (bersih !== '' && !isNaN(Number(bersih))) { e.target.value = bersih; }
  }, true);

  // ── Penahan kirim ganda ────────────────────────────────────────────

  document.addEventListener('submit', function (e) {
    var form = e.target;
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
    if (opsi.length < 12) { return; }   // masih nyaman sebagai dropdown biasa

    var bungkus = document.createElement('div');
    bungkus.className = 'cari';
    var kotak = document.createElement('input');
    kotak.type = 'text';
    kotak.className = 'fld teks';
    kotak.setAttribute('autocomplete', 'off');
    kotak.setAttribute('enterkeyhint', 'search');
    kotak.placeholder = pilih.dataset.cari || 'Ketik untuk mencari…';
    var hasil = document.createElement('div');
    hasil.className = 'cari__hasil';
    var terpilih = document.createElement('div');
    terpilih.className = 'cari__terpilih';

    bungkus.appendChild(kotak);
    bungkus.appendChild(hasil);
    pilih.parentNode.insertBefore(bungkus, pilih);
    pilih.parentNode.insertBefore(terpilih, pilih.nextSibling);
    pilih.style.display = 'none';

    function tampilkanTerpilih() {
      var v = pilih.value;
      if (!v) { terpilih.textContent = ''; return; }
      var ada = opsi.filter(function (o) { return o.nilai === v; })[0];
      terpilih.innerHTML = '';
      var teks = document.createElement('span');
      teks.textContent = 'Terpilih: ' + (ada ? ada.label : v);
      var hapus = document.createElement('button');
      hapus.type = 'button';
      hapus.textContent = 'Ganti';
      hapus.addEventListener('click', function () {
        pilih.value = '';
        kotak.value = '';
        tampilkanTerpilih();
        kotak.focus();
      });
      terpilih.appendChild(teks);
      terpilih.appendChild(hapus);
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
          kotak.value = '';
          hasil.innerHTML = '';
          tampilkanTerpilih();
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

    kotak.addEventListener('input', gambar);
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

    tampilkanTerpilih();
  }

  document.querySelectorAll('select[data-cari]').forEach(pasangPencarian);

  // ── Mulai ──────────────────────────────────────────────────────────

  perbaruiStatusJaringan();
  tampilkanJumlah();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register(PREFIX + '/sw.js', { scope: PREFIX + '/' })
      .catch(function () { /* tanpa service worker aplikasi tetap jalan */ });
  }

  window.timbangan = { antrekan: antrekan, kirimAntrean: kirimAntrean };

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
    if (!perlu_lembar_bagikan()) { return; }   // biarkan tautan bekerja apa adanya
    e.preventDefault();
    unduhBerkas(tautan);
  });

  function unduhBerkas(tautan) {
    if (tautan.dataset.sibuk === '1') { return; }
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
        var cocok = cd.match(/filename="?([^"]+)"?/);
        return r.blob().then(function (blob) {
          return { blob: blob, nama: cocok ? cocok[1] : 'unduhan.csv' };
        });
      })
      .then(function (hasil) {
        var jenis = hasil.blob.type || 'text/csv';
        var berkas;
        try {
          berkas = new File([hasil.blob], hasil.nama, { type: jenis });
        } catch (err) { berkas = null; }

        if (berkas && navigator.canShare &&
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

  /* Kirim satu perintah cetak. `sumber` adalah alamat di server ini yang
   * menyusun perintahnya — perangkat tidak pernah menyusun sendiri. */
  function cetakKePrinter(sumber) {
    var alamat = alamatPrinter();
    if (!alamat) {
      return Promise.reject(
        KirimGagal('Printer belum disetel di perangkat ini.', true));
    }

    return fetch(sumber, { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) { throw new Error('Gagal menyiapkan struk (' + r.status + ').'); }
        return r.text();
      })
      .then(function (perintah) {
        var devid = document.body.dataset.printerDevid || 'local_printer';
        var tujuan = alamat + '/cgi-bin/epos/service.cgi?devid=' +
                     encodeURIComponent(devid) + '&timeout=10000';

        // AbortController dipakai langsung, bukan AbortSignal.timeout: yang
        // kedua belum ada di Safari lama, dan tablet gudang jarang diperbarui.
        var henti = new AbortController();
        var jam = setTimeout(function () { henti.abort(); }, TENGGAT_MS);

        return fetch(tujuan, {
          method: 'POST',
          headers: { 'Content-Type': 'text/xml; charset=utf-8' },
          body: perintah,
          signal: henti.signal
        }).then(function (r) {
          clearTimeout(jam);
          return r.text();
        }, function (err) {
          clearTimeout(jam);
          // Baik permintaan yang ditolak maupun yang menggantung sampai batas
          // waktu berujung di sini, dan keduanya bermuara pada hal yang sama:
          // browser ini belum diizinkan menghubungi printer.
          throw KirimGagal(
            err && err.name === 'AbortError'
              ? 'Printer tidak menjawab dalam ' + (TENGGAT_MS / 1000) +
                ' detik. Biasanya izin jaringan lokal belum diberikan, atau ' +
                'perangkat ini ada di jaringan yang berbeda.'
              : 'Perangkat ini belum bisa menghubungi printer di ' + alamat + '.',
            true);
        });
      })
      .then(function (jawaban) {
        if (/success="true"/.test(jawaban)) { return true; }
        var kode = (jawaban.match(/code="([^"]*)"/) || [])[1] || '';
        throw new Error(ARTI_GAGAL[kode] ||
          ('Printer menolak mencetak' + (kode ? ' (' + kode + ')' : '') + '.'));
      });
  }

  /* Tombol cetak. `data-cetak` berisi alamat penyusun perintah di server. */
  document.addEventListener('click', function (e) {
    if (!e.target.closest) { return; }
    var tombol = e.target.closest('[data-cetak]');
    if (!tombol) { return; }
    e.preventDefault();
    if (tombol.dataset.sibuk === '1') { return; }

    var label = tombol.querySelector('[data-teks]') || tombol;
    var semula = label.textContent;
    tombol.dataset.sibuk = '1';
    label.textContent = 'Mencetak…';
    lapor('');

    cetakKePrinter(tombol.dataset.cetak)
      .then(function () {
        tombol.dataset.sibuk = '';
        label.textContent = semula;
        lapor('Struk keluar di printer.', 'ok');
        catatCetak();
      })
      .catch(function (err) {
        tombol.dataset.sibuk = '';
        label.textContent = semula;
        lapor(err.message, 'err', err.penyiapan);
      });
  });

  function lapor(pesan, nada, penyiapan) {
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
   * Hanya cetakan PERTAMA yang dicatat sendiri. Cetak ulang wajib beralasan,
   * dan alasan tidak boleh dikarang aplikasi — formulirnya dibiarkan terisi
   * separuh supaya petugas mengetiknya. */
  function catatCetak() {
    var form = document.querySelector('form[data-catat-cetak]');
    if (!form) { return; }
    var pilihan = form.querySelector('select[name="format"]');
    if (pilihan) { pilihan.value = '80MM'; }
    var alasan = form.querySelector('input[name="alasan"]');
    if (alasan && alasan.required) {
      alasan.focus();
      return;
    }
    form.submit();
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
    lapor('Alamat printer disimpan di perangkat ini. Sekarang coba uji cetak.',
          'ok');
    document.querySelectorAll('[data-alamat-printer]').forEach(function (el) {
      el.textContent = alamatPrinter();
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


})();

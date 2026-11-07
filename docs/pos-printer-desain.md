# Pos & printer ringkas

Satu kartu memuat alamat, simpan, pemeriksaan sambungan dan cetak uji. Petunjuk
memakai `_panduan.html` dan `panduan.css`, termasuk cadangan native tanpa JS.
Kode pos akun, sertifikat/izin, penggaris 48 kolom, PDF dan penjelasan jalur data
tetap tersedia. Uraian panjang dipindah ke Petunjuk; hasil terbaru tampil singkat.

Transport printer, validasi XML/ACK, URL, timeout, penahanan klik ganda,
penyimpanan lokal dan audit tetap memakai app.js. Tambahan hanya event hasil
terstruktur untuk tampilan penyiapan; halaman cetak transaksi tetap sama.
Sambungan hanya dinyatakan berhasil berdasarkan konfirmasi layanan cetak asli.
Izin yang tidak dilaporkan browser tidak dianggap gagal secara otomatis.

Ketikan belum disimpan mencegah pengiriman ke alamat lama. Gagal menyimpan
mempertahankan ketikan. Saat permintaan berjalan alamat tidak dapat diubah.
Hasil cetak yang belum pasti tetap meminta pemeriksaan kertas sebelum ulang;
perintah struk tidak dikirim ulang otomatis. Uji cetak tidak membuat tiket atau audit transaksi.

Kedua pintu /printer dan /pengaturan?bagian=printer memakai partial yang sama.
Tidak ada perubahan route, query, model, database atau migrasi.


## Pemulihan sambungan

Setiap cetak langsung memeriksa ePOS dengan XML kosong terlebih dahulu.
Pemeriksaan kosong boleh diulang satu kali setelah 500 ms ketika transport
terputus; setiap permintaan punya AbortController dan tenggat yang mencakup
seluruh respons. Printer yang menyatakan kertas habis/penutup terbuka tidak
dicoba lagi. XML struk tetap dikirim sekali; ACK hilang tetap belum pasti.
Kegagalan sebelum pengiriman struk tidak dianggap kertas mungkin sudah keluar.
Pekerjaan cetak dan audit tetap memakai alur lama.

Tidak ada status koneksi permanen yang disimpan: HP yang kembali dari tidur
atau pindah jaringan memeriksa keadaan baru pada cetakan berikutnya. Halaman
penyiapan memeriksa lagi saat kembali dari tab sertifikat, kembali online,
atau dipulihkan dari bfcache, selama tidak sibuk dan alamat tidak sedang diedit.

Pemeriksaan memakai layanan ePOS langsung, tanpa bergantung pada halaman
admin printer. TypeError browser tidak membuktikan sertifikat ditolak atau
Wi-Fi berbeda. Sertifikat swa-tanda/izin browser tetap harus ditangani pada
perangkat; kode web tidak dapat mengesahkan sertifikat printer. Untuk menghapus
keharusan menerima pengecualian sertifikat berulang, diperlukan sertifikat
tepercaya pada printer atau layanan cetak lokal yang dikelola terpisah.

Rujukan protokol status tanpa kertas:
https://files.support.epson.com/pdf/pos/bulk/epos-print_xml_um_en_rev_af.pdf


## Rangkap operasional

Satu pekerjaan struk transaksi langsung ke printer berisi dua lembar, bertanda
RANGKAP 1/2 dan 2/2, dengan potong kertas setelah masing-masing lembar.
Nomor tiket, revisi, nomor cetakan dan seluruh angka sama. Kedua lembar
menghasilkan satu riwayat pekerjaan, bukan dua transaksi atau dua cetak ulang.
Cetak ulang tetap meminta alasan dan kembali menghasilkan dua rangkap.
PDF digital dan cetak uji tidak digandakan. Konten pekerjaan lama yang sudah
dibekukan tidak diubah; aturan dua rangkap berlaku pada pekerjaan baru.

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
tidak ada retry otomatis. Uji cetak tidak membuat tiket atau audit transaksi.

Kedua pintu /printer dan /pengaturan?bagian=printer memakai partial yang sama.
Tidak ada perubahan route, query, model, database atau migrasi.

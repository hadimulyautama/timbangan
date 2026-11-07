# Koreksi dan detail riwayat timbang

Desain yang disetujui 7 November 2026 diterapkan pada koreksi tiket terbuka,
koreksi riwayat selesai, dan detail barang masuk (termasuk titipan jasa).
Halaman detail jenis lain tetap menggunakan tampilannya yang sudah ada.

Koreksi tetap satu formulir dengan nama field, nilai asli, presisi, versi,
required, action, dan handler lama. Kendaraan diprioritaskan pada tiket terbuka;
dua bacaan pada riwayat selesai memakai ukuran sama. Dokumen berada dalam
disclosure. Pratinjau tetap dari endpoint server; browser tidak menghitung ulang.
Hasil sebelum/sesudah ditonjolkan dengan memindahkan node asli. Koreksi terbuka
tetap menampilkan status perhitungan yang belum final. Alasan, konflik versi,
retensi isian saat gagal, pemeriksaan tautan, audit dan izin tetap sama.

Detail barang masuk memprioritaskan identitas, hasil resmi dan status kontrol.
Perhitungan, penerimaan/QC dan jejak menjadi tiga disclosure. Semua data sumber,
putaran QC, pesanan jasa, bobot sementara, cakupan izin, riwayat cetak dan audit
tetap tersedia. Informasi yang belum tersedia tidak diganti nol. Total tara
tetap nilai tersimpan dan sudah termasuk tara lain.

Timbang berikutnya dan Tiket Aktif tidak berada pada area kontrol detail;
akses tetap lewat navigasi utama. Lanjut timbang kedua untuk tiket yang masih
terbuka dipertahankan karena merupakan kelanjutan tiket yang sama.

Panduan, pemeriksaan dan tindakan memakai dialog native dari komponen bersama.
Node formulir asli dipindahkan, tidak disalin. Tanpa JavaScript, disclosure
cadangan tetap dapat dibuka. Handler pemeriksaan.js dan perilaku tindakan lama
tetap dipakai; kegagalan respons tidak menghapus alasan atau mengonfirmasi
penyimpanan. URL tab lama dan #pemeriksaan tetap dipetakan.

Tidak ada perubahan perhitungan, layanan, database, migrasi, atau pembatasan
otorisasi. Versi aset dinaikkan dan aset baru ditambahkan ke precache.

Area kontrol daftar riwayat turut diseragamkan: Cari dan Filter sejajar pada
desktop; periode serta empat filter berada pada satu panel native. Panduan
memakai komponen bersama. Form GET, nama parameter, tanggal, filter aktif, CSV
periode, baris tabel/kartu, aksi, izin, pilihan massal dan paginasi dipertahankan.

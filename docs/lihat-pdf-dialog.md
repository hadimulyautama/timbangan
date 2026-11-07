# Dialog PDF 80 mm bersama

Lihat merupakan tombol dalam macro _rincian_kontrol.html untuk semua jenis detail. Penampil bersama lihat-pdf-dialog.js memakai PDF asli dari GET /cetak/80mm yang sama. Seluruh halaman dirender dengan PDF.js versi terkunci (metadata dan lisensi di static/vendor/pdfjs), tanpa iframe, plugin PDF browser, CDN runtime, tab baru, atau perubahan URL detail. Judul, tombol tutup, zoom, status dan pesan gagal konsisten di desktop/ponsel. Teks PDF disertakan bagi pembaca layar. Menutup dialog membatalkan fetch/render dan melepas dokumen/worker; fokus kembali ke Lihat. Tombol Coba lagi mempertahankan halaman dan tidak mencetak.

PDF.js: https://mozilla.github.io/pdf.js/examples/ . Berkas resmi npm diverifikasi SHA-512 terhadap metadata registry; renderer dan worker disajikan dari origin aplikasi. Tidak ada perubahan isi PDF, aturan kerahasiaan, audit, hitungan, atau protokol cetak.

Periksa sambungan Pos & printer tetap pemeriksaan langsung tanpa kertas. Hasil gagal menampilkan langkah relevan di halaman yang sama, bukan CTA Buka Petunjuk. Petunjuk tetap tersedia secara opsional dari judul. Akses alamat printer hanya melalui klik pengguna jika diperlukan, bukan otomatis.

Tidak ada migrasi. Rollback ke commit sebelumnya tidak mengubah data atau pekerjaan cetak.

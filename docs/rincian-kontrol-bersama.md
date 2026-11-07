# Area kontrol detail timbang bersama

Seluruh detail menggunakan macro `_rincian_kontrol.html` dan kelas
`tf-detail-controls` pada `rincian-kontrol.css`. Barang masuk, keluar, transfer,
retur pelanggan, serta detail umum (termasuk retur supplier, jasa timbang dan
partai) mengikuti satu aturan susunan dan status tombol.

Kembali mempertahankan konteks. Pratinjau/cetak hanya untuk tiket selesai dan
aktif; jumlah cetak tetap terbaca. Tiket terbuka melanjutkan tiket/partai yang
sama. Slot Panduan dan tindakan detail masuk memakai node serta handler asli.
Timbang berikutnya dan daftar Tiket Aktif hanya lewat navigasi aplikasi.
Semua informasi, tautan PadiFlow, tindakan, izin dan formulir lama dipertahankan.

Desain isi detail barang keluar sudah diterapkan sesuai mockup. Hasil satu truk
menjadi ringkasan utama; muatan per pelanggan, perhitungan dan jejak memakai
disclosure. Seluruh loop rincian asli dipertahankan, termasuk identitas sumber,
subtotal, tara, petugas, catatan dan riwayat cetak. Pemeriksaan serta tindakan
memindahkan node formulir asli ke dialog bersama. URL tab lama, hash pemeriksaan,
formulir tanpa JavaScript dan retensi isian saat gagal tetap didukung.

Handler dialog/disclosure yang sama dipakai detail masuk dan keluar; halaman
transfer, retur dan umum hanya menggunakan kontrol bersama, tanpa desain isi baru.

# Tindakan lainnya bersama

Semua detail riwayat memakai dropdown di macro _rincian_kontrol.html, tepat sesudah Panduan bila tersedia. Pilihan diambil dari rincian_tindakan.html yang sudah disaring server: Koreksi, Batalkan transaksi/Hapus tiket ini, Hapus permanen untuk Super Admin, serta keterangan penguncian. Tidak menambah hak akses atau menggandakan tombol bagian bawah.

Koreksi tetap menuju formulir koreksi asli. Pembatalan/penghapusan menampilkan satu formulir terpilih di dialog. Node asli dipindahkan, bukan disalin; nama field, required, label, nilai, alasan, konfirmasi nomor tiket dan endpoint dipertahankan. Penanganan POST dipusatkan di tindakan-dropdown.js dengan validasi respons, pencegahan kirim ganda, retensi isian dan konteks kembali yang sama. Form gagal tidak otomatis dikirim ulang. Tanpa JS tampilan tindakan lama tetap tersedia.

Tidak ada migrasi. Rollback ke commit sebelumnya mempertahankan seluruh transaksi/audit.

Penutupan menu ditangani eksplisit pada pemicu, pointer/click di luar dalam fase capture, Escape pada dokumen, perpindahan fokus, dan pagehide. Dengan demikian penutupan tidak bergantung pada fokus summary atau event bubbling komponen lain. aria-expanded mengikuti keadaan sebenarnya. Hak akses dan endpoint server tidak diubah.

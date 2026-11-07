# Pulihkan dan hapus draf perangkat

Banner menampilkan baris per draf: Pulihkan draf dan rincian di kiri, tombol sekunder Hapus draf di kanan. Konfirmasi menyebut draf terpilih dan kehilangan isian lokal; bukan penghapusan tiket.

Pulihkan tetap menuju jalur asli, termasuk /jasa/, dengan seluruh FormData dan presisi tersimpan. Membuka draf lain pada formulir yang sama memuat ulang dokumen agar hash tidak hanya berubah tanpa memulihkan isian. Draf yang dipulihkan memakai id asal saat disunting, termasuk di tab lain, sehingga tidak membuat salinan draf baru.

Hapus memakai transaksi IndexedDB atomik draf+kiriman: periksa akun, jalur, kunci, data terpilih dan kiriman belum terkonfirmasi. Draf berubah ditolak dan daftar diperbarui; kiriman tertunda tetap utuh. Hanya id terpilih dihapus, draf lain/akun lain tidak disentuh. Formulir aktif yang drafnya dihapus dibuka sebagai isian baru; tab lama tidak boleh menyimpan/mengirim kembali draf terhapus tanpa mulai formulir baru.

Skema IndexedDB tetap timbangan-luring-v2 versi 1. Tidak ada migrasi server atau endpoint penghapusan transaksi baru. Tanda terima server, status antrean, sinkronisasi, dan hak akses tetap memakai kontrak lama. Rollback ke commit sebelumnya mempertahankan seluruh data IndexedDB yang masih tersimpan.

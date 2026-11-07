# Cetak langsung 80 mm

Semua detail riwayat memakai kontrol bersama: Cetak, Lihat, dan Bagikan. Cetak membuka dialog lokal, membaca konteks terbaru tanpa membuat pekerjaan, lalu menjalankan mesin pekerjaan asli 80 mm. Cetak pertama langsung dikirim, cetak ulang meminta alasan dalam dialog. ACK, kunci idempoten, revisi, izin dan konfirmasi hasil tak pasti tetap sama. Tidak berpindah halaman. Riwayat cetak dibaca ulang setelah ACK; kegagalan membaca ulang tidak mengirim kertas lagi.

Lihat membuka PDF di tab terpisah. Bagikan memakai lembar berbagi perangkat, atau mengunduh berkas jika browser tidak mendukung berbagi. Keduanya memakai URL GET 80 mm yang sama, tanpa alasan, pekerjaan atau hitungan cetak. Tidak ada pilihan NCR atau pilihan ukuran baru. Endpoint dan catatan lama tetap dapat dibaca; pekerjaan NCR/PDF lama hanya dapat dituntaskan, tanpa ditawarkan sebagai cetakan baru.

Tidak ada migrasi. Rollback ke commit sebelumnya mempertahankan seluruh pekerjaan dan audit.

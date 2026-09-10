# Pos Timbang — PT Hadi Mulya Utama

Webapp pencatat penimbangan truk: bruto, tara, netto, kontrol terhadap nota &
surat jalan, lalu cetak bukti timbang. Dipakai petugas di pos, di ponsel,
sering sambil truk menunggu.

## Tempat kerja

Empat repo BERSEBELAHAN di satu folder induk (`Hadi Mulya Systems/`):
`produksi/`, `kantor/`, `timbangan/` (ini), `website/`.

Lahir di dalam repo `penggilingan-beras` dan dipisah ke sini pada 31 Agustus
2026, supaya rilisnya tak lagi menunggu — dan tak lagi memicu — rilis sistem
penggilingan dan Kantor AI.

**Basis datanya tetap SATU.** Itu pilihan, bukan kelalaian: memisahkan basis
data berarti memindahkan data produksi dan membangun sinkronisasi pemasok,
sementara yang dibutuhkan hanyalah kemandirian rilis. Konsekuensinya nyata —
tabel yang tampak milik modul ini dibaca juga oleh produksi. Sebelum
menghapus massal, periksa siapa lagi pembacanya.

## Bahasa

Kode, komentar, dan teks layar berbahasa **Indonesia**. Komentarnya panjang
dan menjelaskan **kenapa**, bukan apa. Ikuti gayanya.

## Dua aturan yang membentuk modul ini

**Tak ada satu pun kolom harga.** Disengaja. Petugas pos mencatat BERAT;
harga urusan orang lain di layar lain. Kolom harga di sini berarti angka uang
di tangan orang yang tak berwenang melihatnya, dan angka kedua yang cepat
atau lambat berselisih dengan yang pertama.

**Aturannya hidup di DATA, bukan di kode.** Jenis muatan, pemasok, dan
kaidahnya dibaca dari basis data supaya berubah tanpa rilis. Menambah
`if jenis == "..."` di kode berarti mengembalikan aturan ke tempat yang cuma
bisa diubah lewat deploy.

## Hubungan dengan produksi

Timbangan adalah **otoritas berat**. Sistem produksi MENAUT ke tiket timbang
(`timbangan_transaksi_id`, unik) alih-alih mengetik ulang bobotnya — itu yang
mencegah dobel-entry gabah dan PK masuk. Aksi "Gabah masuk" di Pos Produksi
wajib memilih tiket timbang; ia tak menerima berat yang diketik langsung.

## Uji

```
.venv/bin/python -m pytest -q
```

## Rahasia Railway — aturan keras

Sebuah kunci akun layanan Google pernah BOCOR ke transkrip lewat
`railway variables --kv`.

- **JANGAN** menjalankan perintah yang membaca NILAI variabel.
- **JANGAN** memakai `--kv`, dalam bentuk apa pun.
- **JANGAN** memakai `railway config pull --include-variables`.
- Melihat NAMA variabel dengan aman: `railway variable list --service
  timbangan --json`, disalurkan ke pengurai JSON yang mencetak kuncinya saja.

## Cetak

Struk 80 mm lewat ePOS-Print pada Epson TM-m30III. Model itu **tidak** punya
AirPrint — jangan menyarankannya.

Catatan lebih panjang ada di `docs/ingatan/` pada repo `produksi/`, dan
rancangan modul ini di `docs/RANCANGAN.md`.

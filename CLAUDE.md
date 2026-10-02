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

## Identitas bersama (sejak 13 September 2026, Tahap 2 rancang ulang)

Sandi, sesi, peran, status, dan "boleh masuk?" milik paket `hmu_identitas`
(repo `core/`, di-vendor ke `hmu_identitas/` bersama `hmu_core/` oleh
`core/scripts/sinkron.py`; jangan sunting keduanya di sini). `Base`
SQLAlchemy modul ini = `hmu_core.Base`, dan `users`/`suppliers`/`pelanggan`
dipetakan model hmu_core yang lengkap.

`timbangan_akun` punya dua rupa: **tertaut** (`akun_id` → `produksi_akun`;
kredensial/peran/status/nama milik akun bersama, kolomnya di sini hanya
cermin yang disinkronkan tiap masuk; di sini tinggal kode perangkat) dan
**lama** (`akun_id` kosong; masih masuk dengan sandinya sendiri). Token lama
tetap diterima untuk profil yang baru ditautkan sampai orangnya masuk lagi.
Penautan: `scripts/identitas_tautkan.py` (rencana → `--terapkan` →
`--lepas` untuk mundur). Pos timbang TIDAK lagi membuat akun; layar Pengguna
hanya menautkan akun bersama + kode perangkat. Pintu: operator, admin,
superadmin (`pintu.TIMBANGAN`). Uji: `tests/timbangan/test_identitas*.py`,
`tests/pg/`, `tests/test_identitas_paket.py` (AST peran harfiah).

## Barang masuk JASA (sejak 1 Oktober 2026)

Barang yang **DITITIPKAN** pelanggan untuk digiling, bukan dibeli. Dari sudut
pos timbang yang berubah **satu** hal: lawan transaksinya PELANGGAN, padahal
arahnya tetap MASUK.

**Tidak ada jenis timbang baru.** Cara menimbang, tara, dan ambangnya sama
persis — `GABAH_KERING_JASA` akan menggandakan tiga jenis jadi enam,
menggandakan aturan taranya, dan memberi petugas enam tombol berpasangan mirip
untuk salah pilih.

**Komoditas mana yang boleh dijasakan ada di DATA**: `timbangan_jenis.boleh_jasa`
(migrasi 0039). Hari ini hanya `GABAH_KERING` — bukan karena jasa terbatas pada
gabah kering, melainkan karena hanya jalur itu yang sudah utuh di produksi:
gabah basah belum punya aturan "wajib ke pengering", dan PK dari luar belum
punya tempat menyimpan pemiliknya sama sekali (produksi MENOLAK tiket jasa di
jalur itu). Begitu keduanya dibangun di sana, yang perlu dilakukan di sini NOL:
centang kolomnya di master. Kartu beranda pun mengikuti daftarnya sendiri — ia
hilang bila tak satu pun dibuka, dan berubah bentuk saat yang kedua dibuka.

⚠ **`pihak_untuk(arah, jasa=…)` adalah SATU-SATUNYA tempat yang tahu "pada tiket
jasa lawannya pelanggan".** Faktanya dibutuhkan EMPAT pembaca: daftar pilihan
borang, nama kolom untuk templatnya, penulisan id ke tiket, dan `daftar_pihak`.
Benderanya pernah terlewat di yang keempat — borang menawarkan PEMASOK di bawah
medan bernama `pelanggan_id`, dan id pemasok tersimpan di kolom pelanggan tanpa
satu pun galat. Jangan menyalin cabang "kalau jasa maka pelanggan" ke tempat
kelima.

Borangnya menanyakan **dua** hal tambahan: pemilik barang (daftar pelanggan,
dengan pintu ketik-bebas — cermin Kledo disegarkan mingguan, jadi pelanggan baru
memang bisa belum ada) dan **pesanan**: baru, atau tambahkan ke `JAS-…` yang
sedang berjalan. Yang kedua itu yang membuat 24 ton dengan truk 12 ton tetap
SATU pekerjaan; tanpanya satu pesanan terpecah dua dan produksi menolak
menggiling keduanya bersama.

**Baris `jasa` dibuat PRODUKSI, bukan di sini** (`purchase.pesanan_jasa_dari_tiket`
di sana). Tiket di sini bisa dibatalkan dan direvisi; tiket batal yang sudah
melahirkan pesanan meninggalkan pesanan yatim di sana —
`timbangan_transaksi.jasa_id` karenanya PENUNJUK ke pesanan yang sudah ada, dan
kolomnya pun milik rantai migrasi produksi (0064 di sana; 0039 di sini
menambahkannya idempoten supaya modul ini tetap bisa berdiri sendiri).

⚠⚠ **`timbangan_transaksi.jasa` (migrasi 0041) ADALAH SATU-SATUNYA PENANDA
"ini jasa?"** — bukan `pelanggan_id IS NOT NULL`. Cacat lapangan 2 Oktober
2026: pelanggan BARU yang diketik bebas di pintu ketik-bebas (sah dan
disengaja — cermin Kledo disegarkan mingguan) membuat `pelanggan_id` tetap
NULL sampai produksi membuatnya saat menerima tiketnya. Sampai migrasi ini,
baris tiket "jasa-pelanggan-baru" jadi IDENTIK bentuknya dengan
"pembelian-pemasok-baru", dan produksi (`timbang_link.adalah_jasa`, basis
data yang sama) membuat PEMASOK PALSU dari nama pelanggan.

Diisi SEKALI, di `simpan_timbang_pertama`, dari `data.jasa` — fakta yang
petugas tahu pasti pada detik ia menekan "Barang masuk jasa", lepas dari
apakah pelanggannya sudah terdaftar. `supplier_id`/`pelanggan_id` TETAP ada
dan tetap diisi seperti sebelumnya (mereka menjawab SIAPA, bukan lagi
APAKAH).

⚠ Pelajaran metodologis: `test_pemilik_boleh_diketik_bebas` sudah ADA
sebelum cacat ini ditemukan dan sudah membuktikan `(supplier_id,
pelanggan_id) == (None, None)` sebagai perilaku BENAR untuk pintu ketik-bebas
— tetapi tak pernah memeriksa apakah jejak itu masih bisa dibaca benar oleh
PEMBACA LAIN (produksi, basis data yang sama). Menguji bahwa sebuah pintu
bekerja tidak sama dengan menguji bahwa akibatnya di seberang pintu itu benar.

Uji: `tests/timbangan/test_jasa_masuk.py` (layanan, termasuk bagian 7 — tanda
`jasa` itu sendiri) dan bagian JASA di `tests/timbangan/test_web.py` (layarnya
dirender sungguhan, termasuk jalur pelanggan-baru-ketik-bebas lewat HTTP).

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

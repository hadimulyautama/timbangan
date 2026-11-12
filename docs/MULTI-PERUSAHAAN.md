# Fondasi multi-perusahaan TeraFlow

Status 12 November 2026: inventaris dan pembanding perilaku lama. Tahap ini
tidak mengubah penimbangan, stok, hak akses, atau data produksi. Rencana lintas
aplikasi dan pembagian kelas berada di
[dokumen PadiFlow](https://github.com/hadimulyautama/penggilingan-beras/blob/main/docs/multi-perusahaan/README.md).

## Kontrak yang harus tetap benar

- Perusahaan memakai identitas yang sama dengan PadiFlow pada master bersama.
- Satu perusahaan dapat mempunyai beberapa lokasi pabrik. Setiap lokasi
  mempunyai beberapa gudang/tempat produksi dan setiap tempat dapat mempunyai
  beberapa line. Pos timbang dan profil printer terikat lokasi/perangkat.
- Pelanggan, pemasok, komoditas, tara, pengaturan, gudang dan printer mengikuti
  perusahaan/lokasi yang sah. Nama atau nomor kontak tidak menyatukan perusahaan.
- Pembatasan perusahaan diverifikasi server, termasuk koneksi internal,
  permintaan tertunda dan pengulangan kiriman.
- Aturan dan lintasan pada tiket lama adalah snapshot. Mengganti nama master
  tidak mengubah identitas historis, bobot, hasil kontrol, maupun audit.
- TeraFlow menulis hasil timbang; PadiFlow tetap penulis perpindahan stok.

## Inventaris dan pemanggil

| Area | Sumber | Pekerjaan berikutnya |
|---|---|---|
| Perusahaan dan kontak | `hmu_core/models.py`, `app/models.py`, `hmu_dokumen/perusahaan.py` | Master bersama belum mempunyai cakupan perusahaan; perubahan skema harus sejalan dengan pemilik migrasinya. |
| Pengguna dan sesi | `hmu_identitas/model.py`, `app/timbangan/security.py`, `app/timbangan/models.py` | Tambahkan keanggotaan dan konteks perusahaan terverifikasi sebelum pemilihan perusahaan dibuka. |
| Komoditas dan tara | `app/timbangan/models.py:TimbanganJenis`, `TimbanganTaraStandar`, `app/timbangan/service.py:peta_aturan` | Master berbasis data tetapi masih global; aturan awal tetap menjadi kompatibilitas instalasi lama. |
| Pengaturan alat | `app/timbangan/config.py`, `app/timbangan/setelan.py` | Kapasitas dan setelan perlu mengikuti perusahaan/pos timbang. |
| Gudang dan lintasan | `app/timbangan/lintasan_transfer.py` | Masih khusus g1 menuju g2; snapshot historis tidak dipetakan ulang. |
| Pengiriman PK | `app/timbangan/transfer_pk.py`, `app/timbangan/klien_produksi.py` | Pertahankan satu perjalanan/satu tiket dan pemulihan RPC; konteks perusahaan perlu ikut terikat kontrak. |
| Nomor tiket | `app/timbangan/models.py:TimbanganNomor` | Nomor dibagi menurut awalan/tanggal/perangkat; perusahaan belum menjadi bagian konteksnya. |
| Koneksi PadiFlow | `app/config.py`, `app/timbangan/klien_produksi.py` | Satu URL/token instalasi; identitas perusahaan belum dikirim dan diverifikasi. |
| Kledo | `hmu_core/kledo_kontak.py` melalui PadiFlow | Konfigurasi dan pencocokan kontak perlu dipisahkan per perusahaan. |
| Luring/cache | `app/timbangan/static/luring.js`, `static/sw.js`, `app/timbangan/kiriman.py` | Pemisahan sekarang per akun; perusahaan dan lokasi asal kiriman harus tetap melekat saat berganti konteks. |
| Printer/dokumen | `app/timbangan/static/app.js`, `app/timbangan/config.py`, `app/timbangan/pdf.py`, `app/timbangan/epos.py` | Profil printer dan penerbit mengikuti perusahaan/lokasi; konten cetak lama tetap terjaga. |

## Kelas dan kepemilikan tanggung jawab

Model perusahaan, lokasi pabrik, gudang, kontak dan keanggotaan harus dimiliki paket bersama.
Jangan membuat perusahaan dengan ID terpisah di setiap aplikasi. Kelas
`KonteksKerja` yang direncanakan harus immutable dan dibangun sesudah validasi
server, termasuk `lokasi_pabrik_id`. Konteks ini berbeda dari snapshot transaksi.
Pilihan lintasan perlu mencakup perpindahan antargudang dalam satu lokasi dan
antarlokasi pada perusahaan yang sama. Kiriman lama tidak berpindah lokasi
ketika pengguna mengganti konteks kerjanya.

Snapshot lintasan/dokumen dapat diperkuat menjadi objek berversi ketika kontrak
JSON lama telah dilindungi. `InputTimbang`, model SQLAlchemy dan mesin aturan
yang sudah ada tetap dipakai. Tahap ini tidak memindahkan rumus ke kelas baru
atau menambah kolom perusahaan sebelum kontrak bersama disiapkan.

## Pengujian pembanding

```sh
python -m pytest -m fondasi_multi \
  tests/timbangan/test_fondasi_multi.py \
  tests/timbangan/test_rincian_transfer.py \
  tests/timbangan/test_transfer_pk_bertahap.py \
  --junitxml=bukti/fondasi-teraflow.xml
```

Fixture menggunakan SQLite sementara dan aplikasi HTTP sebenarnya. Pembanding
memeriksa netto 4.000 kg, tara 10,58 kg dan berat barang 3.989,42 kg dari
10.500 kg/6.500 kg, 100 karung × 0,0858 kg serta tara lain 2 kg. Sesudah
master gudang/silo diganti nama, tiket tetap menampilkan snapshot asalnya.
Pembacaan tiga tab detail tidak menulis transaksi, rincian timbang, muatan,
audit atau catatan cetak dan tidak memanggil integrasi.

Kasus lain memakai formulir asli untuk replay, satu perjalanan/satu tiket,
gangguan RPC serta pemulihan. Integrasi dua proses nyata dijalankan dari
PadiFlow menurut instruksi pada dokumen lintas aplikasi. Mock RPC bukan bukti
integrasi jaringan. Semua suite CI lengkap tetap menjadi pengaman rilis.

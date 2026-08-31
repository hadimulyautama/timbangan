# Pos Timbang — PT Hadi Mulya Utama

Webapp pos timbang: mencatat penimbangan truk, mengontrolnya terhadap nota
dan surat jalan, dan mencetak bukti timbang. Dipakai petugas di pos, di ponsel.

Rancangan lengkap ada di [`docs/RANCANGAN.md`](docs/RANCANGAN.md); cara kerja
sehari-hari di [pedoman Admin](docs/pedoman-admin.html) dan
[pedoman Petugas](docs/pedoman-petugas.html).

## Hubungannya dengan sistem penggilingan

Modul ini lahir di dalam repo `hadimulyautama/penggilingan-beras` dan
dipisahkan ke sini pada **31 Agustus 2026**, supaya rilisnya tidak lagi
menunggu — dan tidak lagi memicu — rilis sistem penggilingan dan Kantor AI.

**Databasenya tetap satu.** Ini bukan kelalaian melainkan pilihan: memisahkan
database berarti memindahkan data produksi dan membangun sinkronisasi
supplier, sementara yang dibutuhkan hanyalah kemandirian rilis.

Akibatnya ada empat foreign key yang keluar dari modul ini:

| Kolom | Menunjuk | Milik |
|---|---|---|
| `timbangan_akun.user_id` | `users` | penggilingan |
| `timbangan_transaksi.supplier_id` | `suppliers` | penggilingan |
| `timbangan_transaksi.purchase_batch_id` | `purchase_batches` | penggilingan |
| `timbangan_transaksi.pk_purchase_batch_id` | `pk_purchase_batches` | penggilingan |

Keempat tabel itu dipetakan seperlunya di [`app/models.py`](app/models.py) —
dibaca, tidak pernah dimigrasikan dari sini. Berkas itu adalah **kontrak
tertulis** atas jahitan tersebut: kodenya terpisah, datanya tidak. Perubahan
bentuk keempat tabel itu di repo sebelah bisa merusak modul ini, dan tidak
ada lagi satu rangkaian uji yang menangkapnya.

Riwayat migrasinya juga dipisah: repo ini memakai tabel versi
`alembic_version_timbangan`, dan autogenerate-nya hanya boleh melihat tabel
berawalan `timbangan_`. Rinciannya di [`migrations/env.py`](migrations/env.py).

## Menjalankan secara lokal

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 285 uji, tanpa perlu Postgres
```

Uji memakai SQLite sementara dan tidak pernah menyentuh database produksi.
Untuk menjalankan servernya, isi `DATABASE_URL` lalu:

```bash
.venv/bin/uvicorn app.main:app --reload
```

## Variabel lingkungan

| Wajib | Arti |
|---|---|
| `DATABASE_URL` | Postgres yang sama dengan sistem penggilingan |
| `TIMBANGAN_SECRET_KEY` | Kunci penanda tangan cookie sesi |

| Opsional | Bawaan | Arti |
|---|---|---|
| `APP_TIMEZONE` | `Asia/Jakarta` | Zona waktu tanggal transaksi |
| `TIMBANGAN_ADMIN_USERNAME/_PASSWORD/_NAMA` | — | Membuat akun Admin pertama saat start, bila belum ada akun sama sekali |
| `TIMBANGAN_PERUSAHAAN_NAMA/_ALAMAT/_TELEPON` | — | Identitas pada bukti timbang |

Setelan operasional — kapasitas jembatan, kelipatan tera, jam kunci, jam
tiket menganggur, ukuran foto — **tidak** lewat environment lagi; Super Admin
mengubahnya dari layar Pengaturan dan nilainya tersimpan di
`timbangan_config`. Lihat `app/timbangan/setelan.py`.

## Deploy

Railway, dari `Dockerfile` di akar. Entrypoint menyelaraskan skema lebih dulu
lewat `scripts/siapkan_skema.py`, yang membedakan tiga keadaan: riwayat sudah
ada (upgrade), tabel ada tapi riwayat belum (stamp — skema warisan dari repo
penggilingan), atau database kosong (upgrade dari nol).

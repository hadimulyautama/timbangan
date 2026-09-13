"""Model milik sistem penggilingan yang ikut dibaca modul ini.

**Tabel-tabel ini bukan milik repo ini.** Kelimanya — `users`, `suppliers`,
`pelanggan`, `purchase_batches`, `pk_purchase_batches` — dimiliki dan
dimigrasikan oleh sistem penggilingan. Di sini mereka dipetakan seperlunya
saja, supaya foreign key dari `timbangan_*` punya sasaran yang dikenal
SQLAlchemy, dan supaya `suppliers` serta `pelanggan` bisa dibaca untuk daftar
pilihan.

Inilah jahitan yang tersisa setelah pemisahan repo: **kodenya terpisah,
databasenya tidak.** Siapa pun yang mengubah bentuk keempat tabel itu di repo
penggilingan bisa merusak modul ini, dan tidak ada lagi satu rangkaian uji
yang menangkapnya. Berkas ini adalah kontrak tertulis atas jahitan tersebut —
kalau ia perlu diubah, berarti kontraknya berubah, dan itu harus disepakati
dua sisi.

Karena itu: **jangan membuat migrasi di repo ini yang menyentuhnya.** Kalau
bentuk tabelnya berubah di sana, berkas ini yang menyesuaikan — bukan
sebaliknya. Definisinya disalin apa adanya agar `create_all` pada database uji
menghasilkan tabel yang sepadan.

Kolom yang ditambahkan di sini hanya boleh kolom yang MEMANG DIBACA modul ini,
dan penambahannya berarti kontraknya melebar — bukan sekadar pemetaan yang
dilengkapi. Sampai 11 September 2026 daftarnya: `purchase_batches` dan
`pk_purchase_batches` masing-masing dibaca lewat `timbangan_transaksi_id` dan
`kode_batch`, untuk mengetahui apakah sebuah tiket sudah dipakai produksi.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

__all__ = ["Akun", "Base", "Pelanggan", "PkPurchaseBatch", "PurchaseBatch",
           "Supplier", "User"]


# ── users, suppliers, pelanggan: model LENGKAP dari paket bersama ──
#
# Dulu ketiganya dipetakan "seperlunya" di sini sebagai sasaran foreign key.
# Sejak identitas bersama (Tahap 2, 13 Sep 2026) pos timbang membaca
# `users.role`/`users.status` dan menunjuk `produksi_akun`, jadi modelnya
# harus yang sesungguhnya — dan hanya boleh ada SATU pemetaan per tabel dalam
# satu metadata. Kontraknya tetap: tabel-tabel ini dimiliki chain lain
# (`core`), repo ini tidak pernah memigrasikannya.
from hmu_core import Pelanggan, Supplier, User  # noqa: E402,F401
from hmu_identitas.model import Akun  # noqa: E402,F401  (sasaran timbangan_akun.akun_id)


class PurchaseBatch(Base, TimestampMixin):
    """Batch pembelian gabah (Gudang 1) — dan arah tautannya yang sebenarnya.

    Berkas ini dulu menulis bahwa tabel ini adalah "sasaran
    `timbangan_transaksi.purchase_batch_id`". Itu keliru, dan kekeliruannya
    mahal: kedua kolom penunjuk-balik di `timbangan_transaksi` tidak pernah
    diisi siapa pun. Yang benar-benar dipakai adalah arah SEBALIKNYA —
    produksi menulis `purchase_batches.timbangan_transaksi_id` saat operator
    menaut batch ke tiket.

    Selama tautannya dikira tak pernah ada, timbangan membatalkan,
    mengubah, dan menghapus tiket yang gabahnya sudah masuk stok di sebelah.
    Yang terakhir bahkan tak sampai berubah apa-apa: foreign key inilah yang
    menolaknya, dan yang dilihat Admin adalah halaman galat. Temuan QA X-08
    dan T-12.

    Dua kolom di bawah karenanya DIBACA modul ini — hanya dibaca, lewat
    `app.timbangan.tautan_produksi`. Tidak ada satu pun jalur di repo ini
    yang menulis ke tabel ini, dan tak ada migrasi di sini yang
    menyentuhnya.
    """

    __tablename__ = "purchase_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Ditulis produksi saat batch ditaut ke tiket. UNIQUE di sana — tetapi
    #: keunikannya berlaku per tabel, jadi tiket yang sama masih mungkin juga
    #: muncul di `pk_purchase_batches`. Keduanya wajib diperiksa.
    timbangan_transaksi_id: Mapped[int | None] = mapped_column(index=True)
    #: Kode yang dibaca orang ("GB-20260911-02"). Disebut dalam pesan
    #: penolakan, karena tindak lanjutnya ada di aplikasi sebelah dan
    #: orangnya harus tahu apa yang dicari di sana.
    kode_batch: Mapped[str | None] = mapped_column(String(40))


class PkPurchaseBatch(Base, TimestampMixin):
    """Batch pembelian beras PK (Gudang 2). Lihat catatan di `PurchaseBatch`
    — arah tautannya sama, dan keduanya sama-sama harus diperiksa.
    """

    __tablename__ = "pk_purchase_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    timbangan_transaksi_id: Mapped[int | None] = mapped_column(index=True)
    kode_batch: Mapped[str | None] = mapped_column(String(40))

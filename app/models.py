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

from datetime import datetime

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

__all__ = ["Base", "Pelanggan", "PkPurchaseBatch", "PurchaseBatch",
           "Supplier", "User"]


class User(Base, TimestampMixin):
    """Pengguna sistem penggilingan. Sasaran `timbangan_akun.user_id`.

    **Sengaja tidak lengkap.** Yang dipetakan hanya kolom yang membuatnya
    menjadi sasaran foreign key yang sah; modul ini tidak pernah membaca
    apalagi menulis baris `users`. Kolom lain di tabel aslinya —
    `whatsapp_number`, `telegram_user_id`, `default_warehouse_id`, dan
    seterusnya — sengaja dibiarkan di luar, karena membawanya berarti ikut
    membawa `warehouses` dan seterusnya sampai separuh skema penggilingan
    pindah ke sini.

    Autogenerate Alembic tidak akan pernah menyentuh tabel ini: `env.py`
    membatasi pandangannya pada tabel berawalan `timbangan_`.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="aktif")


class Pelanggan(Base, TimestampMixin):
    """Pembeli beras dan hasil samping. Disinkron dari kontak Kledo tipe 3.

    Dipakai pada arah KELUAR, sebagaimana `Supplier` dipakai pada arah MASUK.
    Sengaja dua tabel, bukan satu tabel berpenanda: di Kledo satu kontak boleh
    sekaligus vendor dan pelanggan — 24 kontak memang begitu — tetapi yang
    menentukan di sini adalah perannya pada transaksi ini.
    """

    __tablename__ = "pelanggan"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama_pelanggan: Mapped[str] = mapped_column(String(150), nullable=False)
    no_telfon: Mapped[str | None] = mapped_column(String(30))
    alamat: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="aktif")
    deleted_at: Mapped[datetime | None] = mapped_column()
    kledo_contact_id: Mapped[int | None] = mapped_column(BigInteger, index=True)


class Supplier(Base, TimestampMixin):
    """Supplier gabah dan beras PK (bisa sama). Soft delete via deleted_at."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    nama_supplier: Mapped[str] = mapped_column(String(150), nullable=False)
    no_telfon: Mapped[str | None] = mapped_column(String(30))
    alamat: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="aktif")
    deleted_at: Mapped[datetime | None] = mapped_column()
    kledo_contact_id: Mapped[int | None] = mapped_column(BigInteger, index=True)


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

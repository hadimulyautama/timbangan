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

Karena itu: **jangan menambah kolom di sini, dan jangan membuat migrasi yang
menyentuhnya.** Kalau bentuk tabelnya berubah di sana, berkas ini yang
menyesuaikan — bukan sebaliknya. Definisinya disalin apa adanya agar
`create_all` pada database uji menghasilkan tabel yang sepadan.
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
    """Batch pembelian gabah (Gudang 1). Sasaran
    `timbangan_transaksi.purchase_batch_id`.

    Seperti `User`: sengaja hanya kunci primernya. Tautan ini SATU ARAH —
    catatan timbang boleh menunjuk sebuah batch pembelian, tetapi modul ini
    tidak pernah membaca isinya. Yang menghubungkan keduanya adalah sistem
    penggilingan, di repo sebelah.
    """

    __tablename__ = "purchase_batches"

    id: Mapped[int] = mapped_column(primary_key=True)


class PkPurchaseBatch(Base, TimestampMixin):
    """Batch pembelian beras PK (Gudang 2). Sasaran
    `timbangan_transaksi.pk_purchase_batch_id`. Lihat catatan di
    `PurchaseBatch`.
    """

    __tablename__ = "pk_purchase_batches"

    id: Mapped[int] = mapped_column(primary_key=True)

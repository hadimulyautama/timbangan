"""Nomor tiket diterbitkan server secara atomik, dan kiriman punya kuncinya sendiri.

Sampai 11 September 2026 nomor tiket dibentuk PERANGKAT saat formulir DIBUKA,
dari `jumlah baris hari ini + 1`, dengan perangkat "P0" bagi akun yang tak
punya kode perangkat — dan admin bawaan maupun akun lama memang tak punya.

Dua petugas yang membuka layar pada detik yang sama menerima nomor yang sama.
Penyimpanannya lalu memakai nomor itu sebagai IDENTITAS dan memperlakukan
nomor terbuka yang sudah ada sebagai "kirim ulang", lalu menulis ulang seluruh
tiket. Keduanya melihat "tersimpan"; hanya truk yang kedua tersisa. Temuan QA
T-01, dan ia juga jadi jalan menimpa tiket orang lain dengan sengaja.

Dua kolom baru menutupnya, dan keduanya memang harus terpisah:

`timbangan_nomor` — penghitung per awalan, tanggal, dan perangkat. Diambil
dengan satu `INSERT … ON CONFLICT DO UPDATE … RETURNING`, jadi dua penyimpanan
berbarengan tak mungkin mendapat angka yang sama. Ia hanya bertambah: nomor
yang sudah terbit tak pernah terbit lagi meski tiketnya dibatalkan, karena
nomor yang muncul dua kali di struk lebih membingungkan daripada nomor yang
melompat.

`timbangan_transaksi.kunci_kiriman` — identitas kiriman yang sebenarnya,
dibuat perangkat saat formulir dibuka. Nomor tiket tak bisa memikul tugas ini
justru karena ia yang bertabrakan. Dengan kunci, kirim ulang dari antrean
luring tetap dikenali sementara dua penimbangan berbeda tak mungkin
bertabrakan.

Kolom yang DIBACA produksi (`kode`, `purchase_batch_id`, dan seluruh kolom
berat) tidak disentuh sama sekali. Yang ditambahkan hanya kolom baru.

Baris lama TIDAK diisi kunci karangan: kunci buatan bisa bertabrakan dengan
kunci sungguhan milik perangkat, dan tiket lama memang tak pernah punya.
Penghitungnya juga tidak disemai dari data lama — nomor berikutnya yang
terbit akan mulai dari 001 untuk hari & perangkat yang belum pernah memakai
penghitung ini, dan bentrokannya tertangkap oleh indeks unik `kode` lalu
dialokasikan ulang.

Revision ID: 0030_timbangan_nomor_atomik
Revises: 0029_timbangan_retur
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_timbangan_nomor_atomik"
down_revision: Union[str, None] = "0029_timbangan_retur"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timbangan_nomor",
        sa.Column("awalan", sa.String(length=8), nullable=False),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("perangkat", sa.String(length=8), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("awalan", "tanggal", "perangkat"),
    )
    op.add_column(
        "timbangan_transaksi",
        sa.Column("kunci_kiriman", sa.String(length=36), nullable=True),
    )
    # UNIK, dan di situlah seluruh gunanya: dua kiriman dengan kunci yang sama
    # tak mungkin menjadi dua tiket, bahkan bila keduanya tiba bersamaan dari
    # dua proses aplikasi yang berbeda.
    op.create_index(
        "ix_timbangan_transaksi_kunci_kiriman",
        "timbangan_transaksi", ["kunci_kiriman"], unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_timbangan_transaksi_kunci_kiriman", table_name="timbangan_transaksi"
    )
    op.drop_column("timbangan_transaksi", "kunci_kiriman")
    op.drop_table("timbangan_nomor")

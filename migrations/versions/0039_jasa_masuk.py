"""Barang masuk JASA: komoditas mana yang boleh dititipkan, dan penunjuk pesanan.

Jasa (toll milling) adalah barang yang DITITIPKAN pelanggan untuk digiling,
bukan dibeli. Dari sudut pos timbang yang berubah hanya satu hal: lawan
transaksinya PELANGGAN, bukan pemasok — padahal arahnya tetap MASUK. Cara
menimbang, tara, dan ambangnya sama persis.

Karena itu TIDAK ada jenis timbang baru. `GABAH_KERING_JASA` akan menggandakan
tiga jenis jadi enam, menggandakan aturan taranya, dan memberi petugas enam
tombol berpasangan mirip untuk salah pilih.

── `timbangan_jenis.boleh_jasa` — ATURANNYA DI DATA ──

Salah satu dari dua aturan yang membentuk modul ini: aturan hidup di DATA,
bukan di kode. Komoditas mana yang boleh dijasakan karenanya sebuah KOLOM,
bukan `if` di kode.

Hari ini hanya `GABAH_KERING` yang dibuka, dan bukan karena jasa terbatas pada
gabah kering — melainkan karena hanya jalur itulah yang sudah utuh di sisi
produksi:

  · gabah BASAH belum punya aturan "wajib ke pengering" (`tujuan_wajib`), dan
    gabah basah yang menumpuk akan rusak — lalu rusaknya jadi perselisihan
    dengan orang yang menitipkannya;
  · beras PK dari luar belum punya tempat menyimpan pemiliknya sama sekali
    (`pk_purchase_batches` tanpa `jasa_id`), dan produksi MENOLAK tiket jasa di
    jalur itu terang-terangan — sebab jalur lamanya akan membuat pemasok palsu
    bernama pelanggan.

Begitu keduanya dibangun di sana, yang perlu dilakukan di sini NOL: centang
kolomnya di master komoditas. Kalau ia `if` di kode, pembukaannya menunggu
rilis — dan yang menunggu rilis cenderung dibuka dengan menambah `if` kedua di
tempat lain.

BARIS LAMA mendapat `false`, termasuk `GABAH_KERING` yang sudah ada di basis
data yang sedang berjalan — lalu diisi `true` secara TERPISAH di bawah. Dua
langkah, bukan satu `server_default`: nilai bawaan yang berbeda per baris tak
bisa dinyatakan sebagai default kolom, dan menyetel seluruhnya `true` akan
membuka komoditas yang produksinya belum siap menerimanya.

── `timbangan_transaksi.jasa_id` — IDEMPOTEN, dan ini perlu dijelaskan ──

Kolomnya sudah DIBUAT oleh migrasi `0064_jasa` repo PENGGILINGAN, bersama tabel
`jasa` yang ditunjuknya; di produksi ia sudah ada. Yang dijaga di sini keadaan
yang lain: basis data yang HANYA menjalankan rantai modul ini — pemasangan
tanpa sistem penggilingan, dan pemulihan dari nol.

FK-nya hanya dipasang bila tabel `jasa` memang ada. Tanpa tabelnya, FK ke
`jasa(id)` akan menggagalkan seluruh migrasi — dan modul ini harus tetap bisa
berdiri sendiri, sebab itulah sebabnya ia dipisah jadi repo tersendiri.

Pola idempoten yang sama sudah dipakai arah sebaliknya: `0064_jasa` di
penggilingan menambahkan `pelanggan_id` dengan penjaga `inspector`, sebab
kolom ITU milik rantai modul ini.

Revision ID: 0039_jasa_masuk
Revises: 0038_kunci_baris_64
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039_jasa_masuk"
down_revision: Union[str, None] = "0038_kunci_baris_64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Komoditas yang dibuka untuk jasa pada irisan pertama. Satu, dan sebabnya
#: ada di kepala berkas. Daftar ini BIBIT — sesudah ini ia milik master, dan
#: migrasi berikutnya tak boleh menyetelnya ulang: yang pemilik centang atau
#: cabut di layar master adalah keputusannya, bukan usul kode.
JASA_AWAL = ("GABAH_KERING",)


def upgrade() -> None:
    sambung = op.get_bind()
    inspector = sa.inspect(sambung)

    kolom_jenis = {c["name"] for c in inspector.get_columns("timbangan_jenis")}
    if "boleh_jasa" not in kolom_jenis:
        op.add_column("timbangan_jenis", sa.Column(
            "boleh_jasa", sa.Boolean(), nullable=False,
            server_default=sa.false()))
        # Dibuka HANYA untuk yang jalurnya sudah utuh di produksi. Dijalankan
        # sebagai UPDATE bersyarat, bukan diisi saat kolomnya dibuat: basis
        # data yang sudah berjalan memuat baris `GABAH_KERING` sejak lama.
        op.execute(
            "UPDATE timbangan_jenis SET boleh_jasa = true WHERE kode IN ("
            + ", ".join(f"'{k}'" for k in JASA_AWAL) + ")"
        )

    kolom_trx = {c["name"] for c in inspector.get_columns("timbangan_transaksi")}
    if "jasa_id" not in kolom_trx:
        # Lihat kepala berkas: di produksi kolom ini sudah dibuat migrasi 0064
        # repo penggilingan, jadi cabang ini hanya berjalan di basis data yang
        # tak menjalankan rantai itu.
        op.add_column("timbangan_transaksi", sa.Column("jasa_id", sa.Integer()))
        op.create_index(
            "ix_timbangan_transaksi_jasa", "timbangan_transaksi", ["jasa_id"],
            postgresql_where=sa.text("jasa_id IS NOT NULL"),
            sqlite_where=sa.text("jasa_id IS NOT NULL"))
        if (sambung.dialect.name != "sqlite"
                and inspector.has_table("jasa")):
            # SQLite tak mendukung ALTER constraint sama sekali, dan tanpa
            # tabel `jasa` tak ada yang bisa ditunjuk. Keduanya keadaan yang
            # sah di sini — integritasnya ditegakkan di basis data produksi,
            # tempat kedua rantai bertemu.
            op.create_foreign_key(
                "fk_timbangan_transaksi_jasa", "timbangan_transaksi",
                "jasa", ["jasa_id"], ["id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # `jasa_id` TIDAK dijatuhkan. Di produksi ia milik rantai penggilingan
    # (migrasi 0064 di sana); menjatuhkannya dari sini akan merobohkan sisi
    # yang tak pernah meminta migrasi INI turun — dan membuang penunjuk pesanan
    # pada tiket yang barangnya sungguh ada di gudang.
    #
    # Yang dijatuhkan hanya kolom yang memang lahir di sini.
    kolom_jenis = {c["name"] for c in inspector.get_columns("timbangan_jenis")}
    if "boleh_jasa" in kolom_jenis:
        op.drop_column("timbangan_jenis", "boleh_jasa")

"""Semai penghitung nomor dari tiket yang sudah ada.

Migrasi 0030 membuat `timbangan_nomor` KOSONG, lalu `alokasi_nomor` mulai
menghitung dari 1 untuk tiap (awalan, tanggal, perangkat). Untuk kombinasi
yang hari itu SUDAH dipakai — yaitu setiap petugas yang sudah menimbang
sebelum pembaruan naik — nomor pertama yang diterbitkan adalah nomor yang
sudah menjadi milik tiket lain, dan penyimpanan gagal dengan:

    duplicate key value violates unique constraint "timbangan_transaksi_kode_key"

Di layar petugas itu muncul sebagai "Internal server error".

Kegagalannya TIDAK sembuh sendiri. Kenaikan penghitung ikut dibatalkan
bersama transaksi yang gagal, jadi percobaan berikutnya mengambil angka yang
sama persis, gagal lagi, selamanya. Terjadi di produksi 11 September 2026:
satu petugas (P5, sudah menimbang sejak pagi) tak bisa menyimpan apa pun
selama hampir empat jam, sementara petugas lain (P4, hari itu belum memakai
awalan yang sama) tidak merasakan apa-apa.

Yang dikerjakan di sini: menaikkan penghitung ke nomor TERTINGGI yang sudah
benar-benar terpakai, per (awalan, tanggal, perangkat). Memakai `greatest`
supaya baris yang sudah telanjur lebih tinggi tidak diturunkan — menurunkannya
akan menerbitkan ulang nomor yang sudah tercetak di struk.

Idempoten: menjalankannya dua kali tidak mengubah apa pun.

Revision ID: 0031_semai_penghitung_nomor
Revises: 0030_timbangan_nomor_atomik
"""
import re
from datetime import date
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_semai_penghitung_nomor"
down_revision: Union[str, None] = "0030_timbangan_nomor_atomik"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: AWALAN-YYYYMMDD-PERANGKAT-URUT. Kode yang tidak berbentuk begini dilewati
#: tanpa suara: ia tidak pernah bisa bertabrakan dengan nomor terbitan baru,
#: yang selalu dibentuk dengan pola ini.
POLA = re.compile(r"^([A-Z]+)-(\d{8})-([A-Za-z0-9]+)-(\d+)$")


def upgrade() -> None:
    # Diuraikan di Python, bukan SQL: `split_part` dan `to_date` milik
    # Postgres, sementara pengujian memakai SQLite. Barisnya sedikit —
    # satu per perangkat per arah per hari — jadi tidak ada ruginya.
    sambungan = op.get_bind()
    baris = sambungan.execute(
        sa.text("select kode from timbangan_transaksi where kode is not null")
    ).fetchall()

    tertinggi: dict[tuple[str, date, str], int] = {}
    for (kode,) in baris:
        cocok = POLA.match(kode or "")
        if not cocok:
            continue
        awalan, tanggal, perangkat, urut = cocok.groups()
        # ── Tanggalnya OBJEK date, bukan teks ──
        #
        # `timbangan_nomor.tanggal` bertipe DATE, dan asyncpg menolak teks
        # untuk parameter bertipe date: "'str' object has no attribute
        # 'toordinal'". psycopg2 dulu memaksanya diam-diam, jadi kekeliruan
        # ini tak terlihat di mana pun yang memakai driver itu — dan uji repo
        # ini berjalan di SQLite, yang menerima teks apa adanya.
        #
        # Akibatnya migrasi ini GAGAL di server, dan karena entrypoint
        # berhenti bila migrasi gagal, Pos Timbang tak bisa menyala dengan
        # versi baru sejak 11 September 2026 pukul 15:47. Yang berjalan di
        # pos timbang sampai sekarang adalah versi sebelum itu.
        try:
            hari = date(int(tanggal[:4]), int(tanggal[4:6]), int(tanggal[6:]))
        except ValueError:
            continue      # tanggal mustahil di dalam kode — dilewati, seperti
                          # kode yang polanya tak cocok sama sekali
        kunci = (awalan, hari, perangkat)
        tertinggi[kunci] = max(tertinggi.get(kunci, 0), int(urut))

    for (awalan, tanggal, perangkat), n in tertinggi.items():
        # Dua langkah, bukan satu ON CONFLICT: sintaksisnya berbeda antara
        # Postgres dan SQLite, dan yang penting di sini kebenarannya, bukan
        # kerampingannya. Migrasi ini hanya berjalan sekali.
        ada = sambungan.execute(
            sa.text("select n from timbangan_nomor "
                    "where awalan = :a and tanggal = :t and perangkat = :p"),
            {"a": awalan, "t": tanggal, "p": perangkat},
        ).scalar()
        if ada is None:
            sambungan.execute(
                sa.text("insert into timbangan_nomor (awalan, tanggal, perangkat, n) "
                        "values (:a, :t, :p, :n)"),
                {"a": awalan, "t": tanggal, "p": perangkat, "n": n},
            )
        elif ada < n:
            sambungan.execute(
                sa.text("update timbangan_nomor set n = :n "
                        "where awalan = :a and tanggal = :t and perangkat = :p"),
                {"a": awalan, "t": tanggal, "p": perangkat, "n": n},
            )


def downgrade() -> None:
    # Sengaja tidak berbuat apa-apa. Menurunkan penghitung berarti menerbitkan
    # ulang nomor yang sudah tercetak di struk dan sudah dirujuk nota —
    # kerusakan yang jauh lebih sulit ditemukan daripada nomor yang melompat.
    pass

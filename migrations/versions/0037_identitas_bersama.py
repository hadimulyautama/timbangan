"""Akun pos timbang bisa ditautkan ke akun bersama (`produksi_akun`).

Tahap 2 rancang ulang, 13 September 2026 — satu orang, satu akun, satu sesi,
satu saklar nonaktif untuk produksi, timbangan, Gudang 2, Meja, dan Kantor
(temuan QA X-11, T-19).

Hanya MENAMBAH: kolom `akun_id` (kosong = akun lama, masih masuk dengan
sandinya sendiri) dan `password_hash` boleh kosong (profil tertaut tak
menyimpan sandi). Tak ada baris yang diubah; penautan per orang dikerjakan
`scripts/identitas_tautkan.py` sesudah pemilik meninjau rencananya, dan bisa
dilepas lagi (`--lepas`) tanpa kehilangan apa pun — sandi lama tetap ada.

Kolom yang DIBACA PRODUKSI tidak disentuh. Foreign key-nya menunjuk tabel
milik chain produksi, seperti `user_id → users` yang sudah ada.

Revision ID: 0037_identitas_bersama
Revises: 0036_indeks_duplikat
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_identitas_bersama"
down_revision: Union[str, None] = "0036_indeks_duplikat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch: di SQLite (uji skema) ALTER nullable butuh membangun ulang tabel;
    # di Postgres ini ALTER TABLE biasa.
    with op.batch_alter_table("timbangan_akun") as b:
        b.add_column(sa.Column("akun_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_timbangan_akun_akun_id", "produksi_akun",
                             ["akun_id"], ["id"])
        b.create_unique_constraint("uq_timbangan_akun_akun_id", ["akun_id"])
        b.alter_column("password_hash", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("timbangan_akun") as b:
        b.drop_constraint("uq_timbangan_akun_akun_id", type_="unique")
        b.drop_constraint("fk_timbangan_akun_akun_id", type_="foreignkey")
        b.drop_column("akun_id")
    # Baris tertaut tak punya sandi: isi hash tiruan supaya NOT NULL bisa
    # kembali tanpa membuka pintu (hash ini tak cocok dengan sandi apa pun).
    op.execute("UPDATE timbangan_akun SET password_hash = 'scrypt$dicabut' "
               "WHERE password_hash IS NULL")
    with op.batch_alter_table("timbangan_akun") as b:
        b.alter_column("password_hash", existing_type=sa.String(255), nullable=False)

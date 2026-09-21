"""R-T-01 — `kunci_baris` dilebarkan ke 64: kunci borang 36 + '#' + indeks.

Insiden 15 September 2026. Borang partai membawa `kunci=str(uuid4())` (36
karakter); layanan menyusun `kunci_baris = f"{kunci}#{i}"` (38); kolomnya
dibuat migrasi 0032 sebagai String(36). Postgres menolak tiap simpan, galatnya
lolos dari penangkap rute, dan petugas melihat halaman hitam — timbangan
partai TIDAK pernah tersimpan.

Yang dilebarkan KOLOMNYA, bukan kuncinya yang dipotong: kunci yang dipotong
jadi 36 berhenti unik antar baris satu kiriman, dan T-10 (kiriman ulang
menambah karung yang sama dua kali) hidup lagi. 64 cukup untuk uuid + '#' +
indeks berapa pun yang masuk akal dalam satu kiriman.

Aman di kedua keadaan: kolom masih 36, ATAU sudah 64 karena pemilik telah
menjalankan `ALTER TABLE ... TYPE varchar(64)` sebagai penambal darurat.
Melebarkan varchar di Postgres hanya mengubah katalog — tak ada penulisan
ulang tabel, indeks uniknya tak terpengaruh — dan ALTER ke lebar yang sama
adalah pekerjaan kosong yang sah.

Revision ID: 0038_kunci_baris_64
Revises: 0037_identitas_bersama
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038_kunci_baris_64"
down_revision: Union[str, None] = "0037_identitas_bersama"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "timbangan_penimbangan", "kunci_baris",
        existing_type=sa.String(length=36), type_=sa.String(length=64),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Menyempitkan kembali akan memotong kunci 38 karakter yang sudah tersimpan
    # (Postgres menolaknya). Yang tersimpan tak boleh dikorbankan demi mundur
    # satu revisi: kolomnya dibiarkan 64.
    pass

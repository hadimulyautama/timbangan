"""Baris partai punya penanda kiriman, supaya karung tak tercatat dua kali.

Temuan QA T-10, 11 September 2026.

Penambahan barang pada tiket partai tak punya penanda apa pun. Jadi kiriman
ULANG — ketukan dobel di layar, atau antrean luring yang mengirim lagi saat
sinyal kembali — tak bisa dibedakan dari karung BERIKUTNYA yang kebetulan sama
beratnya. "+70 kg" yang terkirim dua kali jadi 250 kg, bukan 180.

Tak ada yang bisa menebak mana yang benar sesudahnya: dua karung 70 kg memang
mungkin, dan begitu juga satu karung yang tercatat dua kali.

`kunci_baris` unik, dan boleh kosong: baris yang dibuat sebelum kolom ini ada
memang tak punya penanda, dan mengisinya dengan tebakan justru menghapus
kemungkinan menelusurinya kemudian.

Kolom yang DIBACA PRODUKSI tidak disentuh. Produksi membaca
`timbangan_transaksi` (kode, bobot, status) — bukan `timbangan_penimbangan`,
yang bentuknya memang khusus layar pencatat partai.

Revision ID: 0032_partai_kunci_baris
Revises: 0031_semai_penghitung_nomor
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_partai_kunci_baris"
down_revision: Union[str, None] = "0031_semai_penghitung_nomor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("timbangan_penimbangan",
                  sa.Column("kunci_baris", sa.String(length=36), nullable=True))
    op.create_index("ix_timbangan_penimbangan_kunci_baris",
                    "timbangan_penimbangan", ["kunci_baris"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_timbangan_penimbangan_kunci_baris",
                  table_name="timbangan_penimbangan")
    op.drop_column("timbangan_penimbangan", "kunci_baris")

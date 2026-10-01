"""Jasa dibuka untuk KETIGA komoditas: gabah basah, gabah kering, beras PK.

Keputusan pemilik, 1 Oktober 2026 — dan sebetulnya keputusan nomor 1 di
spesifikasinya sejak awal: *"Jasa dari gabah basah, gabah kering, dan beras
PK."* Migrasi 0039 membuka gabah kering saja, dan itu BUKAN pembatasan yang
pemilik minta: ia pembatasan sementara karena hanya jalur itu yang sudah utuh
di sisi produksi.

Dua jalur yang menghalangi sudah dibangun di repo penggilingan:

  · **gabah basah** — barang titipan yang basah kini WAJIB ke pengering
    (`tumpukan.masuk_tumpukan` menolak, `tujuan_sah` membuang pilihannya dari
    borang). Gabah basah PABRIK tetap boleh menumpuk seperti semula: yang
    dibatasi hanya barang orang lain, sebab basah yang menunggu akan rusak dan
    rusaknya jadi perselisihan dengan yang menitipkannya.
  · **beras PK** — migrasi 0065 di sana memberi `pk_purchase_batches` kolom
    pemiliknya berikut CHECK "tepat satu dari dua", dan penyosohan kini memikul
    pemilik sampai beras & hasil samping (`polishing_process.jasa_id`,
    `jasa.pemilik_hasil()`). Sebelum itu jalur PK luar MENOLAK tiket jasa
    terang-terangan — justru supaya tak ada pemasok palsu bernama pelanggan.

⚠ HANYA MEMBUKA, TIDAK PERNAH MENUTUP. Baris yang sudah `true` dibiarkan, dan
tak satu pun komoditas disetel `false`. Sesudah 0039, kolom ini milik MASTER:
kalau pemilik kelak mencabut salah satunya, keputusan itu tak boleh dibatalkan
oleh migrasi yang berjalan ulang di basis data lain.

`UPDATE` bersyarat, bukan mengisi ulang seluruh tabel — dan tanpa `WHERE
boleh_jasa = false` pun ia idempoten, sebab menyetel `true` ke `true` adalah
pekerjaan kosong yang sah.

Revision ID: 0040_jasa_tiga_komoditas
Revises: 0039_jasa_masuk
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_jasa_tiga_komoditas"
down_revision: Union[str, None] = "0039_jasa_masuk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Yang dibuka migrasi ini. Gabah kering sudah dibuka 0039 dan tidak disebut
#: lagi — menyebutnya ulang akan membuka kembali apa yang mungkin sengaja
#: dicabut pemilik di antara dua migrasi.
DIBUKA = ("GABAH_BASAH", "BERAS_PK")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    kolom = {c["name"] for c in inspector.get_columns("timbangan_jenis")}
    if "boleh_jasa" not in kolom:
        # Basis data yang belum menjalankan 0039 sama sekali — biarkan 0039
        # yang membuat kolomnya berikut bibitnya. Tak ada yang bisa dibuka di
        # sini, dan `UPDATE` atas kolom yang tak ada akan menggagalkan deploy.
        return
    op.execute(
        "UPDATE timbangan_jenis SET boleh_jasa = true WHERE kode IN ("
        + ", ".join(f"'{k}'" for k in DIBUKA) + ")"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    kolom = {c["name"] for c in inspector.get_columns("timbangan_jenis")}
    if "boleh_jasa" not in kolom:
        return
    # Ditutup kembali HANYA yang migrasi ini buka. Gabah kering tak disentuh:
    # ia dibuka 0039, dan turun dari sini tak berarti turun dari sana.
    op.execute(
        "UPDATE timbangan_jenis SET boleh_jasa = false WHERE kode IN ("
        + ", ".join(f"'{k}'" for k in DIBUKA) + ")"
    )

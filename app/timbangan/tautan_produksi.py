"""Apakah sebuah tiket timbang sudah dipakai sistem penggilingan?

**Hanya membaca.** Dua tabel yang dibaca di sini — `purchase_batches` dan
`pk_purchase_batches` — dimiliki repo penggilingan; modul ini tak pernah
menulis, mengunci, atau memigrasikannya. Kontrak kolomnya tertulis di
`app/models.py`.

Kenapa ini ada. Produksi menaut batch pembeliannya ke tiket lewat
`timbangan_transaksi_id`. Selama timbangan tak pernah melihat tautan itu,
setiap tindakan besar di sini berjalan seolah tiketnya masih miliknya
sendiri — tiket dibatalkan padahal gabahnya sudah masuk stok, komoditasnya
diganti padahal batch gabahnya sudah ada, dan penghapusan permanennya
ditolak oleh foreign key sehingga yang terlihat orang adalah halaman galat.
Temuan QA X-08 dan T-12, 11 September 2026.

Pesan penolakannya menyebut KODE BATCH-nya. Penolakan yang hanya berkata
"tidak boleh" memindahkan pekerjaan mencari ke orang yang ditolak, dan
pekerjaan itu ada di aplikasi yang berbeda.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Satu kueri untuk dua tabel. Keunikan `timbangan_transaksi_id` berlaku PER
#: TABEL di sisi produksi, jadi satu tiket masih mungkin muncul di keduanya —
#: memeriksa satu saja berarti melewatkan separuh kemungkinan.
_SQL = text("""
    SELECT kode_batch FROM purchase_batches
     WHERE timbangan_transaksi_id = :tid
    UNION ALL
    SELECT kode_batch FROM pk_purchase_batches
     WHERE timbangan_transaksi_id = :tid
""")


async def batch_tertaut(db: AsyncSession, trx_id: int | None) -> list[str]:
    """Kode batch produksi yang menunjuk tiket ini. Kosong = belum dipakai."""
    if not trx_id:
        return []
    baris = (await db.execute(_SQL, {"tid": trx_id})).all()
    return [b[0] or "(tanpa kode)" for b in baris]


async def pastikan_bebas_tautan(db: AsyncSession, trx, *, tindakan: str) -> None:
    """Tolak `tindakan` bila tiket ini sudah dicatat produksi.

    `tindakan` ditulis apa adanya di pesannya ("Membatalkan tiket ini",
    "Menghapus tiket ini") supaya kalimatnya berbunyi seperti jawaban atas apa
    yang baru saja ditekan orangnya, bukan seperti kode galat.
    """
    from app.timbangan.service import LayananError

    kode = await batch_tertaut(db, getattr(trx, "id", None))
    if not kode:
        return
    raise LayananError(
        f"{tindakan} tidak bisa: tiket ini sudah dicatat produksi sebagai "
        f"{', '.join(kode)} — minta produksi melepas tautannya dulu."
    )

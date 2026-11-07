"""Apakah sebuah tiket timbang sudah dipakai sistem penggilingan?

**Hanya membaca.** Tabel batch, retur, dan pengiriman yang dibaca di sini
dimiliki repo penggilingan; modul ini tak pernah
menulis, mengunci, atau memigrasikannya. Kontrak batch tertulis di
`app/models.py`; kontrak baca pengiriman ada di `pengiriman_tertaut`.

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

from sqlalchemy import inspect, text
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


async def pengiriman_tertaut(db: AsyncSession, trx_id: int | None) -> list[str]:
    """Perintah yang belum batal juga memegang tiket armada yang dipilih.

    Kontrak baca Produksi: outgoing_records.kode (VARCHAR 20), status
    (VARCHAR 20: perintah/dimuat/selesai/batal), timbangan_transaksi_id (INT).
    Tabel ini tidak dibuat atau dimigrasikan Timbangan. Instalasi mandiri
    boleh belum memilikinya; keberadaannya diperiksa tanpa menelan galat SQL
    yang bisa membatalkan seluruh transaksi PostgreSQL.
    """
    if not trx_id or not await db.run_sync(
        lambda sesi: inspect(sesi.connection()).has_table("outgoing_records")
    ):
        return []
    if await db.run_sync(lambda sesi: inspect(sesi.connection()).has_table("kiriman_keluar")):
        return list((await db.execute(text("""
            SELECT o.kode FROM outgoing_records o
            LEFT JOIN kiriman_keluar k ON k.id=o.kiriman_id
            WHERE COALESCE(k.timbangan_transaksi_id,o.timbangan_transaksi_id)=:tid
              AND o.status <> 'batal'
        """), {"tid": trx_id})).scalars().all())
    return list((await db.execute(text("""
        SELECT kode FROM outgoing_records
         WHERE timbangan_transaksi_id = :tid AND status <> 'batal'
    """), {"tid": trx_id})).scalars().all())


async def pastikan_retur_supplier(db: AsyncSession, trx, *, tindakan: str,
                                 termasuk_riwayat: bool = False) -> None:
    """Lindungi pointer eksplisit tanpa menyamakan pengajuan dengan stok.

    Tabel milik PadiFlow boleh belum dipasang. Galat membaca tabel yang ada
    tidak ditelan sebagai tidak tertaut. PadiFlow mengunci baris tiket saat
    menautkan; kunci yang sama menutup celah penghapusan/pergantian identitas
    bersamaan dengan penautan. Koreksi bobot dan pembatalan tidak memanggil
    penjaga khusus pengajuan ini karena tidak memutus pointer/identitasnya.
    Hapus juga menjaga tiket penerimaan asal, termasuk pengajuan dibatalkan;
    sumber beras/hasil samping tidak selalu terjaring pembaca batch generik.
    """
    if not getattr(trx, 'id', None) or not await db.run_sync(
        lambda sesi: inspect(sesi.connection()).has_table('retur_supplier')
    ):
        return
    await db.refresh(trx, with_for_update=True)
    tertaut = (await db.execute(text('''
        SELECT 1 FROM retur_supplier
        WHERE (timbangan_transaksi_id = :tid AND (:riwayat OR status <> 'dibatalkan'))
           OR (:riwayat AND penerimaan_tiket_id = :tid)
    '''), {'tid': trx.id, 'riwayat': termasuk_riwayat})).scalars().all()
    if tertaut:
        from app.timbangan.service import LayananError
        raise LayananError(
            f'{tindakan} tidak bisa: tiket mempunyai hubungan pengajuan Retur ke Supplier '
            'PadiFlow. Periksa pengajuan melalui PadiFlow; '
            'hubungan tidak boleh diputus melalui koreksi atau penghapusan tiket.'
        )


async def pastikan_bebas_tautan(db: AsyncSession, trx, *, tindakan: str) -> None:
    """Tolak `tindakan` bila tiket ini sudah dicatat produksi.

    `tindakan` ditulis apa adanya di pesannya ("Membatalkan tiket ini",
    "Menghapus tiket ini") supaya kalimatnya berbunyi seperti jawaban atas apa
    yang baru saja ditekan orangnya, bukan seperti kode galat.
    """
    from app.timbangan.service import LayananError

    # Penerimaan PadiFlow mengunci tiket yang sama. Pertahankan kunci sampai
    # tindakan selesai agar penerimaan tidak menyelinap setelah pemeriksaan.
    await db.refresh(trx, with_for_update=True)
    kode = await batch_tertaut(db, getattr(trx, "id", None))
    kode.extend(await pengiriman_tertaut(db, getattr(trx, "id", None)))
    kode.extend(await produk_tertaut(db, trx))
    if getattr(trx, "arah", None) == "RETUR_MASUK":
        # Retur yang sudah diterima menjadi sumber stok. Mengubah bobot atau
        # kemasannya sesudah itu akan membuat kedua aplikasi berselisih.
        retur = (await db.execute(text("""
            SELECT kode FROM customer_returns WHERE timbangan_transaksi_id = :tid
        """), {"tid": trx.id})).scalars().all()
        kode.extend(retur)
    if not kode:
        return
    raise LayananError(
        f"{tindakan} tidak bisa: tiket ini sudah dicatat produksi sebagai "
        f"{', '.join(kode)} — minta produksi melepas tautannya dulu."
    )


async def produk_tertaut(db: AsyncSession, trx) -> list[str]:
    """Bukti penerimaan produk tetap berlaku sesudah stok habis/masuk silo.

    Pembaca kompatibel dengan instalasi mandiri yang belum memiliki tabel
    PadiFlow. Tidak menebak hubungan dari nama pemilik atau saldo saat ini.
    """
    tabel = await db.run_sync(lambda s: set(inspect(s.connection()).get_table_names()))
    hasil = []
    for nama, label in (("finished_goods_stock", "stok beras"),
                        ("byproduct_stock", "stok hasil samping"),
                        ("beras_ke_silo", "pemindahan beras ke silo")):
        if nama not in tabel:
            continue
        kolom = await db.run_sync(lambda s: {c['name'] for c in inspect(s.connection()).get_columns(nama)})
        if not {'source_type', 'source_id', 'id'} <= kolom:
            continue
        # Nama tabel berasal dari daftar tetap di atas, bukan payload.
        nomor = await db.scalar(text(f"SELECT id FROM {nama} WHERE source_type='timbangan' AND source_id=:tid LIMIT 1"), {'tid': trx.id})
        if nomor is not None:
            hasil.append(f"{label} #{nomor}")
    if 'activity_logs' in tabel:
        kolom = await db.run_sync(lambda s: {c['name'] for c in inspect(s.connection()).get_columns('activity_logs')})
        if {'action', 'table_name', 'aksi', 'field_name', 'old_value', 'new_value'} <= kolom:
            pola = trx.kode.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + ' · %'
            ada = await db.scalar(text("""
                SELECT 1 FROM activity_logs
                WHERE action='INSERT' AND table_name IN ('finished_goods_stock','byproduct_stock')
                  AND ((aksi='produk_timbang_masuk' AND field_name='timbangan_transaksi_id' AND old_value=:tid)
                       OR new_value LIKE :kode ESCAPE '\\') LIMIT 1
            """), {'tid': str(trx.id), 'kode': pola})
            if ada:
                hasil.append('arsip penerimaan produk PadiFlow')
    return hasil

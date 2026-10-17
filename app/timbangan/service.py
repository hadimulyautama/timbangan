"""Lapisan layanan modul Timbangan: penyimpanan, query, agregasi.

Semua rumus bisnis dipanggil dari `app.timbangan.logic` — modul ini hanya
mengurus DB, aturan kunci/koreksi, pemeriksaan, dan audit.

Dua hal yang membentuk seluruh rancangan modul ini:

  · **Nomor transaksi dibentuk di perangkat.** Server tidak pernah menomori.
    Penyimpanan bersifat idempoten terhadap `kode`, jadi kiriman ulang dari
    antrean offline tidak pernah menghasilkan transaksi kembar.
  · **Aturan komoditas dibaca dari DB lalu disalin ke transaksi.** Merevisi
    ambang tidak pernah menggeser status transaksi yang sudah tersimpan.
"""
from __future__ import annotations

import json
import dataclasses
import logging
import math
from typing import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, func, literal, or_, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from hmu_core import (JenisProses, ProsesTerpadu, StatusProses,
                       normalisasi_nomor_polisi)

from zoneinfo import ZoneInfo

from app.config import settings
from app.models import Pelanggan, Supplier
from hmu_identitas import masuk as identitas
from hmu_identitas import peran as P
from hmu_identitas import pintu
from hmu_identitas.model import Akun
from app.timbangan import format as fmt, logic, setelan
from app.timbangan.config import tsettings
from app.timbangan.db import berzona, sekarang
from app.timbangan.tautan_produksi import pastikan_bebas_tautan
from app.timbangan.models import (
    CARA_DUA_KALI,
    CARA_PARTAI,
    CARA_SEKALI,
    PEMERIKSAAN_DIBUKA,
    PEMERIKSAAN_SELESAI,
    ROLE_ADMIN,
    ROLE_SUPERADMIN,
    ROLES,
    TIKET_DITUTUP_PAKSA,
    TIKET_SELESAI,
    TIKET_TERBUKA,
    TRX_AKTIF,
    TRX_VOID,
    TimbanganAkun,
    TimbanganPenimbangan,
    TimbanganAudit,
    TimbanganCetak,
    TimbanganFoto,
    TimbanganJenis,
    TimbanganNomor,
    TimbanganKendaraan,
    TimbanganMuatan,
    TimbanganPemeriksaan,
    TimbanganSkorSupplier,
    TimbanganSupplierProfil,
    TimbanganTaraStandar,
    TimbanganTransaksi,
)


log = logging.getLogger("timbangan.service")


async def _sinkronkan_proses_bersama(
    db: AsyncSession, trx: TimbanganTransaksi
) -> None:
    """Cerminkan siklus tiket timbang ke indeks proses bersama.

    Tiket timbang tetap menjadi sumber angka bruto, tara, netto, dan detail
    muatan. Baris bersama hanya indeks/jejak proses: ia tidak membawa arus
    stok karena penimbangan mengukur barang, bukan memindahkannya. Menulisnya
    pada sesi yang sama membuat kedua catatan selalu berhasil atau batal
    bersama, dan kunci sumber membuat kiriman ulang tetap satu baris.
    """
    if trx.id is None:
        await db.flush()

    # Akun timbang adalah profil lokal/kompatibilitas. Identitas orangnya
    # tetap `users.id` bersama. Simpan pelaksana kanonis pada ledger proses
    # agar riwayat lintas aplikasi tidak bergantung pada ID profil timbang.
    pelaksana_id = None
    if trx.dibuat_oleh_id is not None:
        pelaksana_id = (await db.execute(
            select(TimbanganAkun.user_id).where(
                TimbanganAkun.id == trx.dibuat_oleh_id
            )
        )).scalar_one_or_none()

    proses = (await db.execute(
        select(ProsesTerpadu).where(
            ProsesTerpadu.aplikasi == "timbangan",
            ProsesTerpadu.tabel_sumber == "timbangan_transaksi",
            ProsesTerpadu.id_sumber == str(trx.id),
        )
    )).scalar_one_or_none()

    status = (
        StatusProses.DIBATALKAN.value if trx.status_transaksi == TRX_VOID
        else StatusProses.DIHENTIKAN.value if trx.status_tiket == TIKET_DITUTUP_PAKSA
        else StatusProses.SELESAI.value if trx.status_tiket == TIKET_SELESAI
        else StatusProses.BERJALAN.value
    )
    jasa = bool(getattr(trx, "jasa", False)) and trx.arah == logic.MASUK
    metadata = {
        "arah": trx.arah,
        "jenis_kode": trx.jenis_kode,
        "cara_timbang": trx.cara_timbang,
        "nomor_polisi": trx.nomor_polisi,
        "kendaraan_id": trx.kendaraan_id,
        "nama_sopir": trx.nama_sopir,
        "pihak_nama": trx.pihak_nama,
        "supplier_id": trx.supplier_id,
        "pelanggan_id": trx.pelanggan_id,
        "jasa": jasa,
        "timbang1_kg": trx.timbang1_kg,
        "timbang2_kg": trx.timbang2_kg,
        "netto_timbangan_kg": trx.netto_timbangan_kg,
        "berat_barang_kg": trx.berat_barang_kg,
        "total_tara_kg": trx.total_tara_kg,
        "jumlah_karung": trx.jumlah_karung,
        "berat_acuan_kg": trx.berat_acuan_kg,
        "selisih_kg": trx.selisih_kg,
        "status_kontrol": trx.status_kontrol,
        "timbang1_waktu": (trx.timbang1_waktu.isoformat()
                            if trx.timbang1_waktu else None),
        "timbang2_waktu": (trx.timbang2_waktu.isoformat()
                            if trx.timbang2_waktu else None),
        "timbang1_petugas_id": trx.timbang1_petugas_id,
        "timbang2_petugas_id": trx.timbang2_petugas_id,
        "void_alasan": trx.void_alasan,
        "tutup_paksa_alasan": trx.tutup_paksa_alasan,
        "muatan": [
            {
                "jenis_kode": m.jenis_kode,
                "nomor_acuan": m.nomor_acuan,
                "jumlah_karung": m.jumlah_karung,
                "berat_acuan_kg": m.berat_acuan_kg,
                "tara_per_karung_kg": m.tara_per_karung_kg,
                "kualitas_id": m.kualitas_id,
                "merek_produk_id": m.merek_produk_id,
                "packaging_material_id": m.packaging_material_id,
                "package_size_id": m.package_size_id,
            }
            for m in trx.muatan
        ],
    }
    nilai = {
        "kode": trx.kode,
        "jenis": JenisProses.PENIMBANGAN.value,
        "status": status,
        # Untuk barang jasa, pemilik barang memang pelanggan. Barang
        # pembelian dan pengiriman dicatat sebagai proses milik pabrik;
        # pihak lawan transaksi tetap tersimpan di metadata.
        "jenis_pemilik": "pelanggan" if jasa else "pabrik",
        "id_pemilik": trx.pelanggan_id if jasa else None,
        "nama_pemilik": trx.pihak_nama if jasa else None,
        "waktu_mulai": trx.timbang1_waktu,
        "waktu_selesai": (
            trx.void_pada if trx.status_transaksi == TRX_VOID
            else trx.timbang2_waktu if trx.status_tiket == TIKET_SELESAI
            else sekarang() if trx.status_tiket == TIKET_DITUTUP_PAKSA
            else None
        ),
        "pelaksana_id": pelaksana_id,
        "referensi_asal": [f"{nama}:{nilai}" for nama, nilai in (
            ("purchase_batch", trx.purchase_batch_id),
            ("pk_purchase_batch", trx.pk_purchase_batch_id),
            ("jasa", trx.jasa_id),
        ) if nilai is not None],
        "metadata_domain": metadata,
    }
    if proses is None:
        proses = ProsesTerpadu(
            aplikasi="timbangan", tabel_sumber="timbangan_transaksi",
            id_sumber=str(trx.id), **nilai,
        )
        db.add(proses)
    else:
        for nama, isi in nilai.items():
            setattr(proses, nama, isi)


class LayananError(Exception):
    """Kesalahan aturan bisnis yang layak ditampilkan ke pengguna."""


# ═══════════════════════════ Audit ═══════════════════════════

async def catat_audit(
    db: AsyncSession,
    *,
    akun: TimbanganAkun | None,
    aksi: str,
    entitas: str | None = None,
    entitas_id: str | int | None = None,
    ringkasan: str | None = None,
    sebelum: dict | None = None,
    sesudah: dict | None = None,
    perangkat: str | None = None,
    ip: str | None = None,
) -> None:
    """Tulis satu baris audit. Hanya bertambah — tidak pernah menimpa."""
    db.add(TimbanganAudit(
        akun_id=akun.id if akun else None,
        akun_nama=akun.nama if akun else None,
        aksi=aksi,
        entitas=entitas,
        entitas_id=str(entitas_id) if entitas_id is not None else None,
        ringkasan=ringkasan,
        nilai_sebelum=json.dumps(sebelum, ensure_ascii=False) if sebelum else None,
        nilai_sesudah=json.dumps(sesudah, ensure_ascii=False) if sesudah else None,
        perangkat_kode=perangkat,
        ip=ip,
    ))


# ═══════════════════════════ Aturan komoditas ═══════════════════════════

def _aturan_dari_baris(baris: TimbanganJenis) -> logic.AturanJenis:
    return logic.AturanJenis(
        kode=baris.kode,
        nama=baris.nama,
        arah=baris.arah,
        acuan=baris.acuan,
        sumber_tara=baris.sumber_tara,
        tara_tetap_kg=float(baris.tara_tetap_kg or 0),
        tara_bawaan_kg=float(baris.tara_bawaan_kg or 0),
        ambang_jenis=baris.ambang_jenis,
        ambang_nilai=float(baris.ambang_nilai or 0),
        ambang_arah=baris.ambang_arah,
        ambang_investigasi_nilai=(
            float(baris.ambang_investigasi_nilai)
            if baris.ambang_investigasi_nilai is not None else None
        ),
        rahasia=bool(baris.rahasia),
        cetak_bukti=bool(baris.cetak_bukti),
        masa_berlaku_tara_hari=int(baris.masa_berlaku_tara_hari or 90),
        boleh_jasa=bool(getattr(baris, "boleh_jasa", False)),
    )


async def daftar_jenis(
    db: AsyncSession, *, arah: str | None = None, hanya_aktif: bool = True
) -> list[TimbanganJenis]:
    q = select(TimbanganJenis).order_by(TimbanganJenis.urutan, TimbanganJenis.nama)
    if hanya_aktif:
        q = q.where(TimbanganJenis.status == "aktif")
    if arah:
        q = q.where(TimbanganJenis.arah.in_([arah, logic.BEBAS]))
    return list((await db.execute(q)).scalars())


async def daftar_jenis_jasa(db: AsyncSession) -> list[TimbanganJenis]:
    """Komoditas yang boleh masuk sebagai barang JASA — dari MASTER, bukan daftar.

    Kosong berarti kartu "Barang masuk jasa" tidak digambar sama sekali di
    beranda, dan itu perilaku yang benar: kartu yang membuka daftar hampa
    menyuruh petugas memilih dari ketiadaan. Bentuk kartunya pun mengikuti
    jumlahnya — satu komoditas jadi tautan langsung, dua atau lebih membentang
    — jadi membuka komoditas kedua lewat master mengubah kartunya sendiri,
    tanpa menyentuh satu berkas pun.

    `arah` tetap MASUK: jasa bukan arah baru, ia pemilik yang berbeda pada arah
    yang sama. Menjadikannya arah tersendiri berarti menggandakan aturan tara
    dan ambang untuk barang yang cara menimbangnya sama persis.
    """
    q = (select(TimbanganJenis)
         .where(TimbanganJenis.status == "aktif",
                TimbanganJenis.boleh_jasa.is_(True),
                TimbanganJenis.arah == logic.MASUK)
         .order_by(TimbanganJenis.urutan, TimbanganJenis.nama))
    return list((await db.execute(q)).scalars())


@dataclass(frozen=True)
class PesananJasa:
    """Satu pesanan jasa yang masih berjalan, beserta apa yang sudah masuk.

    Bobot & jumlah truknya dihitung dari TIKET DI SINI, bukan dari batch di
    produksi. Dua sebab, dan yang kedua menentukan: tiket adalah yang petugas
    pos kenali ("yang tadi pagi itu"), dan tiket yang BELUM diterima produksi
    belum punya batch sama sekali — kalau dihitung dari sana, truk kedua yang
    datang sejam setelah yang pertama akan melihat "0 kg · 0 truk" dan
    menyangka ia salah pesanan.
    """

    id: int
    kode: str
    nama_pelanggan: str
    berat_kg: float
    truk: int


#: Keadaan pesanan jasa yang masih menerima barang. Satu kata, dan ia milik
#: produksi (`app/models/jasa.py` di sana) — disebut di sini sebagai teks
#: karena modul ini hanya MEMBACA tabelnya.
JASA_BERJALAN = "berjalan"

#: Pesanan jasa milik satu pelanggan yang masih berjalan.
#:
#: SQL mentah, sama seperti `tautan_produksi`: tabel `jasa` dimiliki repo
#: penggilingan dan tidak ada di metadata modul ini. Membacanya lewat ORM
#: berarti memetakan model kedua untuk tabel orang lain, lalu menanggung
#: perbedaannya setiap kali kolomnya berubah di sana.
#:
#: Bobot per pesanan dijumlah dari tiket yang MENUNJUKNYA, dan tiket yang
#: dibatalkan tidak ikut: ia tak membawa barang apa pun.
_SQL_PESANAN_JASA = text("""
    SELECT j.id, j.kode, p.nama_pelanggan,
           COALESCE(SUM(COALESCE(NULLIF(t.berat_barang_kg, 0),
                                 t.netto_timbangan_kg, 0)), 0) AS berat,
           COUNT(t.id) AS truk
      FROM jasa j
      JOIN pelanggan p ON p.id = j.pelanggan_id
      LEFT JOIN timbangan_transaksi t
             ON t.jasa_id = j.id AND t.status_transaksi = 'AKTIF'
     WHERE j.pelanggan_id = :pid
       AND j.status = :berjalan
     GROUP BY j.id, j.kode, p.nama_pelanggan
     ORDER BY j.id DESC
""")


async def _baca_pesanan(db: AsyncSession, sql, param: dict) -> list[PesananJasa]:
    """Baca daftar pesanan jasa — dan BERTAHAN bila tabelnya tak ada.

    Tabel `jasa` dimiliki repo penggilingan. Modul ini harus tetap berdiri
    sendiri tanpa sistem itu — pemasangan baru, atau produksi yang belum
    bermigrasi — dan yang hilang saat tabelnya tak ada cuma penawaran
    "tambahkan ke pesanan": tiap tiket jadi pesanan baru, dan borangnya tetap
    bisa dipakai. Layar galat di pos sementara truknya di jembatan jauh lebih
    buruk daripada satu pilihan yang tak muncul.

    ⚠ DI DALAM SAVEPOINT, bukan dengan `db.rollback()` pada sesi pemanggil.
    Galat basis data membatalkan transaksi yang sedang berjalan di Postgres,
    jadi kueri ini HARUS dipagari — tetapi `rollback()` penuh akan membuang
    pekerjaan pemanggilnya yang belum tersimpan. Penolong baca yang membatalkan
    tulisan orang lain adalah jebakan yang baru terasa pada hari ia dipanggil
    dari tempat kedua.
    """
    try:
        async with db.begin_nested():
            baris = (await db.execute(sql, param)).all()
    except DBAPIError:
        return []
    return [PesananJasa(id=b[0], kode=b[1], nama_pelanggan=b[2],
                        berat_kg=float(b[3] or 0), truk=int(b[4] or 0))
            for b in baris]


async def pesanan_jasa_berjalan(
    db: AsyncSession, pelanggan_id: int | None
) -> list[PesananJasa]:
    """Pesanan jasa pelanggan ini yang masih berjalan — untuk ditawarkan borang.

    ⚠ TANPA SARINGAN JENIS, dan itu koreksi atas rancangan awal. Satu pelanggan
    boleh mendatangkan gabah basah lalu gabah kering untuk pekerjaan yang SAMA;
    menyaring "pesanan berjenis sama" akan memaksanya jadi dua pesanan, lalu
    penjaga kepemilikan di produksi menolak menggiling keduanya bersama — tepat
    kesalahan yang penawaran ini ada untuk mencegahnya.
    """
    if not pelanggan_id:
        return []
    return await _baca_pesanan(
        db, _SQL_PESANAN_JASA,
        {"pid": int(pelanggan_id), "berjalan": JASA_BERJALAN})


#: Seluruh pesanan jasa yang masih berjalan, siapa pun pemiliknya.
#:
#: Bentuknya sama dengan `_SQL_PESANAN_JASA`; yang berbeda cuma tanpa saringan
#: pelanggan. Dirakit dari satu kalimat yang sama supaya kedua daftar tak
#: pernah menghitung bobot dengan cara berbeda — "12.000 kg" di satu layar dan
#: "11.940 kg" di layar lain untuk pesanan yang sama adalah selisih yang akan
#: dicari orang di tempat yang salah.
_SQL_PESANAN_JASA_SEMUA = text(
    str(_SQL_PESANAN_JASA).replace("j.pelanggan_id = :pid\n       AND ", ""))


async def pesanan_jasa_semua_berjalan(db: AsyncSession) -> list[PesananJasa]:
    """Pesanan jasa berjalan milik siapa pun — untuk daftar di borang.

    Tiap barisnya MENYEBUT pemiliknya, sebab daftar ini tidak disaring menurut
    pelanggan yang baru dipilih: lihat catatan di rute `/jasa/{jenis_kode}`.
    """
    return await _baca_pesanan(
        db, _SQL_PESANAN_JASA_SEMUA, {"berjalan": JASA_BERJALAN})


async def peta_aturan(db: AsyncSession) -> dict[str, logic.AturanJenis]:
    """Aturan seluruh komoditas, dibaca dari DB.

    Bila tabel masih kosong (mis. di lingkungan uji), pakai aturan awal dari
    `logic` supaya modul tetap bisa berjalan tanpa penyemaian lebih dulu.
    """
    baris = list((await db.execute(select(TimbanganJenis))).scalars())
    if not baris:
        return dict(logic.JENIS_PETA)
    return {b.kode: _aturan_dari_baris(b) for b in baris}


async def aturan_untuk(db: AsyncSession, kode: str) -> logic.AturanJenis:
    peta = await peta_aturan(db)
    if kode not in peta:
        raise LayananError(f"Komoditas '{kode}' tidak dikenal.")
    return peta[kode]


# ═══════════════════════════ Penyemaian ═══════════════════════════

async def pastikan_jenis(db: AsyncSession) -> int:
    """Isi master komoditas dari `logic.JENIS_AWAL` bila belum ada.

    Hanya MENAMBAH yang belum ada — aturan yang sudah disetel manajemen di DB
    tidak pernah ditimpa oleh nilai bawaan kode.
    """
    ada = set((await db.execute(select(TimbanganJenis.kode))).scalars())
    ditambah = 0
    for urut, a in enumerate(logic.JENIS_AWAL, start=1):
        if a.kode in ada:
            continue
        db.add(TimbanganJenis(
            kode=a.kode, nama=a.nama, urutan=urut * 10,
            arah=a.arah, acuan=a.acuan, sumber_tara=a.sumber_tara,
            tara_tetap_kg=a.tara_tetap_kg, tara_bawaan_kg=a.tara_bawaan_kg,
            ambang_jenis=a.ambang_jenis, ambang_nilai=a.ambang_nilai,
            ambang_arah=a.ambang_arah,
            ambang_investigasi_nilai=a.ambang_investigasi_nilai,
            rahasia=a.rahasia, cetak_bukti=a.cetak_bukti,
            masa_berlaku_tara_hari=a.masa_berlaku_tara_hari,
            boleh_jasa=a.boleh_jasa,
        ))
        ditambah += 1
    if ditambah:
        await db.commit()
    return ditambah


async def pastikan_admin(db: AsyncSession) -> bool:
    """Buat akun admin awal bila tabel akun masih kosong.

    Tanpa `TIMBANGAN_ADMIN_PASSWORD` di environment, tidak ada akun yang dibuat
    — lebih baik aplikasi tidak bisa dimasuki daripada punya sandi tebakan.
    """
    from app.timbangan.security import hash_sandi

    if (await db.execute(select(func.count(TimbanganAkun.id)))).scalar_one():
        return False
    if not tsettings.admin_password:
        return False
    db.add(TimbanganAkun(
        username=tsettings.admin_username,
        nama=tsettings.admin_nama,
        role=ROLE_ADMIN,
        password_hash=hash_sandi(tsettings.admin_password),
    ))
    await db.commit()
    return True


# ═══════════════════════════ Utilitas ═══════════════════════════

def normalisasi_nopol(nopol: str | None) -> str | None:
    """'  ad 1234 xy ' → 'AD 1234 XY'."""
    return normalisasi_nomor_polisi(nopol)


async def kendaraan_dari_nopol(
    db: AsyncSession, nopol: str | None
) -> TimbanganKendaraan | None:
    """Cari armada; daftarkan bila belum ada. Master tumbuh sendiri dari pakai."""
    bersih = normalisasi_nopol(nopol)
    if not bersih:
        return None
    kendaraan = (await db.execute(
        select(TimbanganKendaraan).where(TimbanganKendaraan.nomor_polisi == bersih)
    )).scalars().first()
    if kendaraan is None:
        kendaraan = TimbanganKendaraan(nomor_polisi=bersih)
        db.add(kendaraan)
        await db.flush()
    return kendaraan


async def profil_supplier(
    db: AsyncSession, supplier_id: int, *, buat: bool = True
) -> TimbanganSupplierProfil | None:
    profil = (await db.execute(
        select(TimbanganSupplierProfil).where(
            TimbanganSupplierProfil.supplier_id == supplier_id
        )
    )).scalars().first()
    if profil is None and buat:
        profil = TimbanganSupplierProfil(supplier_id=supplier_id)
        db.add(profil)
        await db.flush()
    return profil


#: Lawan transaksi menurut arah: model, kolomnya di transaksi, nama kolomnya.
#:
#: **Barang masuk hanya supplier, pengiriman hanya pelanggan.** Menawarkan
#: keduanya di kedua arah membuat petugas bisa mencatat penjualan atas nama
#: pemasok karung — dan salah pilih semacam itu baru ketahuan berbulan-bulan
#: kemudian, saat rekonsiliasi tidak ketemu.
#: Retur menyilang dengan sengaja: barang yang dikembalikan PELANGGAN datang
#: masuk, dan barang yang dikembalikan KE SUPPLIER berangkat keluar. Yang
#: menentukan tabel lawan transaksi adalah dengan siapa urusannya, bukan ke
#: mana barangnya bergerak.
PIHAK_ARAH: dict[str, tuple] = {
    logic.MASUK: (Supplier, "supplier_id", "nama_supplier"),
    logic.KELUAR: (Pelanggan, "pelanggan_id", "nama_pelanggan"),
    logic.RETUR_MASUK: (Pelanggan, "pelanggan_id", "nama_pelanggan"),
    logic.RETUR_KELUAR: (Supplier, "supplier_id", "nama_supplier"),
}


def pihak_untuk(arah: str, *, jasa: bool = False) -> tuple | None:
    """(model, kolom transaksi, kolom nama) — atau None bila arah ini tidak
    memakai master pihak sama sekali (jasa timbang, transfer internal).

    ⚠ `jasa` MEMBALIK jawabannya pada arah MASUK, dan di sinilah SATU-SATUNYA
    tempat yang tahu soal itu. Barang masuk biasanya dibeli, jadi lawannya
    pemasok; barang jasa dititipkan, jadi lawannya pelanggan — arahnya sama,
    tabelnya berbeda, sebab yang membedakan bukan arah barangnya melainkan
    hubungan hukumnya.

    Dipusatkan karena fakta itu dibutuhkan EMPAT pembaca: daftar pilihan di
    borang, nama kolom untuk templatnya, penulisan id ke tiket, dan pencarian
    tara per pihak. Empat salinan "kalau jasa maka pelanggan" adalah empat
    kesempatan salah satunya tertinggal — dan yang tertinggal akan menulis
    pemilik barang ke kolom pemasok, diam-diam.
    """
    if jasa:
        return PIHAK_ARAH[logic.KELUAR]      # (Pelanggan, "pelanggan_id", …)
    return PIHAK_ARAH.get(arah)


def nama_kolom_pihak(arah: str, *, jasa: bool = False) -> str:
    """Nama atribut yang memuat nama pihak, supaya template tidak perlu tahu
    tabel mana yang sedang dipakai."""
    pihak = pihak_untuk(arah, jasa=jasa)
    return pihak[2] if pihak else "nama"


def _saring_hidup(q, model):
    """Buang baris yang sudah dihapus (soft delete).

    Pemasok yang sudah dihapus tetap ditawarkan di layar timbang, dan tiket
    yang tertaut padanya tak bisa ditelusuri ke mana pun sesudahnya. Penyaring
    lamanya merujuk `is_active` — atribut yang tak pernah ada di model ini —
    jadi `hasattr` selalu False dan penyaringnya tak pernah berjalan sekali
    pun. Temuan QA T-24.
    """
    if hasattr(model, "deleted_at"):
        q = q.where(model.deleted_at.is_(None))
    if hasattr(model, "status"):
        q = q.where(model.status != "nonaktif")
    return q


async def daftar_pihak(db: AsyncSession, arah: str, *, jasa: bool = False) -> list:
    """Calon lawan transaksi yang MASIH ADA untuk arah ini, terurut nama.

    ⚠ `jasa` WAJIB diteruskan, dan pernah terlewat di sini. Tanpanya arah MASUK
    menjawab daftar PEMASOK untuk borang jasa — sementara medannya bernama
    `pelanggan_id`. Hasilnya bentuk kesalahan yang paling sulit dilihat:
    borangnya tampak benar, petugas memilih nama yang ada di daftar, dan id
    pemasok tersimpan di kolom pelanggan. Tak ada galat, dan barang titipan
    tertaut ke pihak yang tak pernah menitipkan apa pun.
    """
    pihak = pihak_untuk(arah, jasa=jasa)
    if pihak is None:
        return []
    model, _, kolom_nama = pihak
    return list((await db.execute(
        _saring_hidup(select(model), model).order_by(getattr(model, kolom_nama))
    )).scalars())


async def pihak_pilihan(
    db: AsyncSession, arah: str, *, hari: int = 120, jasa: bool = False
) -> tuple[list, list]:
    """Dipecah dua: yang benar-benar dipakai belakangan, dan sisanya.

    Daftar dari Kledo memuat seluruh kontak — termasuk pemasok karung dan
    sablon yang tidak pernah lewat jembatan timbang, dan 301 pelanggan yang
    sebagian membeli sekali setahun. Petugas hanya berurusan dengan belasan
    nama; menyuruhnya menggulir ratusan nama di ponsel, sambil truk menunggu,
    adalah cara membuat orang salah pilih.
    """
    pihak = pihak_untuk(arah, jasa=jasa)
    if pihak is None:
        return [], []
    _, kolom_trx, _ = pihak
    kolom = getattr(TimbanganTransaksi, kolom_trx)

    batas = sekarang().date() - timedelta(days=hari)
    terpakai = set((await db.execute(
        select(kolom).where(
            kolom.is_not(None),
            TimbanganTransaksi.tanggal >= batas,
            TimbanganTransaksi.status_transaksi == TRX_AKTIF,
        ).distinct()
    )).scalars())

    semua = await daftar_pihak(db, arah, jasa=jasa)
    return ([s for s in semua if s.id in terpakai],
            [s for s in semua if s.id not in terpakai])


@dataclass(frozen=True)
class KendaraanDikenal:
    """Satu plat yang pernah lewat jembatan, beserta sopir terakhirnya."""

    nomor_polisi: str
    sopir_terakhir: str | None
    terakhir: date | None


async def kendaraan_dikenal(
    db: AsyncSession, *, hari: int = 180, batas: int = 200
) -> list[KendaraanDikenal]:
    """Plat yang pernah datang, terbaru lebih dulu.

    Tabel `timbangan_kendaraan` sudah mencatat setiap plat sejak awal, lalu
    tidak pernah dibaca kembali — sementara 69% penimbangan (38 dari 55, diukur
    8 September 2026) memakai plat yang sistemnya sudah hafal. Petugas
    mengetiknya ulang sambil truk menunggu.

    Yang dikembalikan SARAN, bukan isian. Nomor polisi adalah jangkar tiket
    ini bila kelak ada sengketa; tebakan yang masuk diam-diam lebih berbahaya
    daripada mengetik.

    Sopir diambil dari penimbangan TERAKHIR plat itu, bukan dari yang paling
    sering. Sebutannya di layar pun "terakhir", karena memang itu yang
    diketahui — sopir bisa berganti, dan pada satu dari empat plat berulang ia
    memang berganti.
    """
    batas_hari = sekarang().date() - timedelta(days=hari)

    # Dua langkah, bukan window function: SQLite di pengujian dan Postgres di
    # produksi tidak selalu sepakat soal DISTINCT ON, dan daftarnya pendek.
    terakhir = (await db.execute(
        select(
            TimbanganTransaksi.nomor_polisi,
            func.max(TimbanganTransaksi.id).label("id_akhir"),
        ).where(
            TimbanganTransaksi.nomor_polisi.is_not(None),
            TimbanganTransaksi.nomor_polisi != "",
            TimbanganTransaksi.tanggal >= batas_hari,
            TimbanganTransaksi.status_transaksi == TRX_AKTIF,
        ).group_by(TimbanganTransaksi.nomor_polisi)
        .order_by(func.max(TimbanganTransaksi.id).desc())
        .limit(batas)
    )).all()
    if not terakhir:
        return []

    baris = {
        t.id: t for t in (await db.execute(
            select(TimbanganTransaksi).where(
                TimbanganTransaksi.id.in_([r.id_akhir for r in terakhir])
            )
        )).scalars()
    }
    hasil = []
    for r in terakhir:
        t = baris.get(r.id_akhir)
        hasil.append(KendaraanDikenal(
            nomor_polisi=r.nomor_polisi,
            sopir_terakhir=(t.nama_sopir or None) if t else None,
            terakhir=t.tanggal if t else None,
        ))
    return hasil


async def supplier_pilihan(
    db: AsyncSession, *, hari: int = 120
) -> tuple[list[Supplier], list[Supplier]]:
    """Khusus arah masuk. Dipertahankan karena dipakai layar tara standar."""
    return await pihak_pilihan(db, logic.MASUK, hari=hari)


async def daftar_supplier(
    db: AsyncSession, *, hanya_aktif: bool = True
) -> list[Supplier]:
    """Pemasok yang masih ada. Lihat `_saring_hidup` untuk sebabnya."""
    q = select(Supplier)
    if hanya_aktif:
        q = _saring_hidup(q, Supplier)
    return list((await db.execute(q.order_by(Supplier.nama_supplier))).scalars())


# ═══════════════════════════ Tara standar ═══════════════════════════

async def tara_berlaku(
    db: AsyncSession, *, supplier_id: int | None, jenis_kode: str
) -> TimbanganTaraStandar | None:
    """Sampling tara yang masih berlaku untuk pihak × komoditas ini.

    Sampling khusus pihak menang atas sampling umum (`supplier_id` kosong).
    """
    hari = sekarang().date()
    q = (
        select(TimbanganTaraStandar)
        .where(
            TimbanganTaraStandar.jenis_kode == jenis_kode,
            TimbanganTaraStandar.status == "BERLAKU",
            TimbanganTaraStandar.berlaku_mulai <= hari,
            or_(
                TimbanganTaraStandar.berlaku_sampai.is_(None),
                TimbanganTaraStandar.berlaku_sampai >= hari,
            ),
            or_(
                TimbanganTaraStandar.supplier_id == supplier_id,
                TimbanganTaraStandar.supplier_id.is_(None),
            ),
        )
        .order_by(
            TimbanganTaraStandar.supplier_id.is_(None),   # khusus dulu
            TimbanganTaraStandar.berlaku_mulai.desc(),
        )
    )
    return (await db.execute(q)).scalars().first()


async def tara_disarankan(
    db: AsyncSession, *, supplier_id: int | None, aturan: logic.AturanJenis
) -> tuple[float, TimbanganTaraStandar | None]:
    """Tara per karung yang diusulkan ke layar, beserta asalnya."""
    if aturan.sumber_tara == logic.TARA_SAMPLING:
        baris = await tara_berlaku(
            db, supplier_id=supplier_id, jenis_kode=aturan.kode
        )
        if baris is not None:
            return float(baris.tara_per_karung_kg), baris
    return aturan.tara_default(), None


async def simpan_tara_standar(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    supplier_id: int | None,
    jenis_kode: str,
    jumlah_sampel: int,
    total_berat_kg: float,
    jenis_karung: str | None = None,
    alasan: str | None = None,
) -> TimbanganTaraStandar:
    """Catat sampling baru. Yang lama DIGANTI, tidak pernah ditimpa."""
    if jumlah_sampel <= 0:
        raise LayananError("Jumlah karung sampel harus lebih dari 0.")
    if total_berat_kg <= 0:
        raise LayananError("Total berat sampel harus lebih dari 0.")

    aturan = await aturan_untuk(db, jenis_kode)
    hari = sekarang().date()

    lama = await tara_berlaku(db, supplier_id=supplier_id, jenis_kode=jenis_kode)
    if lama is not None and lama.supplier_id == supplier_id:
        lama.status = "DIGANTI"
        lama.berlaku_sampai = hari

    baris = TimbanganTaraStandar(
        supplier_id=supplier_id,
        jenis_kode=jenis_kode,
        jumlah_sampel=jumlah_sampel,
        total_berat_kg=total_berat_kg,
        tara_per_karung_kg=round(total_berat_kg / jumlah_sampel, 4),
        jenis_karung=jenis_karung,
        berlaku_mulai=hari,
        berlaku_sampai=hari + timedelta(days=aturan.masa_berlaku_tara_hari),
        alasan=alasan,
        dibuat_oleh_id=akun.id,
    )
    db.add(baris)
    await db.flush()
    await catat_audit(
        db, akun=akun, aksi="TARA_STANDAR", entitas="tara_standar",
        entitas_id=baris.id,
        ringkasan=(
            f"{jenis_kode}: {jumlah_sampel} karung / {total_berat_kg} kg "
            f"= {baris.tara_per_karung_kg} kg per karung"
        ),
        sesudah={"tara_per_karung_kg": float(baris.tara_per_karung_kg)},
    )
    return baris


async def tara_jatuh_tempo(db: AsyncSession, *, dalam_hari: int = 14) -> list:
    """Sampling tara yang akan atau sudah kedaluwarsa — bahan radar."""
    batas = sekarang().date() + timedelta(days=dalam_hari)
    q = (
        select(TimbanganTaraStandar, Supplier.nama_supplier)
        .outerjoin(Supplier, Supplier.id == TimbanganTaraStandar.supplier_id)
        .where(
            TimbanganTaraStandar.status == "BERLAKU",
            TimbanganTaraStandar.berlaku_sampai.is_not(None),
            TimbanganTaraStandar.berlaku_sampai <= batas,
        )
        .order_by(TimbanganTaraStandar.berlaku_sampai)
    )
    return list((await db.execute(q)).all())


# ═══════════════════════════ Aturan kunci & koreksi ═══════════════════════

def terkunci_untuk_petugas(
    trx: TimbanganTransaksi, jam_kunci: float | None = None
) -> bool:
    """Transaksi selesai mengunci sendiri setelah beberapa jam."""
    if trx.terkunci:
        return True
    if not trx.selesai:
        return False
    acuan = berzona(trx.timbang2_waktu_sistem or trx.created_at)
    if acuan is None:
        return False
    if jam_kunci is None:
        jam_kunci = tsettings.jam_kunci_otomatis
    return sekarang() - acuan > timedelta(hours=jam_kunci)


def boleh_mengubah(
    trx: TimbanganTransaksi, akun: TimbanganAkun, jam_kunci: float | None = None
) -> tuple[bool, str]:
    """Input yang salah boleh dikoreksi — dengan jejak, bukan diam-diam."""
    if trx.status_transaksi == TRX_VOID:
        return False, "Transaksi sudah dibatalkan."
    if akun.is_admin:
        return True, ""
    if terkunci_untuk_petugas(trx, jam_kunci):
        jam = jam_kunci if jam_kunci is not None else tsettings.jam_kunci_otomatis
        return False, (
            f"Transaksi terkunci setelah {jam:g} jam. "
            "Minta Admin untuk mengoreksi."
        )
    return True, ""


def boleh_membatalkan(akun: TimbanganAkun,
                      trx: TimbanganTransaksi | None = None) -> bool:
    """Admin selalu. Petugas HANYA tiket yang masih terbuka.

    Keputusan pemilik 30 September 2026: "jika masih timbang pertama dan harus
    timbang kedua. harus ada pilihan hapus dan jika dihapus hilang dari tiket
    terbuka."

    Batasnya TIMBANG KEDUA, dan itu garis yang tepat: sebelum timbang kedua
    belum ada netto, belum ada angka yang masuk ke pembukuan mana pun, dan
    yang dibatalkan cuma niat menimbang. Sesudahnya angkanya sudah jadi dasar
    keputusan orang lain — dan membatalkannya kembali jadi pekerjaan Admin.

    Truk yang salah dimulai, dipilih jenisnya keliru, atau batal bongkar
    sebelum kembali naik jembatan adalah keadaan sehari-hari di pos timbang.
    Sampai hari ini satu-satunya jalannya menunggu Admin — dan tiket yang
    menunggu itu berdiri di daftar "menunggu timbang kedua" sepanjang hari,
    membuat daftar yang seharusnya jadi pekerjaan mendesak berhenti dibaca.

    `trx` boleh kosong hanya untuk pertanyaan umum "apakah orang ini pernah
    boleh membatalkan"; yang menentukan keputusan sungguhan wajib membawanya.
    """
    if akun.is_admin:
        return True
    if trx is None:
        return False
    return (trx.status_tiket == TIKET_TERBUKA
            and trx.status_transaksi == TRX_AKTIF)


# ═══════════════════════════ Simpan transaksi ═══════════════════════════

@dataclass
class InputMuatan:
    jenis_kode: str
    jumlah_karung: int = 0
    tara_per_karung_kg: float = 0.0
    berat_acuan_kg: float = 0.0
    nomor_acuan: str | None = None
    tara_standar_id: int | None = None
    catatan: str | None = None
    kualitas_id: int | None = None
    merek_produk_id: int | None = None
    packaging_material_id: int | None = None
    package_size_id: int | None = None


@dataclass
class InputTimbang:
    """Satu kiriman dari perangkat.

    **Identitasnya `kunci`, bukan `kode`.** Kunci dibuat perangkat saat
    formulir dibuka, sekali, dan ikut pada tiap kiriman ulang dari antrean
    luring. Nomor tiketnya sendiri baru diterbitkan server saat menyimpan.

    Dulu sebaliknya: perangkat yang menomori, saat formulir dibuka, dan nomor
    itu dipakai sebagai identitas. Dua petugas yang membuka layar pada detik
    yang sama memegang nomor yang sama — lalu yang menyimpan belakangan
    menulis ulang tiket yang duluan, dan keduanya melihat "tersimpan".

    `kode` masih diterima demi kiriman lama yang tertahan di antrean luring
    sebelum pembaruan ini. Ia dipakai hanya untuk MENCOCOKKAN, tak pernah
    untuk menimpa: nomor yang sudah dimiliki tiket lain ditolak.
    """
    kode: str | None = None
    arah: str = ""
    jenis_kode: str = ""
    berat_kg: float = 0.0
    kunci: str | None = None
    waktu_operator: datetime | None = None
    cara_timbang: str = CARA_DUA_KALI
    supplier_id: int | None = None
    #: JASA: barangnya DITITIPKAN, bukan dibeli.
    #:
    #: Jasa bukan arah baru dan bukan jenis baru — cara menimbang, tara, dan
    #: ambangnya sama persis dengan gabah yang dibeli; yang beda cuma
    #: pemiliknya. Menjadikannya `GABAH_KERING_JASA` berarti menggandakan tiga
    #: jenis jadi enam, menggandakan aturan taranya, dan memberi petugas enam
    #: tombol berpasangan mirip untuk salah pilih.
    #:
    #: Konsekuensinya satu: pada arah MASUK, lawan transaksinya PELANGGAN, bukan
    #: pemasok. Lihat `_pasang_pihak`.
    jasa: bool = False
    #: Pemilik barang titipan — baris `pelanggan`, bukan `suppliers`.
    pelanggan_id: int | None = None
    #: Pesanan jasa yang sudah berjalan, bila petugas memilih "tambahkan ke".
    #: Kosong berarti pesanan BARU — dan yang melahirkannya produksi, saat
    #: operator menerima tiket ini.
    jasa_id: int | None = None
    pihak_nama: str | None = None
    nomor_polisi: str | None = None
    nama_sopir: str | None = None
    tara_lain_kg: float = 0.0
    muatan: list[InputMuatan] = field(default_factory=list)
    catatan: str | None = None
    perangkat_kode: str | None = None
    dibuat_offline: bool = False


def _baris_logic(muatan: list[TimbanganMuatan]) -> list[logic.BarisMuatan]:
    return [
        logic.BarisMuatan(
            jenis_kode=m.jenis_kode,
            jumlah_karung=int(m.jumlah_karung or 0),
            tara_per_karung_kg=float(m.tara_per_karung_kg or 0),
            berat_acuan_kg=float(m.berat_acuan_kg or 0),
            nomor_acuan=m.nomor_acuan,
        )
        for m in muatan
    ]


def _bermuatan_dan_kosong(
    arah: str, t1: float | None, t2: float | None
) -> tuple[float | None, float | None]:
    """Mana dari kedua angka yang bermuatan, menurut arah barang.

    Masuk: truk datang penuh, pulang kosong. Transfer internal dan retur dari
    pelanggan sama — armada datang bermuatan dan ditimbang ulang setelah
    dibongkar. Yang terbalik hanya yang berangkat bermuatan: pengiriman dan
    retur ke supplier.
    """
    if not logic.timbang_pertama_bermuatan(arah):
        return t2, t1
    return t1, t2


def _terapkan_hasil(trx: TimbanganTransaksi, hasil: logic.Hasil) -> None:
    trx.netto_timbangan_kg = hasil.netto_timbangan_kg
    trx.jumlah_karung = hasil.jumlah_karung
    trx.total_tara_kg = hasil.total_tara_kg
    trx.berat_barang_kg = hasil.berat_barang_kg
    trx.berat_acuan_kg = hasil.berat_acuan_kg
    trx.selisih_kg = hasil.selisih_kg
    # Dijepit ke rentang yang MUAT di kolomnya — lihat `jepit_persen`.
    # Tanpa ini, nota "8" untuk muatan 10 ton menggagalkan seluruh
    # penimbangan, dan truknya sudah di jembatan.
    trx.selisih_persen = jepit_persen(hasil.selisih_persen)
    trx.batas_bawah_kg = hasil.batas_bawah_kg
    trx.batas_atas_kg = hasil.batas_atas_kg
    trx.status_kontrol = hasil.status
    trx.keterangan = hasil.keterangan


def _kosongkan_hasil(trx: TimbanganTransaksi) -> None:
    trx.netto_timbangan_kg = None
    trx.berat_barang_kg = None
    trx.selisih_kg = 0
    trx.selisih_persen = 0
    trx.batas_bawah_kg = None
    trx.batas_atas_kg = None
    trx.status_kontrol = None
    trx.keterangan = None


async def _pasang_muatan(
    db: AsyncSession, trx: TimbanganTransaksi, muatan: list[InputMuatan]
) -> None:
    """Ganti seluruh baris muatan. Bentuk data sama untuk masuk & keluar."""
    # Koleksi dimuat lebih dulu: di SQLAlchemy async, menyentuh relasi yang
    # belum termuat memicu I/O di tempat yang tidak mengizinkannya.
    await db.refresh(trx, ["muatan"])
    baris_baru = []
    for urut, m in enumerate(muatan, start=1):
        baris_baru.append(TimbanganMuatan(
            urutan=urut,
            jenis_kode=m.jenis_kode,
            nomor_acuan=(m.nomor_acuan or None),
            jumlah_karung=int(m.jumlah_karung or 0),
            tara_per_karung_kg=(0 if trx.arah in (logic.RETUR_MASUK, logic.RETUR_KELUAR)
                               else float(m.tara_per_karung_kg or 0)),
            berat_acuan_kg=float(m.berat_acuan_kg or 0),
            tara_standar_id=m.tara_standar_id,
            catatan=m.catatan,
            kualitas_id=m.kualitas_id,
            merek_produk_id=m.merek_produk_id,
            packaging_material_id=m.packaging_material_id,
            package_size_id=m.package_size_id,
        ))
    # Penggantian di tempat: baris lama terhapus lewat cascade delete-orphan.
    trx.muatan[:] = baris_baru
    await db.flush()


#: Awalan nomor tiket menurut arah barang.
#:
#: Sampai 4 September 2026 seluruh tiket berawalan TRX-, sehingga selembar
#: bukti di tangan tidak memberitahu apa pun tentang peristiwanya — orang
#: harus membuka sistem hanya untuk tahu apakah yang dipegangnya pembelian,
#: pengiriman, atau retur. Awalan per arah mengembalikan keterangan itu ke
#: kertasnya sendiri.
#:
#: RTP/RTS memakai lawan transaksinya (retur Pelanggan / retur Supplier),
#: bukan arah geraknya, karena "retur masuk" dan "retur keluar" terbaca mirip
#: pada kertas termal yang tercetak pucat.
#:
#: Tiket lama TIDAK diubah. Nomor yang sudah tercetak di bukti NCR dan sudah
#: dirujuk nota tidak boleh berpindah hanya karena penomorannya diperbaiki.
AWALAN_KODE: dict[str, str] = {
    logic.MASUK: "MSK",
    logic.KELUAR: "KLR",
    logic.BEBAS: "BBS",
    logic.TRANSFER: "TRF",
    logic.RETUR_MASUK: "RTP",
    logic.RETUR_KELUAR: "RTS",
}
#: Dipakai bila arahnya tidak dikenal — mempertahankan awalan lama daripada
#: membuat tiket tanpa awalan sama sekali.
AWALAN_BAWAAN = "TRX"


async def kode_baru(db: AsyncSession, akun: TimbanganAkun, arah: str) -> str:
    """Bentuk nomor transaksi: <awalan>-<tanggal>-<perangkat>-<urutan>.

    Perangkat ikut masuk ke nomor supaya dua pos yang sedang tanpa jaringan
    tidak bisa membuat nomor yang sama. Urutannya dihitung per perangkat per
    hari — bukan berurut global — justru agar tidak butuh server untuk menomori.

    Urutan juga berjalan sendiri-sendiri per awalan, jadi MSK-…-001 dan
    KLR-…-001 bisa ada pada hari yang sama. Itu bukan tabrakan: keduanya
    nomor yang berbeda, dan menomori berurut lintas arah justru akan membuat
    urutan barang masuk terlihat bolong-bolong.
    """
    perangkat = (akun.perangkat_kode or "P0")[:8].upper()
    hari = sekarang().date()
    awalan = f"{AWALAN_KODE.get(arah, AWALAN_BAWAAN)}-{hari:%Y%m%d}-{perangkat}-"

    terpakai = set((await db.execute(
        select(TimbanganTransaksi.kode).where(
            TimbanganTransaksi.kode.like(awalan + "%")
        )
    )).scalars())

    urut = len(terpakai) + 1
    while f"{awalan}{urut:03d}" in terpakai:
        urut += 1
    return f"{awalan}{urut:03d}"


async def alokasi_nomor(db: AsyncSession, akun: TimbanganAkun, arah: str) -> str:
    """Terbitkan nomor tiket — atomik, saat MENYIMPAN.

    Satu perintah `INSERT … ON CONFLICT DO UPDATE … RETURNING`, jadi dua
    penyimpanan berbarengan tak mungkin mendapat angka yang sama, bahkan dari
    dua proses yang berbeda. `kode_baru` yang lama menghitung
    `count(*) + 1` saat formulir DIBUKA; dua layar yang terbuka bersamaan
    memegang angka yang sama, dan tiket yang dibatalkan membuat nomor
    tertinggi diterbitkan ulang.

    Penghitungnya hanya bertambah. Nomor yang sudah diterbitkan tak pernah
    diterbitkan lagi meski tiketnya kemudian dibatalkan: nomor yang muncul dua
    kali di buku dan di struk lebih membingungkan daripada nomor yang melompat.
    """
    perangkat = (akun.perangkat_kode or "P0")[:8].upper()
    hari = sekarang().date()
    awalan_kode = AWALAN_KODE.get(arah, AWALAN_BAWAAN)

    # Dialeknya dibedakan karena hanya itu yang berbeda: keduanya punya
    # `ON CONFLICT DO UPDATE`, dengan modul insert masing-masing.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert

    perintah = _insert(TimbanganNomor).values(
        awalan=awalan_kode, tanggal=hari, perangkat=perangkat, n=1
    )
    perintah = perintah.on_conflict_do_update(
        index_elements=["awalan", "tanggal", "perangkat"],
        set_={"n": TimbanganNomor.n + 1},
    ).returning(TimbanganNomor.n)
    urut = (await db.execute(perintah)).scalar_one()

    # ── Pagar: penghitung yang TERTINGGAL dari kenyataan ───────────────
    #
    # Penghitung bisa berada di belakang nomor yang sudah terpakai — ia baru
    # dibuat di tengah hari yang sudah berjalan (persis yang terjadi saat
    # penghitung ini diperkenalkan), atau basis data dipulihkan dari salinan.
    #
    # Akibatnya nomor yang diterbitkan sudah dimiliki tiket lain, penyimpanan
    # gagal di batas unik, dan petugas hanya melihat "Internal server error".
    # Yang membuatnya berbahaya bukan tabrakannya, melainkan bahwa ia TIDAK
    # SEMBUH SENDIRI: kenaikan penghitung ikut dibatalkan bersama transaksi
    # yang gagal, sehingga percobaan berikutnya mengambil angka yang sama
    # persis. Di produksi 11 September 2026 satu petugas karenanya tak bisa
    # menyimpan apa pun selama hampir empat jam.
    #
    # Satu kueri beralas indeks, dan ia menegakkan janji modul ini sekaligus:
    # nomor hanya boleh MAJU, tak pernah mundur ke celah yang tertinggal.
    tertinggi = (await db.execute(
        select(func.max(TimbanganTransaksi.kode)).where(
            TimbanganTransaksi.kode.like(
                f"{awalan_kode}-{hari:%Y%m%d}-{perangkat}-%"
            )
        )
    )).scalar()
    if tertinggi:
        try:
            # Angkanya berlapis nol dengan lebar tetap, jadi urutan abjad
            # sama dengan urutan angka.
            terpakai = int(str(tertinggi).rsplit("-", 1)[1])
        except (IndexError, ValueError):
            terpakai = 0
        if terpakai >= urut:
            urut = terpakai + 1
            # Penghitung ikut dilompatkan, kalau tidak pemeriksaan ini
            # terulang pada tiap penyimpanan berikutnya selamanya.
            await db.execute(
                update(TimbanganNomor)
                .where(
                    TimbanganNomor.awalan == awalan_kode,
                    TimbanganNomor.tanggal == hari,
                    TimbanganNomor.perangkat == perangkat,
                )
                .values(n=urut)
            )

    return f"{awalan_kode}-{hari:%Y%m%d}-{perangkat}-{urut:03d}"


#: Kolom yang menentukan "apakah kiriman ulang ini isinya SAMA".
#:
#: Sengaja hanya yang diketik orang. Waktu kirim, petugas, dan cap sistem
#: memang berubah tiap kiriman ulang — memasukkannya berarti tiap kirim ulang
#: dianggap berbeda, lalu ditolak, dan antrean luring macet selamanya.
_ISI_TIMBANG1 = ("arah", "jenis_kode", "cara_timbang", "nomor_polisi",
                 "nama_sopir", "pihak_nama", "timbang1_kg")


def _isi_berbeda(trx: TimbanganTransaksi, data: InputTimbang) -> str | None:
    """Sebut kolom pertama yang berbeda, atau None bila kiriman ulang sejati."""
    diminta = {
        "arah": data.arah,
        "jenis_kode": data.jenis_kode,
        "cara_timbang": data.cara_timbang,
        "nomor_polisi": normalisasi_nopol(data.nomor_polisi),
        "nama_sopir": data.nama_sopir,
        "pihak_nama": data.pihak_nama,
        "timbang1_kg": float(data.berat_kg),
    }
    for kolom in _ISI_TIMBANG1:
        ada = getattr(trx, kolom)
        minta = diminta[kolom]
        if kolom == "timbang1_kg":
            # Pada PARTAI, `timbang1_kg` adalah JUMLAH seluruh baris — ia
            # memang berubah tiap barang susulan naik timbangan.
            # Membandingkannya dengan angka di formulir awal akan menuduh
            # kiriman ulang yang sah sebagai "dua penimbangan berbeda", dan
            # tiket yang sudah berisi empat karung jadi tak bisa disentuh
            # sama sekali.
            if trx.cara_timbang == CARA_PARTAI:
                continue
            if ada is not None and abs(float(ada) - float(minta)) > 1e-6:
                return (f"berat timbang ({fmt.kg(ada)} ≠ {fmt.kg(minta)})")
            continue
        if (ada or None) != (minta or None):
            return f"{kolom} ({ada or '-'} ≠ {minta or '-'})"
    return None


async def _oleh_siapa(db: AsyncSession, trx: TimbanganTransaksi) -> str:
    """" oleh Budi pukul 14:05" — atau kosong bila tak terlacak.

    Petugas kedua yang kirimannya ditolak perlu tahu SIAPA yang sudah
    menyelesaikannya, supaya ia bisa bertanya alih-alih mengetik ulang angka
    yang sama berkali-kali. Namanya diambil lewat kueri, bukan lewat relasi:
    `TimbanganTransaksi` sengaja tak memuat relasi ke petugas, dan menambah
    satu hanya demi kalimat galat berarti tiap pembacaan tiket ikut menariknya.
    """
    pid = trx.timbang2_petugas_id or trx.timbang1_petugas_id
    nama = None
    if pid:
        nama = (await db.execute(
            select(TimbanganAkun.nama).where(TimbanganAkun.id == pid)
        )).scalars().first()
    jam = trx.timbang2_waktu or trx.timbang1_waktu
    bagian = ""
    if nama:
        bagian += f" oleh {nama}"
    if jam:
        bagian += f" pukul {jam:%H:%M}"
    return bagian


async def ambil_kunci(db: AsyncSession, kunci: str) -> TimbanganTransaksi | None:
    return (await db.execute(
        select(TimbanganTransaksi).where(TimbanganTransaksi.kunci_kiriman == kunci)
    )).scalars().first()


async def ambil_kode(db: AsyncSession, kode: str) -> TimbanganTransaksi | None:
    """Baca tiket untuk DILIHAT. Yang hendak mengubahnya pakai yang terkunci."""
    return (await db.execute(
        select(TimbanganTransaksi).where(TimbanganTransaksi.kode == kode)
    )).scalars().first()


async def ambil_kode_terkunci(db: AsyncSession, kode: str) -> TimbanganTransaksi | None:
    """Baca tiket untuk DIUBAH — barisnya dikunci sampai transaksi selesai.

    Tak ada satu pun `FOR UPDATE` di seluruh layanan ini sampai 11 September
    2026, dan akibatnya terbukti: satu baris berisi timbang-1 15.500, bruto
    15.000, dan netto 10.000 sekaligus — tiga angka yang tak mungkin ada
    bersamaan. Dua petugas menghitung ulang dari salinan yang berbeda-beda
    umurnya, lalu masing-masing menulis hasilnya sendiri.

    Kunci menyelesaikan yang BERSAMAAN. Yang berselang — formulir dibuka
    sebelum orang lain menyimpan — dijaga `pastikan_versi`, karena kunci tak
    bisa memegang baris selama orang mengetik.
    """
    return (await db.execute(
        select(TimbanganTransaksi).where(TimbanganTransaksi.kode == kode)
        .with_for_update()
    )).scalars().first()


def versi_tiket(trx: TimbanganTransaksi) -> str:
    """Penanda versi yang dibawa borang — berubah tiap kali tiketnya berubah.

    Dibentuk dari `updated_at` dan `jumlah_revisi`, bukan kolom versi baru:
    keduanya sudah ada, sudah dipelihara, dan tabel ini DIBACA PRODUKSI —
    menambah kolom di sini menuntut kesepakatan dua repo.
    """
    cap = trx.updated_at.isoformat() if trx.updated_at else "0"
    return f"{trx.jumlah_revisi or 0}:{cap}"


def pastikan_versi(trx: TimbanganTransaksi, versi: str | None) -> None:
    """Tolak simpan dari formulir yang sudah basi.

    Tanpa ini, formulir yang dibuka sebelum orang lain mengoreksi akan
    MENIMPA koreksi itu saat disimpan — diam-diam, dan yang kehilangan tak
    pernah tahu. Yang ditolak menyebut siapa dan pukul berapa, supaya
    petugasnya bisa bertanya alih-alih menebak.

    Versi kosong dibiarkan lewat: kiriman dari antrean luring dibuat sebelum
    penanda ini ada, dan menolaknya berarti menahan pekerjaan yang sah.
    """
    if not versi:
        return
    if versi != versi_tiket(trx):
        jam = trx.updated_at.strftime("%H:%M") if trx.updated_at else "?"
        raise LayananError(
            f"Tiket ini sudah diubah orang lain pukul {jam} — muat ulang "
            "halamannya dulu supaya perubahannya tidak tertimpa."
        )


# ═══════════════════════════ Jejak audit ═══════════════════════════

@dataclass
class FilterAudit:
    """Saringan halaman jejak audit."""

    dari: date | None = None
    sampai: date | None = None
    aksi: str | None = None
    akun_id: int | None = None
    cari: str | None = None


def _batas_hari(f: FilterAudit) -> tuple[datetime | None, datetime | None]:
    """Tanggal → rentang waktu berzona.

    `waktu` adalah cap waktu, bukan tanggal. Membandingkannya langsung dengan
    tanggal akan memotong hari di tengah menurut UTC — baris pukul 07.00 WIB
    akan tampil pada hari sebelumnya.
    """
    zona = ZoneInfo(settings.app_timezone)
    awal = datetime.combine(f.dari, time.min, tzinfo=zona) if f.dari else None
    akhir = (
        datetime.combine(f.sampai, time.max, tzinfo=zona) if f.sampai else None
    )
    return awal, akhir


def _terapkan_filter_audit(q, f: FilterAudit):
    awal, akhir = _batas_hari(f)
    if awal is not None:
        q = q.where(TimbanganAudit.waktu >= awal)
    if akhir is not None:
        q = q.where(TimbanganAudit.waktu <= akhir)
    if f.aksi:
        q = q.where(TimbanganAudit.aksi == f.aksi)
    if f.akun_id:
        q = q.where(TimbanganAudit.akun_id == f.akun_id)
    if f.cari:
        pola = f"%{f.cari.strip()}%"
        q = q.where(or_(
            TimbanganAudit.entitas_id.ilike(pola),
            TimbanganAudit.ringkasan.ilike(pola),
            TimbanganAudit.akun_nama.ilike(pola),
        ))
    return q


async def daftar_audit(
    db: AsyncSession, f: FilterAudit, *, batas: int = 50, offset: int = 0
) -> list[TimbanganAudit]:
    """Baris audit terbaru lebih dulu."""
    q = _terapkan_filter_audit(select(TimbanganAudit), f)
    q = q.order_by(TimbanganAudit.waktu.desc(), TimbanganAudit.id.desc())
    return list((await db.execute(q.limit(batas).offset(offset))).scalars())


async def hitung_audit(db: AsyncSession, f: FilterAudit) -> int:
    q = _terapkan_filter_audit(
        select(func.count(TimbanganAudit.id)).select_from(TimbanganAudit), f
    )
    return (await db.execute(q)).scalar_one()


async def daftar_akun(db: AsyncSession) -> list[TimbanganAkun]:
    """Semua akun, termasuk yang nonaktif — dipakai menyaring jejak audit.

    Yang nonaktif justru sering yang dicari: orang yang sudah berhenti tetapi
    pekerjaannya masih perlu ditelusuri.
    """
    return list((await db.execute(
        select(TimbanganAkun).order_by(TimbanganAkun.nama)
    )).scalars())


async def daftar_aksi_audit(db: AsyncSession) -> list[str]:
    """Jenis aksi yang benar-benar pernah tercatat.

    Dibaca dari data, bukan daftar yang ditulis tangan — aksi baru yang
    ditambahkan kelak ikut muncul di saringan tanpa ada yang perlu ingat
    memperbaruinya di sini.
    """
    return sorted(
        (await db.execute(select(TimbanganAudit.aksi).distinct())).scalars()
    )


#: Arah yang WAJIB menyebut nomor polisi. Keputusan Direksi 31 Agustus 2026.
#: Barang masuk dan barang keluar selalu melibatkan pihak luar, sehingga
#: catatannya harus bisa menunjuk kendaraan tertentu bila kelak ada sengketa.
#: Jasa timbang dan transfer internal dibiarkan boleh kosong. Retur ikut
#: wajib: ia justru peristiwa yang paling mungkin berujung sengketa.
ARAH_WAJIB_NOPOL = (
    logic.MASUK, logic.KELUAR, logic.RETUR_MASUK, logic.RETUR_KELUAR,
)


def _wajib_pihak(arah: str, *, punya_id: bool, pihak_nama: str | None,
                 jasa: bool = False) -> None:
    """Setiap transaksi harus menyebut lawannya.

    Pemasok: dari daftar ATAU diketik bebas untuk yang belum terdaftar.
    Pelanggan: HANYA dari daftar Kledo — permintaan pemilik 4 Oktober 2026,
    "nama pelanggan tidak boleh diketik bebas, harus yang dari kontak
    kledo". Dulu keduanya sama-sama punya pintu ketik-bebas karena
    sinkronisasi Kledo cuma berjalan mingguan; sejak tombol "Perbarui
    Kontak" ada (app/services/kledo_sinkron.py di produksi), pelanggan baru
    tak lagi harus menunggu jadwal — Admin tinggal menekannya sebelum truk
    datang. Pemasok TIDAK ikut berubah: permintaannya hanya menyebut
    pelanggan.

    Dipusatkan lewat `pihak_untuk` (bukan membandingkan `arah` sendiri):
    satu tempat yang tahu "pelanggan atau pemasok", sama seperti alasan
    `pihak_untuk` sendiri dipusatkan — lihat docstring-nya.

    "Salah satu dari dua" tidak bisa dinyatakan HTML, jadi pagarnya memang
    harus di sini — bukan sekadar `required` di isian.
    """
    # Pada tiket jasa yang ditagih bukan "pemasok" melainkan PEMILIK barangnya,
    # dan sebutan yang salah di sini menyuruh petugas mencari nama di daftar
    # yang keliru.
    sebutan = ("Pemilik barang" if jasa
               else logic.PIHAK_LABEL.get(arah, "Nama pihak"))
    pihak = pihak_untuk(arah, jasa=jasa)
    if pihak is not None and pihak[0] is Pelanggan:
        if punya_id:
            return
        raise LayananError(
            f"{sebutan} wajib dipilih dari daftar Kledo. Belum ada di "
            "daftar? Minta Admin menekan “Perbarui Kontak” di "
            "Pengaturan, lalu coba lagi."
        )
    if punya_id or (pihak_nama or "").strip():
        return
    raise LayananError(
        f"{sebutan} wajib diisi — pilih dari daftar, atau ketik namanya "
        "bila belum terdaftar."
    )


async def _periksa_jasa(
    db: AsyncSession, *, aturan: logic.AturanJenis, data: InputTimbang
) -> None:
    """Dua hal yang tak boleh lolos pada tiket jasa.

    ⚠ PENJAGA, BUKAN SARINGAN TAMPILAN. Beranda sudah hanya menawarkan
    komoditas yang `boleh_jasa`, dan borang hanya menawarkan pesanan milik
    pelanggan yang dipilih — tetapi daftar yang menyaring tanpa penjaga di
    belakangnya hanya menyaring yang patuh. Halaman di ponsel petugas berumur
    panjang (antrean luring menyimpannya), jadi kiriman dari halaman lama adalah
    keadaan biasa di sini, bukan serangan.

      1. **Komoditasnya memang dibuka untuk jasa.** Kalau tidak, produksi akan
         menolaknya saat diterima — dan penolakan di sana datang berjam-jam
         kemudian, saat truknya sudah pulang dan barangnya sudah di halaman.
      2. **Pesanan yang ditunjuk milik pelanggan ITU, dan masih berjalan.**
         Salah pesanan berarti barang diserahkan ke orang yang salah, dan itu
         tak bisa dibetulkan dengan pembukuan.
    """
    if not aturan.boleh_jasa:
        raise LayananError(
            f"{aturan.nama} belum dibuka untuk jasa. Yang bisa dijasakan: "
            + (", ".join(j.nama for j in await daftar_jenis_jasa(db))
               or "belum ada satu pun")
            + ". Buka di master komoditas bila memang sudah boleh."
        )
    if data.jasa_id is None:
        return
    sah = await pesanan_jasa_berjalan(db, data.pelanggan_id)
    if not any(p.id == data.jasa_id for p in sah):
        raise LayananError(
            "Pesanan jasa yang dipilih bukan milik pelanggan ini, atau sudah "
            "tidak berjalan. Muat ulang halamannya, lalu pilih lagi — atau "
            "pilih 'pesanan baru'."
        )


def _wajib_sopir(nama_sopir: str | None, *, cara: str = CARA_DUA_KALI) -> None:
    """Nama sopir wajib, apa pun arah barangnya.

    Sopir adalah satu-satunya orang yang benar-benar hadir di jembatan saat
    angka itu dibaca. Tanpa namanya, sengketa tentang muatan tidak punya
    saksi.

    PARTAI KECIL dikecualikan — dan bukan karena syaratnya dilonggarkan,
    melainkan karena syaratnya sudah terpenuhi orang lain: yang datang membawa
    beberapa karung adalah petani atau pedagangnya sendiri, dan namanya WAJIB
    terisi sebagai pihak. Menuntut "nama sopir" pada orang yang datang naik
    motor hanya memaksa petugas mengarang isian.
    """
    if cara == CARA_PARTAI:
        return
    if not (nama_sopir or "").strip():
        raise LayananError("Nama sopir wajib diisi.")


def _wajib_nopol(
    arah: str, nomor_polisi: str | None, *, cara: str = CARA_DUA_KALI
) -> None:
    """Nomor polisi wajib pada barang masuk & keluar — kecuali partai kecil,
    yang sering datang tanpa kendaraan bernomor sama sekali."""
    if cara == CARA_PARTAI:
        return
    if arah in ARAH_WAJIB_NOPOL and not (nomor_polisi or "").strip():
        raise LayananError(
            "Nomor polisi wajib diisi untuk barang masuk, barang keluar, "
            "dan retur."
        )


async def nama_pihak(db: AsyncSession, trx: TimbanganTransaksi) -> str | None:
    """Nama lawan transaksi dari tabel mana pun yang terisi."""
    for model, kolom_trx, kolom_nama in PIHAK_ARAH.values():
        pid = getattr(trx, kolom_trx)
        if pid:
            baris = await db.get(model, pid)
            if baris is not None:
                return getattr(baris, kolom_nama)
    return None


def _pasang_pihak(
    trx: TimbanganTransaksi, arah: str, pihak_id: int | None, *, jasa: bool = False
) -> None:
    """Taruh id lawan transaksi pada kolom yang sesuai arahnya, kosongkan yang lain.

    Mengosongkan yang lain bukan kerapian: kalau keduanya terisi, laporan yang
    menggabungkan nama dari dua tabel akan menampilkan salah satu secara acak,
    dan tidak ada yang bisa menebak mana yang benar.

    Pemetaan arah → kolom (dan pembalikannya untuk jasa) dijawab
    `pihak_untuk()`, bukan disusun ulang di sini — lihat catatannya di sana.
    """
    trx.supplier_id = None
    trx.pelanggan_id = None
    if not pihak_id:
        return
    pihak = pihak_untuk(arah, jasa=jasa)
    if pihak is not None:
        setattr(trx, pihak[1], pihak_id)



# ══════════════════════ Batas isian (temuan QA T-09) ══════════════════════
#
# Salah ketik yang WAJAR jadi galat 500, dan timbang KEDUA hilang saat truk
# menunggu di jembatan: nomor acuan 51 karakter, plat 24 huruf, jumlah karung
# tiga miliar. Semuanya menembus lapisan aplikasi tanpa keluhan lalu ditolak
# Postgres — dan penolakan Postgres berupa galat 500, bukan kalimat yang bisa
# dibaca petugas.
#
# Suite uji berjalan di SQLite, yang tak menegakkan panjang VARCHAR maupun
# NUMERIC. Jadi tak satu pun tertangkap sampai ia tertangkap di pos timbang.
#
# Angkanya diambil dari KOLOMNYA, bukan dikarang: yang dijaga di sini persis
# batas yang akan ditolak basis data.
BATAS_NOPOL = 20          # timbangan_transaksi.nomor_polisi String(20)
BATAS_NOMOR_ACUAN = 50    # timbangan_muatan.nomor_acuan String(50)
BATAS_NAMA = 100          # nama sopir / pihak
BATAS_KARUNG = 100_000    # satu truk tak memuat lebih dari ini
BATAS_PERSEN = 9999.0     # selisih_persen NUMERIC(9,4) → maksimal 99999,9999


def _batas_teks(nilai: str | None, nama: str, batas: int) -> str | None:
    """Tolak isian yang takkan muat di kolomnya, dengan menyebut kolomnya."""
    if nilai is None:
        return None
    teks = str(nilai).strip()
    if len(teks) > batas:
        raise LayananError(
            f"{nama} terlalu panjang ({len(teks)} huruf, maksimal {batas}). "
            "Periksa lagi — biasanya ada yang tersalin dua kali."
        )
    return teks or None


def _batas_angka(nilai, nama: str, *, maksimum: float, minimum: float = 0.0):
    """Tolak angka di luar akal — termasuk NaN dan tak hingga."""
    if nilai is None:
        return nilai
    n = float(nilai)
    if not math.isfinite(n):
        raise LayananError(f"{nama} bukan angka yang bisa dipakai.")
    if n < minimum:
        raise LayananError(f"{nama} tidak boleh kurang dari {minimum:g}.")
    if n > maksimum:
        raise LayananError(
            f"{nama} di luar akal ({n:,.0f}, maksimal {maksimum:,.0f}). "
            "Periksa lagi angkanya.".replace(",", ".")
        )
    return n


def _periksa_isian(data: "InputTimbang") -> None:
    """Seluruh batas diperiksa SEKALIGUS, sebelum satu baris pun ditulis.

    Diperiksa di lapisan layanan, bukan cuma di borang: borang punya
    `maxlength`, tetapi kiriman dari antrean luring dan dari skrip tak lewat
    borang sama sekali.
    """
    data.nomor_polisi = _batas_teks(data.nomor_polisi, "Nomor polisi", BATAS_NOPOL)
    data.nama_sopir = _batas_teks(data.nama_sopir, "Nama sopir", BATAS_NAMA)
    data.pihak_nama = _batas_teks(data.pihak_nama, "Nama pihak", BATAS_NAMA)
    _batas_angka(data.berat_kg, "Berat timbang", maksimum=1_000_000)
    _batas_angka(data.tara_lain_kg, "Tara lain", maksimum=1_000_000)
    for m in (data.muatan or []):
        m.nomor_acuan = _batas_teks(m.nomor_acuan, "Nomor acuan", BATAS_NOMOR_ACUAN)
        _batas_angka(m.jumlah_karung, "Jumlah karung", maksimum=BATAS_KARUNG)
        _batas_angka(m.tara_per_karung_kg, "Tara per karung", maksimum=1_000)
        _batas_angka(m.berat_acuan_kg, "Berat acuan", maksimum=1_000_000)


def jepit_persen(nilai: float | None) -> float:
    """Jepit selisih persen ke rentang yang MUAT di kolomnya.

    Nota "8" untuk muatan 10 ton menghasilkan selisih 124.587%, dan kolomnya
    NUMERIC(9,4). Angka itu menolak disimpan, jadi SELURUH penimbangan gagal —
    padahal yang salah cuma satu angka yang bisa dikoreksi menit berikutnya.
    Truknya sudah di jembatan.

    Dijepit, bukan dibuang: selisih 9999% tetap terbaca sebagai "jauh sekali
    melenceng", dan itulah yang perlu diketahui orang. Angka nota aslinya
    tetap tersimpan apa adanya, jadi tak ada informasi yang hilang.
    """
    if nilai is None or not math.isfinite(float(nilai)):
        return 0.0
    return max(-BATAS_PERSEN, min(BATAS_PERSEN, float(nilai)))

#: Toleransi jam perangkat yang tak persis sama dengan jam server. Ponsel
#: petugas sering meleset satu-dua menit, dan menolak selisih semenit hanya
#: membuat orang berhenti mengisi jamnya sama sekali.
_TOLERANSI_DEPAN = timedelta(minutes=10)


async def pastikan_waktu_wajar(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    waktu: datetime | None,
    sesudah: datetime | None = None,
    label: str = "Jam timbang",
    kode: str | None = None,
    ip: str | None = None,
) -> None:
    """Batasi jam timbang yang diketik sendiri oleh petugas.

    Isian jam ada supaya pencatatan yang terlambat tetap jujur — petugas yang
    baru sempat mengetik satu jam kemudian menulis jam sebenarnya. Tanpa
    batas, isian yang sama juga memindahkan tiket ke periode yang sudah
    ditutup: timbang kedua bertanggal Maret untuk tiket September, di luar
    jendela tujuh hari yang dibaca produksi, sehingga rekap dua sistem
    berhenti cocok tanpa ada yang tahu sebabnya. Temuan QA T-16.

    Tiga pagar, dan ketiganya menjawab hal berbeda:

      · tidak di MASA DEPAN — jam yang belum terjadi bukan pencatatan
        terlambat, melainkan salah ketik atau angan-angan;
      · tidak SEBELUM timbang pertama — truk tak bisa keluar sebelum masuk;
      · tidak lebih mundur dari batas yang disetel — di luar itu Admin yang
        memutuskan, dan keputusannya bernama di audit.
    """
    if waktu is None:
        return
    waktu = berzona(waktu)
    if waktu is None:
        return
    kini = sekarang()
    if waktu > kini + _TOLERANSI_DEPAN:
        raise LayananError(
            f"{label} tidak boleh di masa depan."
        )
    sesudah = berzona(sesudah)
    if sesudah is not None and waktu < sesudah:
        raise LayananError(
            f"{label} tidak boleh sebelum timbang pertama "
            f"({berzona(sesudah):%d-%m-%Y %H:%M})."
        )

    batas = float((await setelan.semua(db))["jam_mundur_maksimum"])
    if kini - waktu <= timedelta(hours=batas):
        return
    if not akun.is_admin:
        raise LayananError(
            f"{label} lebih dari {batas:g} jam ke belakang. Minta Admin yang "
            "mengisinya — memundurkan tanggal memindahkan tiket ke periode "
            "yang mungkin sudah ditutup."
        )
    # Admin boleh, tetapi tidak diam-diam. Yang dijaga bukan wewenangnya
    # melainkan kemungkinan menelusurinya kemudian.
    await catat_audit(
        db, akun=akun, aksi="WAKTU_MUNDUR", entitas="transaksi",
        entitas_id=kode or "-",
        ringkasan=f"{label} dimundurkan ke {waktu:%d-%m-%Y %H:%M} "
                  f"(batas {batas:g} jam)", ip=ip,
    )


async def simpan_timbang_pertama(
    db: AsyncSession, *, akun: TimbanganAkun, data: InputTimbang, ip: str | None = None
) -> TimbanganTransaksi:
    """Timbang pertama → tiket terbuka (atau langsung selesai bila SEKALI).

    Idempoten terhadap `kode`: mengirim ulang kiriman yang sama dari antrean
    offline memperbarui baris yang sama.
    """
    if data.berat_kg <= 0:
        raise LayananError("Berat timbang harus lebih dari 0 kg.")
    _periksa_isian(data)
    # Diperiksa SEBELUM baris tiketnya ada sama sekali. Penjaga ini membaca
    # setelan, dan pembacaan itu membilas sesi — baris tiket yang setengah
    # terisi akan ikut terbilas dan ditolak Postgres, bukan ditolak dengan
    # kalimat yang bisa dibaca petugas.
    await pastikan_waktu_wajar(
        db, akun=akun, waktu=data.waktu_operator,
        label="Jam timbang pertama", kode=data.kode, ip=ip,
    )

    aturan = await aturan_untuk(db, data.jenis_kode)
    _wajib_nopol(aturan.arah, data.nomor_polisi, cara=data.cara_timbang)
    _wajib_pihak(
        aturan.arah,
        punya_id=bool(data.pelanggan_id if data.jasa else data.supplier_id),
        pihak_nama=data.pihak_nama,
        jasa=data.jasa,
    )
    if data.jasa:
        await _periksa_jasa(db, aturan=aturan, data=data)
    _wajib_sopir(data.nama_sopir, cara=data.cara_timbang)
    _setelan = await setelan.semua(db)
    kapasitas = _setelan["kapasitas_jembatan_kg"]
    # Diperiksa SEKARANG, bukan nanti di timbang kedua. Salah ketik yang baru
    # ketahuan setelah truk selesai bongkar sudah terlambat untuk diperbaiki.
    if data.cara_timbang == CARA_PARTAI:
        # Alatnya timbangan kecil, bukan jembatan truk.
        kecil = _setelan["kapasitas_timbangan_kecil_kg"]
        if data.berat_kg > kecil:
            raise LayananError(
                f"Melebihi kapasitas timbangan kecil ({kecil:g} kg) — "
                "periksa lagi angkanya."
            )
    elif data.berat_kg > kapasitas:
        raise LayananError(
            f"Melebihi kapasitas jembatan timbang ({kapasitas:.0f} kg) — "
            "angka ini tidak mungkin."
        )
    waktu = sekarang()
    kendaraan = await kendaraan_dari_nopol(db, data.nomor_polisi)

    # ── Siapa tiket ini: dicari lewat KUNCI, bukan lewat nomor ──
    #
    # Kunci dibuat perangkat saat formulir dibuka dan ikut di tiap kiriman
    # ulang. Nomor tidak bisa memikul tugas ini: sampai 11 September 2026
    # nomor pun dibentuk saat formulir dibuka, sehingga dua petugas yang
    # membuka layar bersamaan memegang angka yang sama.
    trx = None
    if data.kunci:
        trx = await ambil_kunci(db, data.kunci)
    if trx is None and data.kode:
        # Kiriman LAMA dari antrean luring, dibuat sebelum kunci ada. Ia
        # hanya boleh mencocokkan tiket yang memang belum berkunci; nomor yang
        # sudah dimiliki tiket berkunci lain bukan miliknya.
        lama_ = await ambil_kode(db, data.kode)
        if lama_ is not None:
            if lama_.kunci_kiriman and lama_.kunci_kiriman != data.kunci:
                raise LayananError(
                    f"Nomor {data.kode} sudah dipakai tiket lain "
                    f"({lama_.nomor_polisi or '-'}, "
                    f"{fmt.kg(lama_.timbang1_kg or 0)}). "
                    "Simpan ulang tanpa mengisi nomor — server yang "
                    "menerbitkannya."
                )
            trx = lama_

    baru = trx is None
    if trx is None:
        # Nomornya diterbitkan DI SINI, atomik, bukan saat formulir dibuka.
        #
        # Nomor yang DIBAWA kiriman tetap dihormati bila belum dimiliki siapa
        # pun — itu kiriman luring yang dibuat sebelum pembaruan ini, dan
        # nomornya sudah tercetak di struk yang dipegang sopir. Yang sudah
        # dimiliki tiket lain ditolak di atas, bukan diam-diam ditimpa.
        trx = TimbanganTransaksi(
            kode=data.kode or await alokasi_nomor(db, akun, data.arah),
            kunci_kiriman=data.kunci,
        )
        db.add(trx)
    elif trx.status_transaksi == TRX_VOID:
        raise LayananError("Transaksi ini sudah dibatalkan.")
    else:
        # ── Kiriman ulang: isi sama lolos, isi berbeda DITOLAK ──
        #
        # Dulu tiket yang sudah selesai langsung dikembalikan apa adanya, dan
        # layar berkata "tersimpan" — padahal angka yang baru diketik dibuang
        # tanpa satu pun jejak audit. Yang mengetiknya tak punya cara tahu.
        beda = _isi_berbeda(trx, data)
        if beda and trx.selesai:
            raise LayananError(
                f"Tiket {trx.kode} sudah diselesaikan"
                f"{await _oleh_siapa(db, trx)}. Yang tersimpan: {beda}. "
                "Pakai Koreksi bila angkanya memang harus diubah."
            )
        if beda and data.kunci and trx.kunci_kiriman == data.kunci:
            raise LayananError(
                f"Kiriman ini sepertinya dua penimbangan yang berbeda dengan "
                f"kunci yang sama — {beda}. Buka formulir baru untuk truk "
                "yang kedua."
            )
        if trx.selesai:
            # Kiriman ulang sejati atas transaksi yang sudah tuntas — abaikan,
            # jangan mundurkan statusnya.
            return trx

    trx.arah = data.arah
    trx.jenis_kode = data.jenis_kode
    trx.cara_timbang = data.cara_timbang
    trx.aturan_snapshot = json.dumps(
        aturan.__dict__, ensure_ascii=False, default=str
    )
    # Barang masuk mengisi supplier_id, pengiriman mengisi pelanggan_id, dan
    # tidak pernah keduanya. `data.supplier_id` membawa id dari daftar yang
    # ditawarkan layar, dan layar hanya menawarkan satu daftar per arah.
    #
    # KECUALI jasa: barangnya dititipkan, jadi lawannya pelanggan walaupun
    # arahnya MASUK. Lihat `_pasang_pihak`.
    _pasang_pihak(
        trx, data.arah,
        data.pelanggan_id if data.jasa else data.supplier_id,
        jasa=data.jasa,
    )
    # ⚠⚠ PENANDANYA SENDIRI — bukan diturunkan dari `pelanggan_id`.
    #
    # Cacat lapangan 2 Oktober 2026: pelanggan BARU yang diketik bebas (pintu
    # ketik-bebas, sah dan disengaja — lihat `_wajib_pihak`) membuat
    # `_pasang_pihak` di atas mengosongkan `pelanggan_id` juga, sebab
    # `pihak_id`-nya memang belum ada id sampai pelanggannya dibuat di
    # PRODUKSI (`purchase.find_or_create_pelanggan`, bukan di sini). Tanpa
    # baris ini, tiket itu identik bentuknya dengan pembelian biasa yang
    # pemasoknya diketik bebas — dan produksi membuat PEMASOK PALSU dari nama
    # pelanggan, persis yang dilarang keras spek.
    #
    # Dicatat apa adanya (`data.jasa`), bukan "benar" menurut penjaga lain:
    # `_periksa_jasa` sudah menolak komoditas yang belum dibuka untuk jasa,
    # jadi pada titik ini `data.jasa=True` memang sah.
    trx.jasa = data.jasa
    # Penunjuk pesanan hanya sah pada tiket jasa. Dikosongkan terang-terangan
    # untuk yang bukan: kiriman ULANG boleh mengubah tiket, dan tiket yang
    # pernah salah ditandai jasa tak boleh menyimpan penunjuk itu diam-diam.
    trx.jasa_id = data.jasa_id if data.jasa else None
    trx.pihak_nama = data.pihak_nama
    trx.kendaraan_id = kendaraan.id if kendaraan else None
    trx.nomor_polisi = normalisasi_nopol(data.nomor_polisi)
    trx.nama_sopir = data.nama_sopir
    trx.tara_lain_kg = (0 if data.arah in (logic.RETUR_MASUK, logic.RETUR_KELUAR)
                        else float(data.tara_lain_kg or 0))
    trx.catatan = data.catatan
    trx.perangkat_kode = data.perangkat_kode or akun.perangkat_kode
    trx.dibuat_offline = bool(data.dibuat_offline)
    trx.dikirim_pada = waktu

    trx.timbang1_kg = float(data.berat_kg)
    trx.timbang1_waktu = data.waktu_operator or waktu
    trx.timbang1_waktu_sistem = waktu
    trx.timbang1_petugas_id = akun.id
    trx.dibuat_oleh_id = trx.dibuat_oleh_id or akun.id
    trx.tanggal = (trx.timbang1_waktu or waktu).date()

    await db.flush()
    await _pasang_muatan(db, trx, data.muatan)

    if data.cara_timbang == CARA_PARTAI:
        # Timbang pertama SEKALIGUS baris pertama. Tiketnya tetap terbuka:
        # barang berikutnya menyusul naik timbangan, satu kode yang sama.
        #
        # Koleksinya dimuat lewat `refresh`, bukan disentuh langsung: pada
        # transaksi yang baru dibuat ia belum termuat, dan menyentuhnya di
        # jalur async memicu pemuatan malas di luar greenlet — yang berakhir
        # sebagai 500, bukan sebagai kesalahan yang bisa dibaca.
        await db.refresh(trx, ["penimbangan"])
        # ── Kiriman ULANG formulir awal tak boleh menghapus barang susulan ──
        #
        # Baris di bawah menulis ULANG seluruh daftar dari satu angka —
        # perilaku yang benar saat tiketnya baru lahir, dan merusak sesudah
        # barang susulan masuk: baris ketiga & keempat lenyap tanpa satu pun
        # pesan. Temuan QA T-10.
        if len(trx.penimbangan) > 1:
            return trx
        for lama in list(trx.penimbangan):
            trx.penimbangan.remove(lama)
        trx.penimbangan.append(TimbanganPenimbangan(
            urutan=1, berat_kg=float(data.berat_kg),
            waktu=data.waktu_operator or waktu, petugas_id=akun.id,
        ))
        trx.status_tiket = TIKET_TERBUKA
        _kosongkan_hasil(trx)
    elif data.cara_timbang == CARA_SEKALI:
        # Jasa timbang sekali: tidak ada pembanding, tidak ada kontrol.
        trx.berat_bermuatan_kg = trx.timbang1_kg
        trx.berat_kosong_kg = None
        _terapkan_hasil(trx, logic.hitung(
            aturan=aturan,
            berat_bermuatan_kg=trx.timbang1_kg,
            berat_kosong_kg=None,
            muatan=_baris_logic(trx.muatan),
            tara_lain_kg=trx.tara_lain_kg,
            kapasitas_kg=kapasitas,
        ))
        trx.status_tiket = TIKET_SELESAI
        trx.timbang2_petugas_id = akun.id
    else:
        trx.status_tiket = TIKET_TERBUKA
        _kosongkan_hasil(trx)

    await catat_audit(
        db, akun=akun, aksi="SIMPAN_TIMBANG_1" if baru else "KIRIM_ULANG_TIMBANG_1",
        entitas="transaksi", entitas_id=trx.kode,
        ringkasan=f"{trx.arah} {trx.jenis_kode} {trx.nomor_polisi or ''} "
                  f"{trx.timbang1_kg:.0f} kg".strip(),
        sesudah={"timbang1_kg": float(trx.timbang1_kg)},
        perangkat=trx.perangkat_kode, ip=ip,
    )
    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return trx


def _pastikan_partai_terbuka(trx: TimbanganTransaksi | None, kode: str) -> TimbanganTransaksi:
    if trx is None:
        raise LayananError(f"Kode timbang {kode} tidak ditemukan.")
    if trx.status_transaksi == TRX_VOID:
        raise LayananError("Transaksi ini sudah dibatalkan.")
    if not trx.partai:
        raise LayananError("Transaksi ini bukan partai kecil.")
    if trx.selesai:
        raise LayananError("Tiket ini sudah ditutup — tak bisa ditambah lagi.")
    if trx.terkunci:
        raise LayananError("Transaksi ini sudah dikunci.")
    return trx


def _jumlahkan_partai(trx: TimbanganTransaksi) -> None:
    """Salin jumlah seluruh baris ke `timbang1_kg`.

    Satu angka itulah yang dibaca laporan, bukti cetak, dan jembatan ke modul
    produksi — bentuk khusus partai kecil berhenti di layar yang mencatatnya.
    """
    for i, baris in enumerate(trx.penimbangan, start=1):
        baris.urutan = i
    trx.timbang1_kg = round(trx.total_penimbangan_kg, 3)


async def tambah_penimbangan(
    db: AsyncSession, *, akun: TimbanganAkun, kode: str,
    berat_kg: float | None = None, berat: Sequence[float] | None = None,
    catatan: str | None = None, waktu_operator: datetime | None = None,
    kunci: str | None = None,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Naikkan satu atau beberapa barang lagi ke timbangan, pada kode yang sama.

    Menerima beberapa sekaligus karena begitulah kenyataannya di pos: petugas
    menimbang lima karung berturut-turut lalu mencatatnya, bukan bolak-balik ke
    layar setiap satu karung.
    """
    sumber = list(berat) if berat is not None else ([] if berat_kg is None else [berat_kg])
    daftar = [float(b) for b in sumber if b is not None and str(b).strip() != ""]
    if not daftar:
        raise LayananError("Isi dulu berat timbangannya.")
    if any(b <= 0 for b in daftar):
        raise LayananError("Berat timbang harus lebih dari 0 kg.")

    trx = _pastikan_partai_terbuka(await ambil_kode_terkunci(db, kode), kode)

    # ── Kiriman ULANG tak menambah lagi ──
    #
    # Penambahan partai dulu tak punya penanda apa pun, jadi kiriman ulang —
    # ketukan dobel, atau antrean luring yang mengirim lagi saat sinyal
    # kembali — tak bisa dibedakan dari karung berikutnya yang kebetulan sama
    # beratnya. "+70 kg" jadi 250 kg, bukan 180. Temuan QA T-10.
    #
    # Tak berbuat apa-apa, bukan menolak: antrean luring yang ditolak akan
    # mencoba selamanya dan macet.
    if kunci:
        await db.refresh(trx, ["penimbangan"])
        if any((b.kunci_baris or "").startswith(kunci) for b in trx.penimbangan):
            return trx

    kapasitas = (await setelan.semua(db))["kapasitas_timbangan_kecil_kg"]
    lebih = [b for b in daftar if b > kapasitas]
    if lebih:
        raise LayananError(
            f"{lebih[0]:g} kg melebihi kapasitas timbangan kecil "
            f"({kapasitas:g} kg) — periksa lagi angkanya."
        )

    waktu = sekarang()
    for i, b in enumerate(daftar):
        trx.penimbangan.append(TimbanganPenimbangan(
            urutan=len(trx.penimbangan) + 1, berat_kg=b,
            waktu=waktu_operator or waktu, petugas_id=akun.id,
            catatan=(catatan or None),
            # Kunci menandai KIRIMANNYA. Baris kedua dan seterusnya dalam satu
            # kiriman diberi akhiran supaya tetap unik di kolomnya.
            kunci_baris=(f"{kunci}#{i}" if kunci else None),
        ))
    _jumlahkan_partai(trx)
    ringkas = " + ".join(f"{b:g}" for b in daftar)
    await catat_audit(
        db, akun=akun, aksi="TAMBAH_PENIMBANGAN", entitas="transaksi",
        entitas_id=trx.kode,
        ringkasan=f"+{ringkas} kg → total {trx.timbang1_kg:g} kg "
                  f"({len(trx.penimbangan)} baris)",
        sesudah={"berat_kg": daftar, "total_kg": float(trx.timbang1_kg)},
        perangkat=trx.perangkat_kode, ip=ip,
    )
    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return trx


async def hapus_penimbangan(
    db: AsyncSession, *, akun: TimbanganAkun, kode: str, urutan: int,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Buang satu baris yang salah ketik — hanya selama tiket masih terbuka.

    Sesudah tiket ditutup, koreksi menempuh jalur `koreksi_transaksi` yang
    meninggalkan jejak revisi; salah ketik di tengah penimbangan tidak perlu
    seberat itu.
    """
    trx = _pastikan_partai_terbuka(await ambil_kode(db, kode), kode)
    if len(trx.penimbangan) <= 1:
        raise LayananError(
            "Baris terakhir tak bisa dihapus — batalkan tiketnya bila memang salah."
        )
    sasaran = next((p for p in trx.penimbangan if p.urutan == int(urutan)), None)
    if sasaran is None:
        raise LayananError("Baris timbang itu tidak ada.")
    dibuang = float(sasaran.berat_kg)
    trx.penimbangan.remove(sasaran)
    _jumlahkan_partai(trx)
    await catat_audit(
        db, akun=akun, aksi="HAPUS_PENIMBANGAN", entitas="transaksi",
        entitas_id=trx.kode,
        ringkasan=f"−{dibuang:g} kg (baris {urutan}) → total {trx.timbang1_kg:g} kg",
        sebelum={"berat_kg": dibuang}, perangkat=trx.perangkat_kode, ip=ip,
    )
    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return trx


async def selesaikan_partai(
    db: AsyncSession, *, akun: TimbanganAkun, kode: str, ip: str | None = None
) -> TimbanganTransaksi:
    """Tutup tiket partai kecil: nettonya jumlah seluruh baris."""
    trx = _pastikan_partai_terbuka(await ambil_kode(db, kode), kode)
    if not trx.penimbangan:
        raise LayananError("Belum ada satu pun penimbangan.")

    aturan = await aturan_untuk(db, trx.jenis_kode)
    _jumlahkan_partai(trx)
    trx.berat_bermuatan_kg = trx.timbang1_kg
    trx.berat_kosong_kg = None
    # Kapasitas TIDAK diperiksa terhadap jumlah: tiap baris sudah diperiksa
    # sendiri saat ditimbang, dan wajar bila totalnya melampaui kapasitas
    # sekali angkat — itu justru gunanya menimbang berulang.
    _terapkan_hasil(trx, logic.hitung(
        aturan=aturan,
        berat_bermuatan_kg=trx.timbang1_kg,
        berat_kosong_kg=None,
        muatan=_baris_logic(trx.muatan),
        tara_lain_kg=trx.tara_lain_kg,
        kapasitas_kg=math.inf,
    ))
    waktu = sekarang()
    trx.timbang2_kg = None
    trx.timbang2_waktu = waktu
    trx.timbang2_waktu_sistem = waktu
    trx.timbang2_petugas_id = akun.id
    trx.status_tiket = TIKET_SELESAI
    trx.tanggal = waktu.date()

    await catat_audit(
        db, akun=akun, aksi="SELESAI_PARTAI", entitas="transaksi",
        entitas_id=trx.kode,
        ringkasan=f"{len(trx.penimbangan)} kali timbang → {trx.timbang1_kg:g} kg",
        sesudah={"total_kg": float(trx.timbang1_kg),
                 "jumlah_baris": len(trx.penimbangan)},
        perangkat=trx.perangkat_kode, ip=ip,
    )
    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return trx


async def simpan_timbang_kedua(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    kode: str,
    berat_kg: float,
    waktu_operator: datetime | None = None,
    muatan: list[InputMuatan] | None = None,
    tara_lain_kg: float | None = None,
    catatan: str | None = None,
    selesaikan: bool = True,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Timbang kedua → hitung, beri status, tutup tiket.

    Tanggal transaksi mengikuti timbang KEDUA: truk yang masuk menjelang
    tengah malam dan keluar setelahnya tercatat di hari ia selesai.

    **`selesaikan=False` menyimpan tanpa menutup tiket.** Angka timbang kedua
    sudah masuk dan aman dari HP mati atau shift berganti, tetapi tiketnya
    tetap terbuka karena penimbangannya memang belum selesai — biasanya
    jumlah karung baru diketahui setelah bongkar rampung. Yang ditunda bukan
    penyimpanannya, melainkan perhitungannya: selisih tidak dihitung, status
    kontrol tidak diberikan, dan lembar pemeriksaan tidak dibuka. Menghitung
    selisih tanpa jumlah karung akan memberi angka yang salah sekaligus
    meyakinkan — tara total nol membuat barang tampak berlebih.

    **Barang masuk tidak bisa diselesaikan tanpa jumlah karung.** Seluruh
    komoditas masuk bertara per karung, jadi tanpa angka itu berat barang dan
    selisihnya keliru — dan statusnya tersimpan permanen serta terbawa ke
    ekspor.
    """
    trx = await ambil_kode_terkunci(db, kode)
    if trx is None:
        raise LayananError(f"Transaksi {kode} tidak ditemukan.")
    if trx.status_transaksi == TRX_VOID:
        raise LayananError("Transaksi ini sudah dibatalkan.")
    if trx.status_tiket == TIKET_DITUTUP_PAKSA:
        raise LayananError("Tiket ini sudah ditutup paksa.")
    if trx.status_tiket == TIKET_SELESAI:
        # ── Kiriman ulang: isi sama lolos, isi BERBEDA ditolak ──
        #
        # Dulu baris ini langsung mengembalikan tiketnya, dan layar berkata
        # "Timbangan selesai dan tersimpan". Angka yang baru diketik dibuang
        # tanpa satu pun jejak audit, dan yang mengetiknya pulang dengan yakin
        # pekerjaannya tercatat. Itu keadaan terburuk yang bisa dibuat sebuah
        # layar: bukan gagal, melainkan berbohong.
        #
        # Kiriman ulang sejati tetap harus lolos — antrean luring mengirim
        # ulang kiriman yang sama saat sinyal kembali, dan menolaknya membuat
        # antreannya macet selamanya.
        tersimpan = float(trx.timbang2_kg or 0)
        if abs(tersimpan - float(berat_kg)) > 1e-6:
            raise LayananError(
                f"Tiket {kode} sudah diselesaikan"
                f"{await _oleh_siapa(db, trx)} dengan timbang kedua "
                f"{fmt.kg(tersimpan)} — angka {fmt.kg(berat_kg)} tidak "
                "disimpan. Pakai Koreksi bila angka yang tersimpan keliru."
            )
        return trx                      # kiriman ulang sejati — sudah tuntas
    if berat_kg <= 0:
        raise LayananError("Berat timbang harus lebih dari 0 kg.")
    # Diperiksa SEBELUM apa pun disentuh: jam yang ditolak tak boleh sempat
    # mengubah tanggal tiket, dan tanggal tiket menentukan periode laporannya.
    await pastikan_waktu_wajar(
        db, akun=akun, waktu=waktu_operator, sesudah=trx.timbang1_waktu,
        label="Jam timbang kedua", kode=trx.kode, ip=ip,
    )

    aturan = await aturan_untuk(db, trx.jenis_kode)
    waktu = sekarang()

    trx.timbang2_kg = float(berat_kg)
    trx.timbang2_waktu = waktu_operator or waktu
    trx.timbang2_waktu_sistem = waktu
    trx.timbang2_petugas_id = akun.id
    trx.diubah_oleh_id = akun.id
    trx.dikirim_pada = waktu
    trx.tanggal = (trx.timbang2_waktu or waktu).date()
    if catatan is not None:
        trx.catatan = catatan
    if tara_lain_kg is not None:
        trx.tara_lain_kg = float(tara_lain_kg)
    if muatan is not None:
        await _pasang_muatan(db, trx, muatan)

    if not selesaikan:
        await catat_audit(
            db, akun=akun, aksi="SIMPAN_SEMENTARA", entitas="transaksi",
            entitas_id=trx.kode,
            ringkasan=f"{trx.timbang2_kg:.0f} kg disimpan, tiket tetap terbuka",
            sesudah={"timbang2_kg": float(trx.timbang2_kg)},
            perangkat=trx.perangkat_kode, ip=ip,
        )
        await _sinkronkan_proses_bersama(db, trx)
        await db.commit()
        await db.refresh(trx)
        return trx

    if trx.arah == logic.MASUK and not sum(
        int(m.jumlah_karung or 0) for m in trx.muatan
    ):
        raise LayananError(
            "Jumlah karung belum diisi. Barang masuk tidak bisa diselesaikan "
            "tanpa angka itu — taranya dihitung per karung, jadi selisihnya "
            "akan keliru. Pakai Simpan sementara sampai bongkar rampung."
        )

    bermuatan, kosong = _bermuatan_dan_kosong(
        trx.arah, float(trx.timbang1_kg), float(trx.timbang2_kg)
    )
    trx.berat_bermuatan_kg = bermuatan
    trx.berat_kosong_kg = kosong

    _terapkan_hasil(trx, logic.hitung(
        aturan=aturan,
        berat_bermuatan_kg=bermuatan,
        berat_kosong_kg=kosong,
        muatan=_baris_logic(trx.muatan),
        tara_lain_kg=float(trx.tara_lain_kg or 0),
        kapasitas_kg=(await setelan.semua(db))["kapasitas_jembatan_kg"],
    ))
    trx.status_tiket = TIKET_SELESAI

    await catat_audit(
        db, akun=akun, aksi="SIMPAN_TIMBANG_2", entitas="transaksi",
        entitas_id=trx.kode,
        ringkasan=f"{trx.timbang2_kg:.0f} kg → selisih {trx.selisih_kg:+.0f} kg "
                  f"({trx.status_kontrol})",
        sesudah={
            "timbang2_kg": float(trx.timbang2_kg),
            "selisih_kg": float(trx.selisih_kg),
            "status_kontrol": trx.status_kontrol,
        },
        perangkat=trx.perangkat_kode, ip=ip,
    )

    if trx.status_kontrol in logic.STATUS_WAJIB_PERIKSA:
        await buka_pemeriksaan(db, akun=akun, trx=trx)

    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return trx


async def ubah_jenis(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    jenis_kode: str,
    alasan: str,
    tukar_timbangan: bool = False,
    ip: str | None = None,
) -> str:
    """Ganti komoditas — dan karenanya arah barang — pada transaksi yang ada.

    Operator memilih komoditas di awal, dan komoditas itulah yang menentukan
    arah: gabah selalu masuk, menir selalu keluar. Salah pilih di layar
    pertama karena itu berarti salah arah, dan salah arah membalik tafsir
    kedua angka timbangnya.

    **Biasanya angka timbangnya tidak perlu dipindah**, hanya ditafsirkan
    ulang: pada barang masuk timbang pertama adalah truk bermuatan, pada
    pengiriman ia truk kosong.

    Tetapi kadang urutan angkanya ikut terbalik, dan itu bukan kebetulan.
    Petugas mengetik mengikuti LABEL di layar, bukan urutan waktu — kalau
    arahnya terlanjur salah, ia menaruh bacaan bermuatan di kolom yang
    tertulis "truk kosong". `tukar_timbangan=True` menukar kedua angka
    beserta jamnya untuk keadaan itu.

    Kapan yang mana dibutuhkan tidak perlu ditebak: bila arah barunya membuat
    truk kosong lebih berat daripada truk bermuatan — mustahil secara fisik —
    layanan ini menolak dan menyebut penukaran sebagai jalan keluarnya, alih-
    alih melempar galat "berat truk kosong harus lebih kecil" yang benar
    tetapi tidak menolong siapa pun.

    Boleh dilakukan **sebelum maupun sesudah timbang kedua**, dan hanya oleh
    Admin (termasuk Super Admin). Bukan karena petugas tidak dipercaya,
    melainkan karena mengubah arah mengubah seluruh hasil kontrol sebuah
    transaksi yang sudah tersimpan — itu keputusan yang harus punya nama.
    """
    if not akun.is_admin:
        raise LayananError(
            "Hanya Admin yang boleh mengubah jenis atau arah barang."
        )
    if trx.status_transaksi == TRX_VOID:
        raise LayananError("Transaksi sudah dibatalkan.")
    if not (alasan or "").strip():
        raise LayananError("Perubahan jenis barang harus disertai alasan.")
    # Komoditas menentukan TABEL batch di produksi. Menggantinya sesudah
    # tertaut meninggalkan batch gabah yang menunjuk tiket PK — dan tak ada
    # constraint di mana pun yang melarang keadaan itu bertahan.
    await pastikan_bebas_tautan(db, trx, tindakan="Mengubah jenis barang")

    baru = (jenis_kode or "").strip().upper()
    if not baru or baru == trx.jenis_kode:
        return ""

    aturan_baru = await aturan_untuk(db, baru)
    aturan_lama = await aturan_untuk(db, trx.jenis_kode)

    # Timbang sekali tidak punya angka kedua. Komoditas yang dikontrol
    # terhadap dokumen menuntut dua angka; memindahkannya ke sana akan
    # menghitung seluruh berat truk sebagai barang.
    if (trx.cara_timbang == CARA_SEKALI
            and aturan_baru.acuan != logic.ACUAN_TIDAK_ADA):
        raise LayananError(
            f"{aturan_baru.nama} butuh dua kali timbang, sedangkan transaksi "
            "ini hanya ditimbang sekali. Batalkan lalu timbang ulang."
        )

    sebelum = {"jenis_kode": trx.jenis_kode, "arah": trx.arah,
               "status_kontrol": trx.status_kontrol,
               "selisih_kg": float(trx.selisih_kg or 0)}

    # Pindah arah berarti pindah TABEL pihak: supplier id 5 bukan pelanggan
    # id 5. Idnya karena itu tidak bisa dibawa — tetapi namanya bisa, dan
    # itulah yang benar-benar dibutuhkan catatan. Namanya diselamatkan ke
    # kolom teks bebas supaya tidak ada yang hilang diam-diam.
    if pihak_untuk(trx.arah) != pihak_untuk(aturan_baru.arah):
        nama_lama = await nama_pihak(db, trx)
        if nama_lama and not trx.pihak_nama:
            trx.pihak_nama = nama_lama
        trx.supplier_id = None
        trx.pelanggan_id = None

    trx.jenis_kode = baru
    trx.arah = aturan_baru.arah
    trx.aturan_snapshot = json.dumps(
        aturan_baru.__dict__, ensure_ascii=False, default=str
    )
    trx.diubah_oleh_id = akun.id

    await db.refresh(trx, ["muatan"])
    tara_lama_bawaan = aturan_lama.tara_default()
    for m in trx.muatan:
        m.jenis_kode = baru
        # Tara ikut berganti HANYA bila angkanya masih bawaan komoditas lama,
        # yaitu angka yang tinggal diterima petugas dari formulir. Bila ia
        # mengetiknya sendiri — hasil menimbang karung yang benar-benar ada —
        # angkanya dihormati, karena itu pengamatan, bukan setelan.
        if abs(float(m.tara_per_karung_kg or 0) - tara_lama_bawaan) < 1e-9:
            m.tara_per_karung_kg = aturan_baru.tara_default()

    if tukar_timbangan and trx.timbang2_kg is not None:
        trx.timbang1_kg, trx.timbang2_kg = trx.timbang2_kg, trx.timbang1_kg
        trx.timbang1_waktu, trx.timbang2_waktu = (
            trx.timbang2_waktu, trx.timbang1_waktu)
        trx.timbang1_petugas_id, trx.timbang2_petugas_id = (
            trx.timbang2_petugas_id, trx.timbang1_petugas_id)
        sebelum["timbang_ditukar"] = True

    if trx.status_tiket == TIKET_SELESAI and trx.cara_timbang != CARA_DUA_KALI:
        # ── Partai & sekali-timbang punya jalur hitungnya sendiri ──
        #
        # Keduanya tak punya `timbang2_kg`, dan blok di bawah ini menghitung
        # dari dua angka. Pada tiket PARTAI itu berakhir sebagai TypeError —
        # halaman galat 500, bukan kalimat yang bisa dibaca Admin — dan pada
        # tiket sekali-timbang ia menghasilkan angka yang salah dengan tenang.
        # Temuan QA T-21.
        #
        # `_hitung_ulang_koreksi` sudah menjawab ketiga cara timbang dengan
        # benar; dipakai di sini supaya tak ada dua tempat yang menghitung hal
        # yang sama secara berbeda.
        await _hitung_ulang_koreksi(db, trx)
    elif trx.status_tiket == TIKET_SELESAI:
        bermuatan, kosong = _bermuatan_dan_kosong(
            trx.arah, float(trx.timbang1_kg), float(trx.timbang2_kg)
            if trx.timbang2_kg is not None else None
        )
        if kosong is not None and kosong >= bermuatan:
            # Angkanya diformat sendiri-sendiri. Pernah ditulis sebagai satu
            # kalimat lalu `.replace(",", ".")` untuk pemisah ribuan — dan
            # koma kalimatnya ikut termakan jadi titik.
            def _kg(n: float) -> str:
                return f"{n:,.0f}".replace(",", ".")

            raise LayananError(
                f"Dengan arah {aturan_baru.arah.lower()}, truk kosong "
                f"({_kg(kosong)} kg) jadi lebih berat daripada truk bermuatan "
                f"({_kg(bermuatan)} kg) — mustahil. Kemungkinan besar urutan "
                "angkanya ikut terbalik karena petugas mengetik mengikuti "
                "label di layar. Ulangi sambil mencentang "
                "\u201cTukar urutan angka timbang\u201d."
            )
        trx.berat_bermuatan_kg = bermuatan
        trx.berat_kosong_kg = kosong
        _terapkan_hasil(trx, logic.hitung(
            aturan=aturan_baru,
            berat_bermuatan_kg=bermuatan,
            berat_kosong_kg=kosong,
            muatan=_baris_logic(trx.muatan),
            tara_lain_kg=float(trx.tara_lain_kg or 0),
            kapasitas_kg=(await setelan.semua(db))["kapasitas_jembatan_kg"],
        ))

    await catat_audit(
        db, akun=akun, aksi="UBAH_JENIS", entitas="transaksi",
        entitas_id=trx.kode,
        ringkasan=f"{aturan_lama.nama} ({sebelum['arah']}) → "
                  f"{aturan_baru.nama} ({trx.arah}) — {alasan.strip()}",
        sebelum=sebelum,
        sesudah={"jenis_kode": trx.jenis_kode, "arah": trx.arah,
                 "status_kontrol": trx.status_kontrol,
                 "selisih_kg": float(trx.selisih_kg or 0)},
        perangkat=trx.perangkat_kode, ip=ip,
    )

    if trx.status_kontrol in logic.STATUS_WAJIB_PERIKSA:
        await buka_pemeriksaan(db, akun=akun, trx=trx)

    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return f"{aturan_lama.nama} → {aturan_baru.nama}"


async def koreksi_transaksi(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    perubahan: dict,
    versi: str | None = None,
    muatan: list[InputMuatan] | None = None,
    alasan: str | None = None,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Koreksi input yang salah — dengan jejak sebelum & sesudah.

    Angka lama tidak hilang: ia tertulis di `timbangan_audit`.
    """
    # ── Barisnya DIKUNCI, lalu dibaca ULANG ──
    #
    # `trx` yang diterima fungsi ini dibaca sebelum permintaan ini mulai, dan
    # koreksi menghitung ulang dari angka di dalamnya. Bila orang lain
    # menyimpan di antaranya, hitungannya dibangun di atas angka basi — dan
    # hasilnya satu baris yang memuat tiga angka yang tak mungkin ada
    # bersamaan. Temuan QA T-04.
    await db.refresh(trx, with_for_update=True)
    pastikan_versi(trx, versi)

    nilai = await setelan.semua(db)
    boleh, sebab = boleh_mengubah(trx, akun, nilai["jam_kunci_otomatis"])
    if not boleh:
        raise LayananError(sebab)

    dapat_diubah = {
        "supplier_id", "pelanggan_id", "pihak_nama", "nomor_polisi",
        "nama_sopir",
        "timbang1_kg", "timbang2_kg", "timbang1_waktu", "timbang2_waktu",
        "tara_lain_kg", "catatan",
    }
    # Diperiksa sebelum apa pun disentuh — koreksi tidak boleh menjadi jalan
    # memutar untuk mengosongkan hal yang wajib saat menimbang. Rute koreksi
    # memang memperlakukan kolom kosong sebagai "tidak diubah", jadi pagar ini
    # menjaga pintu lain: antrean luring dan pemakaian layanan langsung.
    if "nomor_polisi" in perubahan:
        _wajib_nopol(trx.arah, perubahan["nomor_polisi"])
    if "nama_sopir" in perubahan:
        _wajib_sopir(perubahan["nama_sopir"])
    if "pihak_nama" in perubahan or "supplier_id" in perubahan:
        _wajib_pihak(
            trx.arah,
            punya_id=bool(
                perubahan.get("supplier_id", trx.supplier_id or trx.pelanggan_id)
            ),
            pihak_nama=perubahan.get("pihak_nama", trx.pihak_nama),
        )

    # ── Yang IKUT TERSALIN ke batch produksi tak boleh dikoreksi diam-diam ──
    #
    # Produksi menyalin pemasok, nopol, dan jam kedatangan SEKALI saat batch
    # dibuat, lalu tak pernah membacanya lagi. Bobot lain perkaranya: ada
    # poller yang menyusulkan revisinya. Jadi pagar ini hanya berdiri di depan
    # kolom yang revisinya tak punya jalan sampai ke sebelah.
    #
    # Membetulkan nama sopir atau catatan tetap bebas. Pagar yang mengunci
    # segalanya akan dicari jalan memutarnya, dan jalan memutar itu tak
    # meninggalkan jejak.
    IKUT_KE_BATCH = {"supplier_id", "pelanggan_id", "pihak_nama",
                     "nomor_polisi", "timbang1_waktu"}
    disentuh = {k for k in perubahan if k in IKUT_KE_BATCH
                and getattr(trx, k) != perubahan[k]}
    if trx.arah == logic.RETUR_MASUK:
        # Stok retur sudah menggunakan bobot DAN kemasan ini. Berbeda dari
        # batch pembelian, tidak ada poller yang menyusulkan koreksinya.
        disentuh.update(k for k in perubahan if k in dapat_diubah
                        and k not in {"catatan", "nama_sopir"}
                        and getattr(trx, k) != perubahan[k])
        if muatan is not None:
            disentuh.add("muatan")
    if disentuh:
        await pastikan_bebas_tautan(
            db, trx, tindakan="Mengoreksi " + ", ".join(sorted(disentuh)))

    sebelum, sesudah = {}, {}
    for kolom, nilai in perubahan.items():
        if kolom not in dapat_diubah:
            continue
        lama = getattr(trx, kolom)
        if kolom == "nomor_polisi":
            nilai = normalisasi_nopol(nilai)
        if lama == nilai:
            continue
        sebelum[kolom] = str(lama) if lama is not None else None
        sesudah[kolom] = str(nilai) if nilai is not None else None
        setattr(trx, kolom, nilai)

    if "nomor_polisi" in sesudah:
        kendaraan = await kendaraan_dari_nopol(db, trx.nomor_polisi)
        trx.kendaraan_id = kendaraan.id if kendaraan else None

    if muatan is not None:
        sebelum["muatan"] = [
            {"jenis": m.jenis_kode, "karung": m.jumlah_karung,
             "acuan_kg": float(m.berat_acuan_kg or 0)}
            for m in trx.muatan
        ]
        await _pasang_muatan(db, trx, muatan)
        sesudah["muatan"] = [
            {"jenis": m.jenis_kode, "karung": m.jumlah_karung,
             "acuan_kg": float(m.berat_acuan_kg or 0)}
            for m in trx.muatan
        ]

    if not sebelum:
        return trx

    # ── Hitung ulang, untuk SETIAP cara timbang ──
    #
    # Dulu hanya `DUA_KALI`. Jasa timbang SEKALI yang dikoreksi 12.000 → 8.000
    # nettonya tetap 12.000: angka yang dikoreksi tersimpan, hasilnya tidak.
    # Dan tiket partai lebih kacau lagi — koreksi mengubah `timbang1_kg`,
    # padahal pada partai angka itu cuma baris PERTAMA dari beberapa.
    kontrol_lama = trx.status_kontrol
    if await _hitung_ulang_koreksi(db, trx):
        sesudah["status_kontrol"] = trx.status_kontrol
        sesudah["selisih_kg"] = float(trx.selisih_kg or 0)

    # ── Status yang berubah jadi wajib-periksa MEMBUKA lembarnya ──
    #
    # Temuan QA T-07. Tiket bertanda INVESTIGASI tanpa satu pun lembar berarti
    # tak ada yang menindaklanjutinya: lembar itulah antrean pemeriksanya.
    # Jalur timbang kedua sudah membukanya sejak dulu; jalur koreksi tidak,
    # dan tak ada yang menyadarinya karena keduanya berakhir dengan status
    # yang sama di layar.
    if (trx.status_kontrol != kontrol_lama
            and trx.status_kontrol in _WAJIB_PERIKSA
            and trx.status_tiket == TIKET_SELESAI):
        await buka_pemeriksaan(db, akun=akun, trx=trx)

    trx.jumlah_revisi = (trx.jumlah_revisi or 0) + 1
    trx.diubah_oleh_id = akun.id

    await catat_audit(
        db, akun=akun, aksi="KOREKSI", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=alasan or f"Koreksi {', '.join(sebelum)}",
        sebelum=sebelum, sesudah=sesudah,
        perangkat=trx.perangkat_kode, ip=ip,
    )
    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return trx


#: Status kontrol yang menuntut lembar pemeriksaan dibuka.
#:
#: Diambil dari `logic`, bukan diketik ulang. Daftar yang diketik di sini dulu
#: berbunyi ("INVESTIGASI", "WAJIB_PERIKSA") — dan "WAJIB_PERIKSA" bukan nama
#: status mana pun. Akibatnya jalur koreksi tak pernah membuka lembar untuk
#: PERLU_PEMERIKSAAN maupun KELEBIHAN, dan tak ada yang menyadarinya karena
#: layarnya tetap menampilkan status yang benar.
_WAJIB_PERIKSA = logic.STATUS_WAJIB_PERIKSA


async def _hitung_ulang_koreksi(db: AsyncSession, trx: TimbanganTransaksi) -> bool:
    """Hitung ulang hasil sesudah koreksi — SATU jalur per cara timbang.

    Dulu satu `if` yang hanya menyebut `DUA_KALI`, dan dua cara lainnya
    diam-diam tak pernah dihitung ulang. Bentuk `if` tunggal itu pula yang
    membuat kelupaannya tak kelihatan: tak ada tempat yang menuntut ketiganya
    disebutkan.

    Kembalikan True bila ada yang dihitung ulang.
    """
    kapasitas = (await setelan.semua(db))["kapasitas_jembatan_kg"]
    # Aturan dari SNAPSHOT tiketnya, bukan aturan hari ini — lihat
    # `aturan_dari_snapshot`.
    aturan = aturan_dari_snapshot(trx) or await aturan_untuk(db, trx.jenis_kode)

    if trx.cara_timbang == CARA_SEKALI:
        # Tak ada pembanding: bruto = angka satu-satunya, tanpa kontrol.
        bruto = float(trx.timbang1_kg or 0)
        trx.berat_bermuatan_kg = bruto
        trx.berat_kosong_kg = None
        _terapkan_hasil(trx, logic.hitung(
            aturan=aturan, berat_bermuatan_kg=bruto, berat_kosong_kg=None,
            muatan=_baris_logic(trx.muatan),
            tara_lain_kg=float(trx.tara_lain_kg or 0), kapasitas_kg=kapasitas,
        ))
        return True

    if trx.cara_timbang == CARA_PARTAI:
        # Pada partai, berat totalnya JUMLAH baris penimbangan — `timbang1_kg`
        # cuma baris pertama. Menghitung dari situ memberi angka yang selalu
        # kurang, sebanyak apa pun barang yang menyusul.
        await db.refresh(trx, ["penimbangan"])
        total = sum(float(b.berat_kg or 0) for b in trx.penimbangan)
        trx.berat_bermuatan_kg = total
        trx.berat_kosong_kg = None
        _terapkan_hasil(trx, logic.hitung(
            aturan=aturan, berat_bermuatan_kg=total, berat_kosong_kg=None,
            muatan=_baris_logic(trx.muatan),
            tara_lain_kg=float(trx.tara_lain_kg or 0), kapasitas_kg=kapasitas,
        ))
        return True

    if trx.timbang2_kg is None:
        return False          # DUA_KALI yang belum lengkap — tak ada hasilnya
    bermuatan, kosong = _bermuatan_dan_kosong(
        trx.arah, float(trx.timbang1_kg), float(trx.timbang2_kg)
    )
    trx.berat_bermuatan_kg = bermuatan
    trx.berat_kosong_kg = kosong
    _terapkan_hasil(trx, logic.hitung(
        aturan=aturan, berat_bermuatan_kg=bermuatan, berat_kosong_kg=kosong,
        muatan=_baris_logic(trx.muatan),
        tara_lain_kg=float(trx.tara_lain_kg or 0), kapasitas_kg=kapasitas,
    ))
    return True


def aturan_dari_snapshot(trx: TimbanganTransaksi) -> "logic.AturanJenis | None":
    """Bangun aturan dari `aturan_snapshot` tiket — bukan aturan hari ini.

    Snapshotnya ditulis pada TIAP penimbangan sejak lama, dan tak pernah
    sekali pun dibaca. Temuan QA T-13.

    Akibatnya tiket lama dinilai ulang dengan aturan yang berlaku sekarang:
    toleransi yang berubah bulan lalu membuat tiket bulan sebelumnya tiba-tiba
    berstatus lain, dan bukti yang dicetak ULANG bisa berbeda dari yang dulu
    diserahkan ke sopir — termasuk flag rahasia, yang menentukan apakah angka
    acuan ikut tercetak.

    Yang tak punya snapshot (tiket paling lama) mengembalikan None, dan
    pemanggilnya jatuh ke aturan sekarang. Itu memang satu-satunya yang
    tersisa untuk mereka.
    """
    mentah = (trx.aturan_snapshot or "").strip()
    if not mentah:
        return None
    try:
        data = json.loads(mentah)
        sah = {f.name for f in dataclasses.fields(logic.AturanJenis)}
        return logic.AturanJenis(**{k: v for k, v in data.items() if k in sah})
    except Exception:
        # Snapshot rusak atau dari bentuk lama: jatuh ke aturan sekarang,
        # bukan menggagalkan pencetakan bukti.
        return None


async def void_transaksi(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    alasan: str,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Batalkan transaksi. Data TIDAK pernah dihapus — hanya ditandai."""
    if not boleh_membatalkan(akun, trx):
        # Kalimatnya menyebut SEBABNYA, bukan sekadar perannya: petugas yang
        # ditolak di sini hampir selalu sedang memegang tiket yang sudah
        # ditimbang kedua, dan yang ia perlu tahu adalah itu — bukan bahwa ia
        # bukan Admin.
        raise LayananError(
            "Tiket ini sudah ditimbang kedua — pembatalannya jadi wewenang "
            "Admin. Yang masih menunggu timbang kedua boleh Anda batalkan "
            "sendiri.")
    if not (alasan or "").strip():
        raise LayananError("Pembatalan harus disertai alasan.")
    if trx.status_transaksi == TRX_VOID:
        return trx
    # Gabahnya mungkin sudah masuk stok di sebelah. Membatalkan tiketnya di
    # sini tak menariknya keluar dari sana — yang terjadi hanyalah dua sistem
    # berhenti sepakat tentang truk yang sama.
    await pastikan_bebas_tautan(db, trx, tindakan="Membatalkan tiket ini")

    trx.status_transaksi = TRX_VOID
    trx.void_alasan = alasan.strip()
    trx.void_oleh_id = akun.id
    trx.void_pada = sekarang()

    # ── Lembar pemeriksaannya ikut ditutup ──
    #
    # Lembar milik tiket yang dibatalkan menumpuk di antrean SELAMANYA:
    # pekerjaan yang tak mungkin diselesaikan siapa pun, sebab angka yang
    # hendak ditelusuri sudah tak berlaku. Antrean yang memuat pekerjaan
    # semacam itu berhenti dibaca orang. Temuan QA T-23.
    ditutup = (await db.execute(
        select(TimbanganPemeriksaan).where(
            TimbanganPemeriksaan.transaksi_id == trx.id,
            TimbanganPemeriksaan.status != PEMERIKSAAN_SELESAI,
        )
    )).scalars().all()
    for lembar in ditutup:
        lembar.status = PEMERIKSAAN_SELESAI
        lembar.kategori_hasil = lembar.kategori_hasil or "TIKET_DIBATALKAN"
        lembar.catatan_resolusi = (
            f"Ditutup otomatis karena tiketnya dibatalkan: {trx.void_alasan}"
        )
        lembar.ditutup_oleh_id = akun.id
        lembar.ditutup_pada = sekarang()
        await catat_audit(
            db, akun=akun, aksi="PEMERIKSAAN_SELESAI", entitas="pemeriksaan",
            entitas_id=lembar.id,
            ringkasan="ditutup otomatis — tiketnya dibatalkan", ip=ip,
        )

    await catat_audit(
        db, akun=akun, aksi="VOID", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=trx.void_alasan, ip=ip,
    )
    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return trx


async def tutup_paksa(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    alasan: str,
    tanpa_timbang_keluar: bool = False,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Tutup tiket yang tidak akan pernah punya timbang kedua.

    Truk yang batal bongkar tetap meninggalkan jejak: tiketnya ditutup dengan
    alasan, bukan dihapus supaya daftar terlihat rapi.

    **Muatan yang DITOLAK bukan alasan melewatkan timbang keluar.** Truk yang
    ditolak tetap keluar dari pabrik, dan tanpa angka keluarnya tak ada
    kontrol masuk−keluar sama sekali (RANCANGAN §4.3) — truk bisa pergi
    membawa lebih banyak daripada yang ia bawa masuk, dan tak ada satu angka
    pun yang bisa menunjukkannya. Yang benar untuk muatan ditolak adalah
    menyelesaikan timbang keduanya seperti biasa; barang diterima jatuh ke
    sekitar nol dengan sendirinya, dan selisihnya tetap terkontrol.

    Jalan ini karena itu hanya untuk truk yang MEMANG sudah pergi tanpa
    ditimbang, dan `tanpa_timbang_keluar` adalah pengakuan tertulis bahwa
    itulah yang terjadi. Temuan QA T-15.
    """
    if trx.status_tiket != TIKET_TERBUKA:
        raise LayananError("Tiket ini tidak dalam keadaan terbuka.")
    if not (alasan or "").strip():
        raise LayananError("Penutupan paksa harus disertai alasan.")
    if not tanpa_timbang_keluar:
        raise LayananError(
            "Truk yang ditolak tetap wajib ditimbang keluar — selesaikan "
            "timbang keduanya, dan barang diterima akan terhitung nol. "
            "Penutupan paksa hanya untuk truk yang sudah pergi tanpa "
            "sempat ditimbang keluar."
        )
    # ── Tiket orang lain hanya boleh ditutup Admin ke atas ──
    #
    # Sebelumnya siapa pun bisa. Andi menutup tiket Siti dengan alasannya
    # sendiri, dan Siti tak pernah tahu — yang tertinggal di layar hanyalah
    # tiketnya yang hilang dari daftar terbuka.
    if not akun.is_admin and (trx.timbang1_petugas_id or trx.dibuat_oleh_id) \
            not in (akun.id, None):
        raise LayananError(
            "Tiket ini dibuka petugas lain. Menutup paksa tiket orang lain "
            "hanya bisa oleh Admin."
        )
    # Menutup paksa mengosongkan hasil timbangnya. Bila produksi sudah menaut
    # batch ke tiket ini, batch itu akan menunggu bobot selamanya.
    await pastikan_bebas_tautan(db, trx, tindakan="Menutup paksa tiket ini")

    trx.status_tiket = TIKET_DITUTUP_PAKSA
    trx.tutup_paksa_alasan = alasan.strip()
    trx.diubah_oleh_id = akun.id
    _kosongkan_hasil(trx)

    await catat_audit(
        db, akun=akun, aksi="TUTUP_PAKSA", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=f"{trx.tutup_paksa_alasan} — truk pergi tanpa timbang keluar",
        ip=ip,
    )
    await _sinkronkan_proses_bersama(db, trx)
    await db.commit()
    await db.refresh(trx)
    return trx


async def kunci_transaksi(
    db: AsyncSession, *, akun: TimbanganAkun, trx: TimbanganTransaksi
) -> TimbanganTransaksi:
    trx.terkunci = True
    trx.dikunci_pada = sekarang()
    await catat_audit(
        db, akun=akun, aksi="KUNCI", entitas="transaksi", entitas_id=trx.kode,
    )
    await db.commit()
    return trx


# ═══════════════════════════ Akun ═══════════════════════════

async def hapus_transaksi(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    alasan: str,
    ip: str | None = None,
) -> str:
    """Hapus catatan timbang seluruhnya. Hanya Super Admin.

    **Ini bukan pembatalan.** Membatalkan (VOID) meninggalkan barisnya di
    catatan beserta alasannya — truk yang batal bongkar tetap terlihat pernah
    datang, dan itu memang yang benar. Menghapus meniadakan barisnya sama
    sekali. Karena itu wewenangnya dipisahkan ke peran tersendiri: agar
    pekerjaan sehari-hari tidak dilakukan sambil memegang tombol yang tidak
    bisa dibatalkan.

    Yang tetap tertinggal adalah jejak auditnya, berisi salinan penuh angka
    yang dihapus beserta alasannya. Audit hanya bertambah — sebuah catatan
    boleh hilang dari daftar, tetapi tidak boleh hilang dari sejarah.
    """
    from app.timbangan.models import TimbanganCetak, TimbanganPemeriksaan

    if not akun.is_super:
        raise LayananError("Menghapus catatan timbang hanya bisa Super Admin.")
    if not (alasan or "").strip():
        raise LayananError("Penghapusan harus disertai alasan.")
    # Diperiksa DI SINI, bukan dibiarkan foreign key produksi yang menolak.
    # Keduanya sama-sama menahan barisnya, tetapi yang satu berbunyi seperti
    # penjelasan dan yang lain berbunyi seperti aplikasi rusak.
    await pastikan_bebas_tautan(db, trx, tindakan="Menghapus tiket ini")

    kode = trx.kode
    await db.refresh(trx, ["muatan"])
    salinan = {
        "kode": kode, "tanggal": str(trx.tanggal), "arah": trx.arah,
        "jenis_kode": trx.jenis_kode,
        "pihak": trx.pihak_nama, "supplier_id": trx.supplier_id,
        "nomor_polisi": trx.nomor_polisi, "nama_sopir": trx.nama_sopir,
        "timbang1_kg": trx.timbang1_kg, "timbang2_kg": trx.timbang2_kg,
        "netto_timbangan_kg": trx.netto_timbangan_kg,
        "berat_barang_kg": trx.berat_barang_kg,
        "berat_acuan_kg": trx.berat_acuan_kg,
        "selisih_kg": trx.selisih_kg, "selisih_persen": trx.selisih_persen,
        "status_kontrol": trx.status_kontrol,
        "status_tiket": trx.status_tiket,
        "status_transaksi": trx.status_transaksi,
        "muatan": [
            {"jenis_kode": m.jenis_kode, "jumlah_karung": m.jumlah_karung,
             "tara_per_karung_kg": m.tara_per_karung_kg,
             "berat_acuan_kg": m.berat_acuan_kg, "nomor_acuan": m.nomor_acuan}
            for m in trx.muatan
        ],
    }
    await catat_audit(
        db, akun=akun, aksi="HAPUS_TRANSAKSI", entitas="transaksi",
        entitas_id=kode,
        ringkasan=f"{kode} dihapus permanen — {alasan.strip()}",
        sebelum=salinan, sesudah={"alasan": alasan.strip()},
        perangkat=trx.perangkat_kode, ip=ip,
    )

    # Muatan dan foto ikut terhapus lewat cascade relasinya; cetak dan
    # pemeriksaan tidak punya relasi, jadi dihapus di sini. Menghapus muatan
    # dua kali membuat ORM mengira ada baris yang hilang diam-diam.
    for model in (TimbanganCetak, TimbanganPemeriksaan):
        await db.execute(delete(model).where(model.transaksi_id == trx.id))
    await db.execute(delete(ProsesTerpadu).where(
        ProsesTerpadu.aplikasi == "timbangan",
        ProsesTerpadu.tabel_sumber == "timbangan_transaksi",
        ProsesTerpadu.id_sumber == str(trx.id),
    ))
    await db.delete(trx)
    await db.commit()
    return kode


async def _admin_aktif_lain(db: AsyncSession, kecuali_id: int) -> int:
    """Admin lain yang masih aktif — Super Admin ikut dihitung.

    Yang dijaga adalah "masih ada yang bisa mengelola pengguna", dan Super
    Admin bisa. Menghitungnya terpisah akan menolak penurunan peran yang
    sebenarnya aman. Profil tertaut ikut terhitung lewat kolom `role`-nya
    yang disinkronkan tiap masuk; Super Admin bersama yang belum punya
    profil dihitung `security.ada_super_aktif`.
    """
    return (await db.execute(
        select(func.count(TimbanganAkun.id)).where(
            TimbanganAkun.role.in_((ROLE_ADMIN, ROLE_SUPERADMIN)),
            TimbanganAkun.status == "aktif",
            TimbanganAkun.id != kecuali_id,
        )
    )).scalar_one()


async def _terapkan_ubah_akun(
    db: AsyncSession,
    *,
    pelaku: TimbanganAkun,
    orang: TimbanganAkun,
    nama: str | None = None,
    username: str | None = None,
    role: str | None = None,
    perangkat_kode: str | None = None,
    sandi_baru: str | None = None,
    ip: str | None = None,
) -> list[str]:
    """Ubah data satu akun. Mengembalikan daftar kolom yang benar-benar berubah.

    Dua pagar yang tidak boleh dilepas, keduanya melindungi dari mengunci diri
    sendiri di luar sistem:

      · **Selalu tersisa satu Admin aktif.** Menurunkan peran atau
        menonaktifkan Admin terakhir akan membuat tidak ada lagi yang bisa
        mengelola pengguna — dan tidak ada jalan memperbaikinya dari dalam
        aplikasi.
      · **Sandi kosong berarti tidak diubah**, bukan dikosongkan. Kalau tidak,
        Admin yang hanya ingin membetulkan ejaan nama akan tanpa sadar
        menghapus sandi orang lain.

    Sandi lama tidak pernah tersimpan maupun tercatat di audit — yang dicatat
    hanya FAKTA bahwa sandi diganti.
    """
    from app.timbangan.security import hash_sandi

    sebelum, sesudah, berubah = {}, {}, []

    # ── Profil tertaut: nama, nama pengguna, peran, dan sandi milik akun
    #    bersama — diubah di Pos Produksi / Meja oleh Super Admin ──
    if orang.tertaut:
        milik_bersama = []
        if username is not None and username.strip().lower() not in ("", orang.username):
            milik_bersama.append("nama pengguna")
        if nama is not None and nama.strip() not in ("", orang.nama):
            milik_bersama.append("nama")
        if role is not None and role != orang.role:
            milik_bersama.append("peran")
        if sandi_baru:
            milik_bersama.append("sandi")
        if milik_bersama:
            raise LayananError(
                f"{', '.join(milik_bersama).capitalize()} milik akun bersama — "
                "ubah di Pos Produksi atau Meja (Kelola pengguna). Di sini "
                "hanya kode perangkat.")
        username = nama = role = sandi_baru = None

    if username is not None:
        bersih = username.strip().lower()
        if not bersih:
            raise LayananError("Nama pengguna tidak boleh kosong.")
        if bersih != orang.username:
            bentrok = (await db.execute(
                select(TimbanganAkun).where(
                    TimbanganAkun.username == bersih,
                    TimbanganAkun.id != orang.id,
                )
            )).scalars().first()
            if bentrok is not None:
                raise LayananError(f"Nama pengguna '{bersih}' sudah dipakai.")
            sebelum["username"], sesudah["username"] = orang.username, bersih
            orang.username = bersih
            berubah.append("nama pengguna")

    if nama is not None and nama.strip() and nama.strip() != orang.nama:
        sebelum["nama"], sesudah["nama"] = orang.nama, nama.strip()
        orang.nama = nama.strip()
        berubah.append("nama")

    if role is not None and role != orang.role:
        if role not in ROLES:
            raise LayananError(f"Peran '{role}' tidak dikenal.")
        if orang.is_admin and not await _admin_aktif_lain(db, orang.id):
            raise LayananError(
                "Ini satu-satunya Admin yang aktif. Angkat Admin lain lebih "
                "dulu, kalau tidak tidak akan ada yang bisa mengelola pengguna."
            )
        sebelum["role"], sesudah["role"] = orang.role, role
        orang.role = role
        berubah.append("peran")

    if perangkat_kode is not None:
        kode = perangkat_kode.strip().upper()[:8] or None
        if kode != orang.perangkat_kode:
            sebelum["perangkat_kode"] = orang.perangkat_kode
            sesudah["perangkat_kode"] = kode
            orang.perangkat_kode = kode
            berubah.append("kode perangkat")

    # Kosong berarti "jangan diubah" — bukan "kosongkan".
    if sandi_baru:
        try:
            orang.password_hash = hash_sandi(sandi_baru)
        except ValueError as e:
            raise LayananError(str(e)) from None
        # Sandi tidak pernah masuk audit, baik yang lama maupun yang baru.
        sesudah["sandi"] = "diganti"
        berubah.append("sandi")

    # ── Sesi lama ikut putus ──
    #
    # Sandi yang diganti atau peran yang diturunkan tak berarti apa-apa
    # selama token lama masih diterima — dan token di sini berlaku 180 hari.
    # Temuan QA T-19.
    if "sandi" in berubah or "peran" in berubah:
        orang.token_version = (orang.token_version or 1) + 1

    if not berubah:
        return []

    await catat_audit(
        db, akun=pelaku, aksi="UBAH_AKUN", entitas="akun", entitas_id=orang.id,
        ringkasan=f"{orang.username}: {', '.join(berubah)} diubah",
        sebelum=sebelum or None, sesudah=sesudah or None, ip=ip,
    )
    await db.commit()
    return berubah


async def _super_aktif_ada(db: AsyncSession, kecuali_id: int | None = None) -> bool:
    q = select(func.count(TimbanganAkun.id)).where(
        TimbanganAkun.role == ROLE_SUPERADMIN,
        TimbanganAkun.status == "aktif",
    )
    if kecuali_id is not None:
        q = q.where(TimbanganAkun.id != kecuali_id)
    return bool((await db.execute(q)).scalar_one())


async def _jaga_wewenang_super(
    db: AsyncSession, *, admin: TimbanganAkun, orang: TimbanganAkun,
    role_baru: str | None = None,
) -> None:
    """Admin biasa tidak boleh menyentuh Super Admin, apalagi menjadi satu.

    Kalau boleh, pemisahan perannya tidak berarti apa-apa: Admin mana pun
    tinggal mengangkat dirinya sendiri, atau menonaktifkan Super Admin yang
    ada lalu mengangkat dirinya. Wewenang menghapus data akan kembali
    melekat pada pekerjaan sehari-hari — persis yang hendak dihindari.

    Satu pengecualian, untuk membuat yang PERTAMA dan untuk memulihkan bila
    satu-satunya hilang: selama belum ada Super Admin aktif, Admin boleh
    mengangkatnya. Begitu ada, pintunya tertutup dan hanya Super Admin yang
    bisa membukanya lagi.
    """
    if admin.is_super:
        return
    if orang.is_super:
        raise LayananError(
            "Akun Super Admin hanya bisa diubah oleh Super Admin."
        )
    if role_baru == ROLE_SUPERADMIN and await _super_aktif_ada(db):
        raise LayananError(
            "Hanya Super Admin yang bisa mengangkat Super Admin baru."
        )


async def jaga_pemberian_peran(
    db: AsyncSession, *, admin: TimbanganAkun, role: str
) -> None:
    """Dipakai saat MEMBUAT akun. Pagarnya sama dengan saat mengubah peran —
    kalau tidak, Admin cukup membuat akun Super Admin baru dan masuk dengannya.
    """
    if role == ROLE_SUPERADMIN and not admin.is_super and await _super_aktif_ada(db):
        raise LayananError("Hanya Super Admin yang bisa mengangkat Super Admin baru.")
    if role not in ROLES:
        raise LayananError(f"Peran '{role}' tidak dikenal.")


async def ubah_akun(
    db: AsyncSession,
    *,
    admin: TimbanganAkun,
    orang: TimbanganAkun,
    **ubahan,
) -> list[str]:
    """Admin mengubah akun siapa pun, termasuk peran dan kode perangkat."""
    if not admin.is_admin:
        raise LayananError("Hanya Admin yang boleh mengubah akun orang lain.")
    await _jaga_wewenang_super(
        db, admin=admin, orang=orang, role_baru=ubahan.get("role")
    )
    return await _terapkan_ubah_akun(db, pelaku=admin, orang=orang, **ubahan)


async def ubah_profil(
    db: AsyncSession,
    *,
    orang: TimbanganAkun,
    nama: str | None = None,
    username: str | None = None,
    sandi_lama: str | None = None,
    sandi_baru: str | None = None,
    ip: str | None = None,
) -> list[str]:
    """Siapa pun membetulkan akunnya SENDIRI: nama, nama pengguna, sandi.

    Yang sengaja TIDAK ada di sini: peran dan kode perangkat. Keduanya
    menentukan apa yang boleh dilakukan orang ini dan nomor transaksi apa
    yang keluar dari perangkatnya — itu keputusan Admin, bukan keputusan
    pemakainya sendiri.

    Mengganti sandi menuntut sandi yang sekarang. Perangkat di pos timbang
    dipakai bergantian dan tetap masuk sepanjang shift; tanpa syarat ini,
    siapa pun yang lewat di depan layar yang ditinggal terbuka bisa mengunci
    pemiliknya keluar dari akunnya sendiri.
    """
    from app.timbangan.security import cek_sandi

    if orang.tertaut:
        return await _ubah_profil_bersama(
            db, orang=orang, nama=nama, username=username,
            sandi_lama=sandi_lama, sandi_baru=sandi_baru, ip=ip)

    if sandi_baru:
        if not sandi_lama:
            raise LayananError(
                "Masukkan sandi Anda yang sekarang untuk menggantinya."
            )
        if not cek_sandi(sandi_lama, orang.password_hash):
            raise LayananError("Sandi sekarang tidak cocok.")

    return await _terapkan_ubah_akun(
        db, pelaku=orang, orang=orang,
        nama=nama, username=username, sandi_baru=sandi_baru, ip=ip,
    )


def _kolom_penunjuk_akun():
    """Setiap kolom yang menunjuk `timbangan_akun.id`, kecuali milik audit.

    Dibaca dari metadata, bukan dari daftar yang ditulis tangan — supaya
    tabel baru yang menyimpan "siapa yang mengerjakan" ikut terjaga sendiri
    tanpa ada yang perlu ingat memperbarui fungsi ini.
    """
    from app.database import Base

    for tabel in Base.metadata.sorted_tables:
        if tabel.name == "timbangan_audit":
            continue
        for kolom in tabel.columns:
            if any(fk.target_fullname == "timbangan_akun.id"
                   for fk in kolom.foreign_keys):
                yield tabel, kolom


async def _tabel_yang_menunjuk_akun(db: AsyncSession, akun_id: int) -> list[str]:
    """Nama kolom mana saja yang masih menunjuk akun ini. Audit dikecualikan.

    Dibaca dari metadata, bukan dari daftar tabel yang ditulis tangan — supaya
    tabel baru yang menyimpan "siapa yang mengerjakan" ikut terjaga sendiri
    tanpa ada yang perlu ingat memperbarui fungsi ini.

    Audit sengaja di luar hitungan: barisnya sudah menyimpan `akun_nama`
    sebagai salinan, jadi jejaknya tetap terbaca meski penunjuknya dilepas.
    """
    dipakai = []
    for tabel, kolom in _kolom_penunjuk_akun():
        ada = (await db.execute(
            select(literal(1)).select_from(tabel)
            .where(kolom == akun_id).limit(1)
        )).first()
        if ada:
            dipakai.append(f"{tabel.name}.{kolom.name}")
    return dipakai


async def hapus_akun(
    db: AsyncSession,
    *,
    admin: TimbanganAkun,
    orang: TimbanganAkun,
    ip: str | None = None,
) -> str:
    """Hapus akun. Mengembalikan namanya.

    **Catatan timbang tidak pernah ikut terhapus.** Yang dilepas hanya
    penunjuk namanya: baris yang tadinya menyebut orang ini berubah menjadi
    tidak menyebut siapa-siapa. Angka timbang, tanggal, selisih, status —
    semuanya utuh.

    Karena itu wewenangnya dibagi dua:

      · **Admin** hanya boleh menghapus akun yang belum meninggalkan jejak
        kerja apa pun — salah ketik saat membuat, akun percobaan, orang yang
        batal masuk. Untuk yang sudah bekerja: nonaktifkan, supaya catatannya
        tetap menyebut orang yang benar.
      · **Super Admin** boleh menghapus akun yang sudah bekerja, dan nama
        pada catatan-catatan itu dikosongkan. Keputusan Direksi 30 Agustus
        2026.

    Jejak audit tidak ikut terhapus, baik miliknya maupun tentangnya.
    Penunjuk akunnya dilepas, tetapi `akun_nama` sudah tersimpan sebagai
    salinan sejak baris itu ditulis — sehingga "siapa" tetap terbaca di sana
    meski akunnya tidak ada lagi. Itu pula satu-satunya tempat yang masih
    bisa menjawab siapa yang menimbang catatan yang namanya dikosongkan.
    """
    from app.timbangan.models import TimbanganAudit

    if not admin.is_admin:
        raise LayananError("Hanya Admin yang boleh menghapus akun.")
    await _jaga_wewenang_super(db, admin=admin, orang=orang)
    if orang.id == admin.id:
        raise LayananError("Tidak bisa menghapus akun sendiri.")
    if orang.is_admin and not await _admin_aktif_lain(db, orang.id):
        raise LayananError(
            "Ini satu-satunya Admin yang aktif. Angkat Admin lain lebih dulu."
        )

    dipakai = await _tabel_yang_menunjuk_akun(db, orang.id)
    if dipakai and not admin.is_super:
        raise LayananError(
            f"{orang.nama} sudah punya riwayat kerja. Menghapus akunnya akan "
            "mengosongkan namanya dari catatan-catatan itu, dan itu hanya "
            "bisa dilakukan Super Admin. Nonaktifkan saja — pintunya "
            "tertutup, catatannya tetap menyebut orang yang benar."
        )

    nama = orang.nama
    await catat_audit(
        db, akun=admin, aksi="HAPUS_AKUN", entitas="akun", entitas_id=orang.id,
        ringkasan=(
            f"{orang.username} ({nama}) dihapus — "
            + (f"nama dikosongkan dari {len(dipakai)} kolom catatan: "
               + ", ".join(dipakai)
               if dipakai else "belum punya riwayat kerja")
        ),
        sebelum={"username": orang.username, "nama": nama, "role": orang.role,
                 "perangkat_kode": orang.perangkat_kode, "status": orang.status},
        sesudah={"nama_dikosongkan_dari": dipakai} if dipakai else None,
        ip=ip,
    )

    # Kosongkan namanya dari catatan, JANGAN hapus catatannya. Semua kolom
    # penunjuk akun memang boleh NULL — itu keputusan skema sejak awal,
    # supaya catatan tidak pernah bergantung pada akun yang masih ada.
    for tabel, kolom in _kolom_penunjuk_akun():
        await db.execute(
            tabel.update().where(kolom == orang.id).values({kolom.name: None})
        )
    # Penunjuk di audit ikut dilepas; `akun_nama` tetap menyimpan namanya.
    await db.execute(
        update(TimbanganAudit)
        .where(TimbanganAudit.akun_id == orang.id)
        .values(akun_id=None)
    )
    await db.delete(orang)
    await db.commit()
    return nama


async def ubah_status_akun(
    db: AsyncSession, *, admin: TimbanganAkun, orang: TimbanganAkun,
    ip: str | None = None,
) -> str:
    """Aktifkan atau nonaktifkan satu akun (yang BELUM ditautkan).

    Profil tertaut punya satu saklar untuk semua aplikasi di Pos Produksi /
    Meja (`hmu_identitas.masuk.nonaktifkan`); dua saklar untuk satu orang
    adalah persis temuan QA X-11.
    """
    if not admin.is_admin:
        raise LayananError("Hanya Admin yang boleh mengubah akun.")
    if orang.tertaut:
        raise LayananError(
            f"{orang.nama} memakai akun bersama — nonaktifkan di Pos Produksi "
            "atau Meja (Kelola pengguna); berlaku untuk semua aplikasi sekaligus.")
    await _jaga_wewenang_super(db, admin=admin, orang=orang)
    if orang.id == admin.id:
        raise LayananError("Anda tidak bisa menonaktifkan akun sendiri.")
    if (orang.status == "aktif" and orang.is_admin
            and not await _admin_aktif_lain(db, orang.id)):
        raise LayananError(
            "Ini satu-satunya Admin yang aktif — menonaktifkannya membuat "
            "tidak ada lagi yang bisa mengelola pengguna."
        )

    lama = orang.status
    orang.status = "nonaktif" if lama == "aktif" else "aktif"
    await catat_audit(
        db, akun=admin, aksi="UBAH_STATUS_AKUN", entitas="akun",
        entitas_id=orang.id, ringkasan=f"{orang.username} → {orang.status}",
        sebelum={"status": lama}, sesudah={"status": orang.status}, ip=ip,
    )
    await db.commit()
    return orang.status


# ═══════════════════════════ Identitas bersama ═══════════════════════════
#
# Sejak Tahap 2 rancang ulang (13 Sep 2026): kredensial, peran, status, dan
# nama orang tinggal di akun bersama (`produksi_akun` + `users`,
# `hmu_identitas`). `timbangan_akun` yang tertaut adalah PROFIL pos timbang:
# kode perangkat, dan sasaran foreign key seluruh catatan timbang.

async def sinkron_profil(db: AsyncSession, profil: TimbanganAkun, bersama: Akun) -> bool:
    """Cerminkan nama/peran/status akun bersama ke profil. True bila berubah.

    Kolom cermin dipertahankan (bukan dibuang) karena kueri, templat, dan
    `akun_nama` di audit membacanya; yang menjamin kebenarannya adalah
    penyelarasan di sini — tiap masuk dan tiap permintaan bersesi.
    """
    berubah = False
    role = P.ke_timbangan(bersama.peran)
    status = "aktif" if bersama.aktif else "nonaktif"
    for kolom, nilai in (("nama", bersama.nama), ("role", role), ("status", status),
                         ("user_id", bersama.user_id), ("username", bersama.username)):
        if getattr(profil, kolom) != nilai:
            setattr(profil, kolom, nilai)
            berubah = True
    if berubah:
        await db.commit()
    return berubah


async def profil_untuk(db: AsyncSession, bersama: Akun, *, buat: bool = True,
                       perangkat_kode: str | None = None) -> TimbanganAkun | None:
    """Profil pos timbang milik akun bersama — dibuat bila belum ada.

    Dibuat TANPA kode perangkat: kode itu masuk ke nomor tiket dan tercetak
    di struk, jadi Admin yang menetapkannya (daftar "belum punya kode" ada di
    layar Pengguna, temuan QA T-01). Nama pengguna lama yang kebetulan sama
    tetapi belum ditautkan ikut ditautkan di sini: satu orang, satu baris.
    """
    profil = (await db.execute(
        select(TimbanganAkun).where(TimbanganAkun.akun_id == bersama.id)
    )).scalars().first()
    if profil is not None or not buat:
        return profil
    lama = (await db.execute(
        select(TimbanganAkun).where(TimbanganAkun.username == bersama.username,
                                    TimbanganAkun.akun_id.is_(None))
    )).scalars().first()
    if lama is not None:
        lama.akun_id = bersama.id
        lama.password_hash = None
        profil = lama
    else:
        profil = TimbanganAkun(
            username=bersama.username, nama=bersama.nama,
            role=P.ke_timbangan(bersama.peran), akun_id=bersama.id,
            user_id=bersama.user_id, password_hash=None,
            perangkat_kode=(perangkat_kode or "").strip().upper()[:8] or None,
        )
        db.add(profil)
    await db.flush()
    await sinkron_profil(db, profil, bersama)
    await db.commit()
    return profil


async def masuk_bersama(db: AsyncSession, username: str, sandi: str) -> tuple[Akun, TimbanganAkun]:
    """Masuk dengan akun bersama: kredensial (paket), pintu pos timbang,
    profil (dibuat bila perlu). Melempar `identitas.Tolak`."""
    bersama = await identitas.periksa_kredensial(db, username, sandi)
    sebab = pintu.sebab_tolak(bersama.peran, pintu.TIMBANGAN)
    if sebab:
        raise identitas.Tolak(403, sebab)
    profil = await profil_untuk(db, bersama)
    if profil.status != "aktif":
        raise identitas.Tolak(403, identitas.PESAN_NONAKTIF)
    return bersama, profil


async def buat_profil(db: AsyncSession, *, admin: TimbanganAkun, username: str,
                      perangkat_kode: str, ip: str | None = None) -> TimbanganAkun:
    """Admin menautkan akun bersama yang sudah ada ke pos timbang, dengan
    kode perangkatnya. Akunnya sendiri dibuat Super Admin di Pos Produksi /
    Meja — di sini tak ada lagi pembuatan sandi."""
    uname = identitas.normal_username(username)
    bersama = (await db.execute(select(Akun).where(Akun.username == uname))).scalars().first()
    if bersama is None:
        raise LayananError(
            f"Tidak ada akun bersama bernama '{uname}'. Buat akunnya dulu di "
            "Pos Produksi atau Meja (Kelola pengguna, Super Admin), lalu "
            "tautkan di sini dengan kode perangkatnya.")
    sebab = pintu.sebab_tolak(bersama.peran, pintu.TIMBANGAN)
    if sebab:
        raise LayananError(sebab)
    if await profil_untuk(db, bersama, buat=False) is not None:
        raise LayananError(f"{bersama.nama} sudah punya profil pos timbang.")
    kode = (perangkat_kode or "").strip().upper()[:8]
    if not kode:
        raise LayananError("Kode perangkat wajib diisi — ia masuk ke nomor tiket dan "
                           "tercetak di struk. Contoh: P1, P2.")
    kembar = (await db.execute(
        select(TimbanganAkun.nama).where(TimbanganAkun.perangkat_kode == kode)
    )).scalars().first()
    if kembar is not None:
        raise LayananError(f"Kode perangkat {kode} sudah dipakai {kembar}. Dua akun "
                           "berkode sama akan menerbitkan nomor tiket yang sama.")
    profil = await profil_untuk(db, bersama, perangkat_kode=kode)
    if profil.perangkat_kode != kode:
        profil.perangkat_kode = kode
    await catat_audit(
        db, akun=admin, aksi="BUAT_AKUN", entitas="akun", entitas_id=profil.id,
        ringkasan=f"{profil.username} ditautkan ke akun bersama, kode {kode}", ip=ip,
    )
    await db.commit()
    return profil


async def _ubah_profil_bersama(
    db: AsyncSession, *, orang: TimbanganAkun, nama, username, sandi_lama, sandi_baru, ip,
) -> list[str]:
    """Akun saya, untuk profil tertaut: sandi diganti di akun bersama (versi
    sesi naik di semua aplikasi); nama & nama pengguna diubah di Pos Produksi."""
    if (nama and nama.strip() != orang.nama) or (username and username.strip().lower() != orang.username):
        raise LayananError("Nama dan nama pengguna milik akun bersama — ubah di "
                           "Pos Produksi (Pengaturan).")
    if not sandi_baru:
        return []
    bersama = await db.get(Akun, orang.akun_id)
    try:
        versi = await identitas.ganti_sandi(db, bersama, sandi_lama=sandi_lama, sandi_baru=sandi_baru)
    except identitas.Tolak as e:
        raise LayananError(e.pesan) from None
    orang.token_version = versi  # dibaca rute untuk memasang cookie baru
    await catat_audit(db, akun=orang, aksi="UBAH_AKUN", entitas="akun", entitas_id=orang.id,
                      ringkasan=f"{orang.username}: sandi diubah (akun bersama)", ip=ip)
    await db.commit()
    return ["sandi"]


# ═══════════════════════════ Pemeriksaan (SOP butir 6) ═══════════════════

async def buka_pemeriksaan(
    db: AsyncSession, *, akun: TimbanganAkun, trx: TimbanganTransaksi
) -> TimbanganPemeriksaan:
    """Buka lembar pemeriksaan bila belum ada yang terbuka."""
    ada = (await db.execute(
        select(TimbanganPemeriksaan).where(
            TimbanganPemeriksaan.transaksi_id == trx.id,
            TimbanganPemeriksaan.status == PEMERIKSAAN_DIBUKA,
        )
    )).scalars().first()
    if ada is not None:
        return ada

    lembar = TimbanganPemeriksaan(transaksi_id=trx.id, dibuka_oleh_id=akun.id)
    db.add(lembar)
    await db.flush()
    await catat_audit(
        db, akun=akun, aksi="PEMERIKSAAN_DIBUKA", entitas="pemeriksaan",
        entitas_id=lembar.id, ringkasan=f"{trx.kode}: {trx.status_kontrol}",
    )
    return lembar


async def pemeriksaan_transaksi(
    db: AsyncSession, transaksi_id: int
) -> TimbanganPemeriksaan | None:
    return (await db.execute(
        select(TimbanganPemeriksaan)
        .where(TimbanganPemeriksaan.transaksi_id == transaksi_id)
        .order_by(TimbanganPemeriksaan.id.desc())
    )).scalars().first()


async def selesaikan_pemeriksaan(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    lembar: TimbanganPemeriksaan,
    langkah: dict,
    kategori_hasil: str,
    catatan_resolusi: str,
    dilaporkan_ke: str | None = None,
    ip: str | None = None,
) -> TimbanganPemeriksaan:
    """Tutup lembar pemeriksaan dengan catatan resolusi.

    Selesai TIDAK berarti bersih — ia berarti sudah ditelusuri dan hasilnya
    tercatat. Itulah gunanya `kategori_hasil` dan `catatan_resolusi`.
    """
    if not akun.is_admin:
        raise LayananError("Hanya Admin yang boleh menutup pemeriksaan.")
    # ── Sekali ditutup, selesai ──
    #
    # Penutupan kedua menimpa kategori hasil DAN nama penutupnya, jadi lembar
    # yang sudah diselesaikan seseorang bisa ditulis ulang oleh orang lain
    # tanpa satu pun jejak bahwa itu pernah terjadi. Yang benar bukan menutup
    # ulang melainkan membuka pemeriksaan baru. Temuan QA T-23.
    if lembar.status == PEMERIKSAAN_SELESAI:
        raise LayananError(
            "Lembar pemeriksaan ini sudah ditutup. Bila masih ada yang perlu "
            "ditelusuri, buka pemeriksaan baru — jangan menimpa yang lama."
        )
    if not (catatan_resolusi or "").strip():
        raise LayananError("Catatan resolusi wajib diisi.")
    if not kategori_hasil:
        raise LayananError("Kategori hasil wajib dipilih.")

    for kolom in (
        "langkah_ulang_timbang", "langkah_hitung_karung", "langkah_periksa_tara",
        "langkah_periksa_dokumen", "langkah_periksa_muatan", "langkah_lapor",
    ):
        if kolom in langkah:
            setattr(lembar, kolom, langkah[kolom])

    if dilaporkan_ke:
        lembar.dilaporkan_ke = dilaporkan_ke
        lembar.dilaporkan_pada = lembar.dilaporkan_pada or sekarang()

    lembar.kategori_hasil = kategori_hasil
    lembar.catatan_resolusi = catatan_resolusi.strip()
    lembar.status = PEMERIKSAAN_SELESAI
    lembar.ditutup_oleh_id = akun.id
    lembar.ditutup_pada = sekarang()

    await catat_audit(
        db, akun=akun, aksi="PEMERIKSAAN_SELESAI", entitas="pemeriksaan",
        entitas_id=lembar.id,
        ringkasan=f"{kategori_hasil}: {lembar.catatan_resolusi[:120]}", ip=ip,
    )
    await db.commit()
    await db.refresh(lembar)
    return lembar


# ═══════════════════════════ Cetak & foto ═══════════════════════════

def pastikan_boleh_cetak(trx) -> None:
    """Hanya tiket AKTIF dan SELESAI yang boleh keluar sebagai bukti.

    Sampai 11 September 2026 cetak hanya memeriksa kepemilikan tiket, dan
    dua jenis kertas beredar sebagai bukti sah tanpa satu kata pun yang
    menyebut keadaannya: struk tiket yang sudah DIBATALKAN, dan struk tiket
    yang masih TERBUKA — lengkap dengan baris netto yang angkanya belum ada.
    Keduanya ditandatangani pihak luar. Temuan QA T-11.

    Sebabnya ikut disebut. Penolakan yang hanya berbunyi "tidak bisa dicetak"
    membuat petugas mencari jalan lain, dan salah satu jalan itu akan berhasil.
    """
    if trx.status_transaksi != TRX_AKTIF:
        raise LayananError(
            "Tiket ini sudah dibatalkan, jadi tak boleh dicetak sebagai bukti."
        )
    if trx.status_tiket == TIKET_DITUTUP_PAKSA:
        raise LayananError(
            "Tiket ini ditutup paksa tanpa timbang kedua — tak ada angka yang "
            "bisa dijadikan bukti."
        )
    if trx.status_tiket != TIKET_SELESAI:
        raise LayananError(
            "Timbang kedua belum ada, jadi buktinya belum bisa dicetak."
        )


async def cetakan_ke(db: AsyncSession, trx_id: int) -> int:
    """Nomor cetakan BERIKUTNYA — yang akan tertera di kertas yang sedang
    disiapkan. Dihitung sebelum kertasnya keluar, bukan sesudah, karena
    tandanya harus ikut tercetak."""
    return ((await db.execute(
        select(func.max(TimbanganCetak.urutan)).where(
            TimbanganCetak.transaksi_id == trx_id
        )
    )).scalar() or 0) + 1


async def catat_cetak(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    alasan: str | None = None,
    format: str = "80MM",
    ip: str | None = None,
) -> TimbanganCetak:
    """Catat satu kali cetak. Cetak kedua dan seterusnya wajib beralasan."""
    pastikan_boleh_cetak(trx)
    urutan = await cetakan_ke(db, trx.id)

    if urutan > 1 and not (alasan or "").strip():
        raise LayananError("Cetak ulang harus disertai alasan.")

    baris = TimbanganCetak(
        transaksi_id=trx.id, urutan=urutan, ulang=urutan > 1,
        format=(format if format in ("80MM", "NCR") else "80MM"),
        # Nomor revisi tiket SAAT kertas ini keluar. Sengketa dibuka
        # berbulan-bulan kemudian, dan yang ditanya adalah "lembar mana yang
        # dipegang orang itu" — tanpa angka ini pertanyaannya tak berjawab.
        revisi=int(trx.jumlah_revisi or 0),
        alasan=(alasan or None), oleh_id=akun.id,
    )
    db.add(baris)
    await catat_audit(
        db, akun=akun, aksi="CETAK", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=f"cetak ke-{urutan} ({baris.format}, revisi {baris.revisi})"
                  + (f" — {alasan}" if alasan else ""), ip=ip,
    )
    await db.commit()
    return baris


async def simpan_foto(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    nama_file: str,
    mime: str,
    konten: bytes,
    jenis: str = "LAIN",
) -> TimbanganFoto:
    maks_mb = (await setelan.semua(db))["maks_foto_mb"]
    if len(konten) > maks_mb * 1024 * 1024:
        raise LayananError(f"Foto terlalu besar (maksimal {maks_mb:g} MB).")
    foto = TimbanganFoto(
        transaksi_id=trx.id, jenis=jenis, nama_file=nama_file[:255],
        mime=mime or "image/jpeg", ukuran_byte=len(konten), konten=konten,
        diunggah_oleh_id=akun.id,
    )
    db.add(foto)
    await catat_audit(
        db, akun=akun, aksi="UNGGAH_FOTO", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=f"{jenis}: {nama_file}",
    )
    await db.commit()
    return foto


# ═══════════════════════════ Query & filter ═══════════════════════════

@dataclass
class FilterTransaksi:
    dari: date | None = None
    sampai: date | None = None
    supplier_id: int | None = None
    arah: str | tuple[str, ...] | None = None
    jenis_kode: str | None = None
    status_kontrol: str | None = None
    status_tiket: str | None = None
    nomor_polisi: str | None = None
    cari: str | None = None
    sertakan_void: bool = False
    #: Batasi ke transaksi yang ditimbang orang ini (timbang pertama ATAU
    #: kedua). Dipakai untuk petugas, yang hanya berhak melihat hasil
    #: pekerjaannya sendiri.
    petugas_id: int | None = None


def _terapkan_filter(q, f: FilterTransaksi):
    if not f.sertakan_void:
        q = q.where(TimbanganTransaksi.status_transaksi == TRX_AKTIF)
    if f.dari:
        q = q.where(TimbanganTransaksi.tanggal >= f.dari)
    if f.sampai:
        q = q.where(TimbanganTransaksi.tanggal <= f.sampai)
    if f.supplier_id:
        q = q.where(TimbanganTransaksi.supplier_id == f.supplier_id)
    if f.arah:
        # Satu arah atau beberapa — dibutuhkan filter "Retur" di Catatan, yang
        # menggabungkan RETUR_MASUK & RETUR_KELUAR jadi satu pilihan (pembeda
        # keduanya urusan pihak lawan transaksinya, bukan urusan orang yang
        # sedang mencari "transaksi retur apa saja hari ini"). Pola yang sama
        # dengan `status_kontrol` di bawah.
        if isinstance(f.arah, (list, tuple, set)):
            q = q.where(TimbanganTransaksi.arah.in_(sorted(f.arah)))
        else:
            q = q.where(TimbanganTransaksi.arah == f.arah)
    if f.jenis_kode:
        q = q.where(TimbanganTransaksi.jenis_kode == f.jenis_kode)
    if f.status_kontrol:
        # Boleh satu status atau beberapa. Ringkasan memerlukan yang kedua:
        # petaknya menghitung SEMUA status di luar batas, jadi daftarnya harus
        # memuat semuanya juga — kalau tidak, angka dan daftarnya bercerita
        # hal yang berbeda pada layar yang sama.
        if isinstance(f.status_kontrol, (list, tuple, set)):
            q = q.where(TimbanganTransaksi.status_kontrol.in_(
                sorted(f.status_kontrol)))
        else:
            q = q.where(TimbanganTransaksi.status_kontrol == f.status_kontrol)
    if f.status_tiket:
        q = q.where(TimbanganTransaksi.status_tiket == f.status_tiket)
    if f.nomor_polisi:
        q = q.where(TimbanganTransaksi.nomor_polisi == normalisasi_nopol(f.nomor_polisi))
    if f.petugas_id:
        q = q.where(or_(
            TimbanganTransaksi.timbang1_petugas_id == f.petugas_id,
            TimbanganTransaksi.timbang2_petugas_id == f.petugas_id,
        ))
    if f.cari:
        pola = f"%{f.cari.strip()}%"
        q = q.where(or_(
            TimbanganTransaksi.kode.ilike(pola),
            TimbanganTransaksi.nomor_polisi.ilike(pola),
            TimbanganTransaksi.pihak_nama.ilike(pola),
            TimbanganTransaksi.nama_sopir.ilike(pola),
        ))
    return q


@dataclass
class BarisTransaksi:
    trx: TimbanganTransaksi
    supplier_nama: str | None


async def daftar_transaksi(
    db: AsyncSession, f: FilterTransaksi, *, batas: int = 100, offset: int = 0
) -> list[BarisTransaksi]:
    q = _terapkan_filter(
        # Nama pihak diambil dari tabel mana pun yang terisi: supplier untuk
        # barang masuk, pelanggan untuk pengiriman. Satu transaksi tidak
        # pernah mengisi keduanya.
        select(TimbanganTransaksi,
               func.coalesce(Supplier.nama_supplier, Pelanggan.nama_pelanggan))
        .outerjoin(Supplier, Supplier.id == TimbanganTransaksi.supplier_id)
        .outerjoin(Pelanggan, Pelanggan.id == TimbanganTransaksi.pelanggan_id),
        f,
    ).order_by(
        TimbanganTransaksi.tanggal.desc(), TimbanganTransaksi.id.desc()
    ).limit(batas).offset(offset)
    return [BarisTransaksi(trx=t, supplier_nama=n) for t, n in (await db.execute(q)).all()]


async def hitung_transaksi(db: AsyncSession, f: FilterTransaksi) -> int:
    q = _terapkan_filter(
        select(func.count(TimbanganTransaksi.id)).select_from(TimbanganTransaksi), f
    )
    return (await db.execute(q)).scalar_one()


async def tiket_terbuka(db: AsyncSession) -> list[BarisTransaksi]:
    """Truk yang sudah timbang pertama dan belum kembali."""
    return await daftar_transaksi(
        db, FilterTransaksi(status_tiket=TIKET_TERBUKA), batas=200
    )


async def tiket_menganggur(db: AsyncSession) -> list[BarisTransaksi]:
    """Tiket terbuka yang sudah kelewat lama — kandidat ditutup paksa."""
    jam = (await setelan.semua(db))["jam_tiket_menganggur"]
    batas = sekarang() - timedelta(hours=jam)
    q = (
        select(TimbanganTransaksi,
               func.coalesce(Supplier.nama_supplier, Pelanggan.nama_pelanggan))
        .outerjoin(Supplier, Supplier.id == TimbanganTransaksi.supplier_id)
        .outerjoin(Pelanggan, Pelanggan.id == TimbanganTransaksi.pelanggan_id)
        .where(
            TimbanganTransaksi.status_tiket == TIKET_TERBUKA,
            TimbanganTransaksi.status_transaksi == TRX_AKTIF,
            TimbanganTransaksi.timbang1_waktu_sistem < batas,
        )
        .order_by(TimbanganTransaksi.timbang1_waktu_sistem)
    )
    return [BarisTransaksi(trx=t, supplier_nama=n) for t, n in (await db.execute(q)).all()]


async def ambil_transaksi(
    db: AsyncSession, transaksi_id: int
) -> BarisTransaksi | None:
    baris = (await db.execute(
        select(TimbanganTransaksi,
               func.coalesce(Supplier.nama_supplier, Pelanggan.nama_pelanggan))
        .outerjoin(Supplier, Supplier.id == TimbanganTransaksi.supplier_id)
        .outerjoin(Pelanggan, Pelanggan.id == TimbanganTransaksi.pelanggan_id)
        .where(TimbanganTransaksi.id == transaksi_id)
    )).first()
    if baris is None:
        return None
    return BarisTransaksi(trx=baris[0], supplier_nama=baris[1])


def ke_ringkas(baris: list[BarisTransaksi]) -> list[logic.TransaksiRingkas]:
    """Bentuk yang dipakai deteksi pola & skor — tanpa objek DB."""
    hasil = []
    for b in baris:
        t = b.trx
        if t.selisih_kg is None or t.status_kontrol is None:
            continue
        selisih = float(t.selisih_kg or 0)
        # Batas yang relevan adalah batas DI ARAH selisihnya. Untuk aturan yang
        # tidak simetris — gabah kering boleh lebih, kiriman tidak boleh kurang
        # — memakai satu angka saja akan salah menilai.
        if selisih < 0:
            batas = abs(float(t.batas_bawah_kg)) if t.batas_bawah_kg is not None else 0.0
        else:
            batas = float(t.batas_atas_kg) if t.batas_atas_kg is not None else 0.0
        hasil.append(logic.TransaksiRingkas(
            tanggal=t.tanggal,
            selisih_kg=selisih,
            selisih_persen=float(t.selisih_persen or 0),
            batas_kg=batas,
            berat_barang_kg=float(t.berat_barang_kg or 0),
            berat_acuan_kg=float(t.berat_acuan_kg or 0),
            nomor_polisi=t.nomor_polisi,
            pihak_id=t.supplier_id,
            pihak_nama=b.supplier_nama or (t.pihak_nama or ""),
            dikoreksi=bool(t.jumlah_revisi),
            kode=t.kode,
        ))
    return hasil


# ═══════════════════════════ Ringkasan & monitoring ═══════════════════════

@dataclass
class RingkasanDashboard:
    jumlah: int = 0
    tiket_terbuka: int = 0
    perlu_periksa: int = 0
    pemeriksaan_terbuka: int = 0
    #: Dipisah per arah sejak 11 September 2026. Satu angka yang menjumlahkan
    #: gabah MASUK, beras KELUAR, jasa timbang, dan transfer internal tidak
    #: berarti apa-apa — dan yang membacanya mengira itu jumlah gabah yang
    #: diterima hari itu. Temuan QA T-26.
    masuk_kg: float = 0.0
    keluar_kg: float = 0.0
    #: Dipertahankan demi pemanggil lama; isinya masuk + keluar saja, TANPA
    #: jasa timbang dan transfer internal.
    total_barang_kg: float = 0.0
    total_selisih_kg: float = 0.0


async def daftar_pemeriksaan_terbuka(db: AsyncSession) -> list[BarisTransaksi]:
    """Lembar pemeriksaan yang belum ditutup, beserta transaksinya.

    Dipakai Ringkasan supaya angkanya bisa DIJANGKAU. Sebelumnya jumlahnya
    hanya disebut sebagai teks polos, sementara daftar di bawahnya cuma memuat
    transaksi yang STATUSNYA masih menuntut pemeriksaan — sehingga lembar yang
    angkanya sudah dikoreksi tetap terhitung tetapi tidak muncul di mana pun.
    Justru lembar itulah yang paling perlu ditutup, dan justru itu yang tidak
    bisa ditemukan.
    """
    q = (
        select(TimbanganTransaksi,
               func.coalesce(Supplier.nama_supplier, Pelanggan.nama_pelanggan))
        .join(TimbanganPemeriksaan,
              TimbanganPemeriksaan.transaksi_id == TimbanganTransaksi.id)
        .outerjoin(Supplier, Supplier.id == TimbanganTransaksi.supplier_id)
        .outerjoin(Pelanggan, Pelanggan.id == TimbanganTransaksi.pelanggan_id)
        .where(TimbanganPemeriksaan.status != PEMERIKSAAN_SELESAI)
        .order_by(TimbanganPemeriksaan.id)
    )
    return [BarisTransaksi(trx=t, supplier_nama=n)
            for t, n in (await db.execute(q)).all()]


async def ringkasan_dashboard(
    db: AsyncSession, f: FilterTransaksi
) -> RingkasanDashboard:
    baris = (await db.execute(_terapkan_filter(
        select(
            func.count(TimbanganTransaksi.id),
            func.coalesce(func.sum(TimbanganTransaksi.berat_barang_kg), 0),
            func.coalesce(func.sum(TimbanganTransaksi.selisih_kg), 0),
        ).select_from(TimbanganTransaksi),
        f,
    ))).one()

    perlu = (await db.execute(_terapkan_filter(
        select(func.count(TimbanganTransaksi.id)).select_from(TimbanganTransaksi), f
    ).where(
        TimbanganTransaksi.status_kontrol.in_(sorted(logic.STATUS_WAJIB_PERIKSA))
    ))).scalar_one()

    terbuka = (await db.execute(_terapkan_filter(
        select(func.count(TimbanganTransaksi.id)).select_from(TimbanganTransaksi), f
    ).where(TimbanganTransaksi.status_tiket == TIKET_TERBUKA))).scalar_one()

    lembar = (await db.execute(
        select(func.count(TimbanganPemeriksaan.id))
        .where(TimbanganPemeriksaan.status == PEMERIKSAAN_DIBUKA)
    )).scalar_one()

    # Dijumlah PER ARAH. Jasa timbang (BEBAS) dan transfer internal sengaja
    # tak ikut di mana pun: barangnya tak masuk dan tak keluar, jadi
    # menjumlahkannya ke salah satu sisi membuat angka itu berbohong.
    per_arah = dict((await db.execute(_terapkan_filter(
        select(TimbanganTransaksi.arah,
               func.coalesce(func.sum(TimbanganTransaksi.berat_barang_kg), 0))
        .select_from(TimbanganTransaksi), f,
    ).group_by(TimbanganTransaksi.arah))).all())

    masuk = float(per_arah.get(logic.MASUK, 0) or 0) + \
        float(per_arah.get(logic.RETUR_MASUK, 0) or 0)
    keluar = float(per_arah.get(logic.KELUAR, 0) or 0) + \
        float(per_arah.get(logic.RETUR_KELUAR, 0) or 0)

    return RingkasanDashboard(
        jumlah=baris[0],
        tiket_terbuka=terbuka,
        perlu_periksa=perlu,
        pemeriksaan_terbuka=lembar,
        masuk_kg=masuk,
        keluar_kg=keluar,
        total_barang_kg=masuk + keluar,
        total_selisih_kg=float(baris[2] or 0),
    )


@dataclass
class BarisMonitoring:
    supplier_id: int
    nama: str
    jumlah_transaksi: int
    skor: logic.SkorPihak | None
    pola: list[logic.Pola]
    status_saat_ini: str
    status_disarankan: str


#: Berapa baris dibaca sekali jalan, dan pagar terakhirnya.
#:
#: Halaman kecil menjaga pemakaian memori; pagar besar mencegah satu layar
#: menghabiskan menit-menit bila rentang tanggalnya dibiarkan seluas mungkin.
HALAMAN_MONITORING = 1_000
BATAS_MONITORING = 50_000


async def monitoring_supplier(
    db: AsyncSession, f: FilterTransaksi, *, minimal_transaksi: int = 3
) -> list[BarisMonitoring]:
    """Skor & pola per pihak. Bahasa hasilnya selalu 'perlu diperiksa',
    tidak pernah menuduh."""
    # ── Dibaca SELURUHNYA, bertahap — bukan dipotong diam-diam di 5.000 ──
    #
    # Batas lama memotong tanpa satu kata pun. Pada 6.000 tiket, seribu di
    # antaranya hilang dari hitungan, dan skor pemasok yang keluar dihitung
    # dari sebagian data — angka yang tampak sah dan tidak benar. Yang paling
    # mungkin terpotong justru yang paling lama, yaitu riwayat yang membuat
    # pola terlihat. Temuan QA T-22.
    #
    # Dibaca per halaman supaya yang ada di memori sekali waktu tetap
    # terbatas, dan foto BLOB-nya kini tak ikut termuat (`deferred`).
    semua: list[BarisTransaksi] = []
    halaman = 0
    while True:
        potong = await daftar_transaksi(db, f, batas=HALAMAN_MONITORING,
                                        offset=halaman * HALAMAN_MONITORING)
        semua.extend(potong)
        if len(potong) < HALAMAN_MONITORING:
            break
        halaman += 1
        if halaman * HALAMAN_MONITORING >= BATAS_MONITORING:
            # Pagar terakhir, dan ia BERBUNYI — bukan memotong diam-diam.
            log.warning(
                "Monitoring pemasok berhenti di %s tiket; masih ada sisanya. "
                "Persempit rentang tanggalnya.", BATAS_MONITORING)
            break

    per_supplier: dict[int, list[BarisTransaksi]] = {}
    nama: dict[int, str] = {}
    for b in semua:
        if b.trx.supplier_id is None:
            continue
        per_supplier.setdefault(b.trx.supplier_id, []).append(b)
        nama[b.trx.supplier_id] = b.supplier_nama or "(tanpa nama)"

    profil = {
        p.supplier_id: p for p in (await db.execute(
            select(TimbanganSupplierProfil)
        )).scalars()
    }

    hasil: list[BarisMonitoring] = []
    for supplier_id, baris in per_supplier.items():
        if len(baris) < minimal_transaksi:
            continue
        ringkas = ke_ringkas(baris)
        skor = logic.hitung_skor_pihak(ringkas)
        pola = logic.deteksi_pola(ringkas)
        hasil.append(BarisMonitoring(
            supplier_id=supplier_id,
            nama=nama[supplier_id],
            jumlah_transaksi=len(ringkas),
            skor=skor,
            pola=pola,
            status_saat_ini=(
                profil[supplier_id].status_monitoring
                if supplier_id in profil else "AKTIF"
            ),
            status_disarankan=logic.status_pihak_disarankan(skor, pola),
        ))
    hasil.sort(key=lambda b: (b.skor.skor_total if b.skor else 100))
    return hasil


async def simpan_skor(db: AsyncSession, baris: list[BarisMonitoring]) -> int:
    """Simpan cache skor 'TERKINI' — dihitung ulang, bukan ditumpuk."""
    disimpan = 0
    for b in baris:
        if b.skor is None:
            continue
        lama = (await db.execute(
            select(TimbanganSkorSupplier).where(
                TimbanganSkorSupplier.supplier_id == b.supplier_id,
                TimbanganSkorSupplier.periode == "TERKINI",
            )
        )).scalars().first()
        data = dict(
            skor_total=b.skor.skor_total,
            kategori=b.skor.kategori,
            jumlah_transaksi=b.jumlah_transaksi,
            komponen_json=json.dumps(b.skor.komponen, ensure_ascii=False),
            pola_json=json.dumps(
                [
                    {"kode": p.kode, "judul": p.judul,
                     "keterangan": p.keterangan, "tingkat": p.tingkat}
                    for p in b.pola
                ],
                ensure_ascii=False,
            ),
            dihitung_pada=sekarang(),
        )
        if lama is None:
            db.add(TimbanganSkorSupplier(
                supplier_id=b.supplier_id, periode="TERKINI", **data
            ))
        else:
            for kolom, nilai in data.items():
                setattr(lama, kolom, nilai)
        disimpan += 1
    await db.commit()
    return disimpan

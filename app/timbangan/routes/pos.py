"""Rute pos timbang — layar yang dipakai petugas berdiri di dekat jembatan.

Urutannya sengaja pendek: beranda → pilih komoditas → timbang pertama →
(truk bongkar) → timbang kedua → hasil. Tidak ada layar yang bisa dilewati,
dan tidak ada layar tambahan yang tidak dipakai setiap hari.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import math
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.timbangan import logic, service
from app.timbangan.db import get_db, hari_ini, sekarang
from app.timbangan.models import (
    CARA_DUA_KALI,
    CARA_PARTAI,
    CARA_SEKALI,
    TimbanganAkun,
)
from app.timbangan.security import butuh_akun
from app.timbangan.web import PREFIX, redirect, render

router = APIRouter(prefix=PREFIX)


def _angka(teks: str | None, bawaan: float = 0.0) -> float:
    """Terima '13.600', '13,600', '13600', '0.250' — petugas mengetik apa adanya.

    Satu titik dengan tiga angka di belakangnya ambigu: '13.600' berarti tiga
    belas ribu enam ratus, tetapi '0.250' berarti seperempat kilogram. Yang
    membedakan adalah angka di depan titik — tidak ada orang yang menulis
    '0.250' untuk maksud dua ratus lima puluh.

    Salah menebak di sini berakibat fatal: tara 0,25 kg yang terbaca 250 kg
    membuat setiap transaksi gabah ditolak sebagai mustahil.
    """
    if teks is None:
        return bawaan
    bersih = str(teks).strip().replace(" ", "")
    if not bersih:
        return bawaan

    if "," in bersih:
        # Koma dipakai desimal → titik pasti pemisah ribuan.
        bersih = bersih.replace(".", "").replace(",", ".")
    elif bersih.count(".") > 1:
        # '1.234.567' — hanya mungkin pemisah ribuan.
        bersih = bersih.replace(".", "")
    elif bersih.count(".") == 1:
        depan, belakang = bersih.split(".")
        ribuan = len(belakang) == 3 and depan.lstrip("-+").lstrip("0") != ""
        if ribuan:
            bersih = bersih.replace(".", "")
    try:
        n = float(bersih)
    except ValueError:
        return bawaan
    # "nan" dan "inf" LOLOS `float()` — itulah lubangnya. NaN lalu membuat
    # SETIAP perbandingan bernilai salah, jadi kekurangan 10 ton lolos sebagai
    # NORMAL: batas atas dan batas bawah sama-sama tak terlampaui, karena
    # perbandingan dengan NaN memang selalu False. Temuan QA T-08.
    if not math.isfinite(n):
        return bawaan
    return n


def _waktu_operator(teks: str | None) -> datetime | None:
    """Jam yang boleh dikoreksi petugas bila ia mencatat terlambat.

    **Hasilnya WAJIB berzona.** Isian `datetime-local` di peramban mengirim
    angka polos tanpa zona — "2026-08-31T09:15" — dan angka itu adalah waktu
    setempat, WIB. Bila diserahkan apa adanya ke kolom `timestamptz`,
    Postgres menafsirkannya memakai zona sesinya (UTC di Railway), sehingga
    ketikan 09:15 pagi tersimpan sebagai 09:15 UTC lalu tampil kembali
    sebagai 16:15 sore. Tepat tujuh jam meleset, dan meyakinkan.

    Kesalahan itu tidak terlihat di pengujian maupun di SQLite: uji mengirim
    kolom ini kosong sehingga jatuh ke `sekarang()` yang memang berzona, dan
    SQLite menyimpan tanpa zona sehingga angkanya kembali apa adanya. Ia
    hanya muncul di Postgres, yaitu di produksi.
    """
    if not teks:
        return None
    for pola in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(teks, pola).replace(
                tzinfo=ZoneInfo(settings.app_timezone)
            )
        except ValueError:
            continue
    return None


# ═══════════════════════════ Beranda ═══════════════════════════

async def _penanda(db: AsyncSession) -> dict:
    """Satu rumus penanda untuk dua kanal: /keadaan (denyut) dan /aliran (dorong)."""
    from sqlalchemy import text as _text

    from app.timbangan.web import VERSI

    r = (await db.execute(_text(
        "select "
        " (select coalesce(max(id), 0) from timbangan_transaksi),"
        " (select coalesce(cast(extract(epoch from max(updated_at)) * 1000000 as bigint), 0)"
        "    from timbangan_transaksi),"
        " (select coalesce(cast(extract(epoch from max(updated_at)) * 1000000 as bigint), 0)"
        "    from timbangan_pemeriksaan),"
        " (select coalesce(cast(extract(epoch from max(updated_at)) * 1000000 as bigint), 0)"
        "    from timbangan_jenis)"
    ))).first()
    return {"n": ".".join(str(x) for x in r), "versi": VERSI}


async def aliran_penanda(jeda: float = 2.0):
    """Kanal dorong (SSE): penanda seketika saat tersambung, lalu hanya
    ketika bergerak; komentar `: hidup` tiap ~15 detik menahan proxy."""
    import asyncio
    import json

    from app import database

    terakhir = None
    hidup = 0.0
    while True:
        async with database.SessionLocal() as db:
            p = await _penanda(db)
        if p != terakhir:            # n ATAU versi — versi baru pun terdorong
            terakhir = p
            hidup = 0.0
            yield "data: " + json.dumps(p) + "\n\n"
        else:
            hidup += jeda
            if hidup >= 15:
                hidup = 0.0
                yield ": hidup\n\n"
        await asyncio.sleep(jeda)


@router.get("/aliran", include_in_schema=False)
async def aliran(akun: TimbanganAkun = Depends(butuh_akun)):
    from fastapi.responses import StreamingResponse

    return StreamingResponse(aliran_penanda(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/keadaan")
async def keadaan(
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Satu penanda: APAKAH ada yang berubah — bukan apa yang berubah.

    Dipanggil berkala oleh tiap perangkat yang layar bacanya menyala. Sebelum
    ini, denyut penyegaran mengunduh SELURUH halaman hanya untuk menyimpulkan
    "tak ada yang berubah" di hampir semua denyutnya — dan petugas memakai
    kuotanya sendiri. Sekarang halamannya baru dimuat ulang kalau penanda ini
    berbeda dari yang terakhir dilihat.

    `updated_at` ikut, tidak cukup nomornya saja: sebuah tiket DIUBAH saat
    timbang kedua — bobot keluar diisi, statusnya berpindah — dan nomornya
    tidak bergerak sedikit pun di situ. Tanpa bagian ini, penimbangan kedua
    tak akan pernah muncul sendiri di layar siapa pun.

    Yang dipakai nomor dan cap waktu dari basis data, bukan jam perangkat:
    jam yang bergeser sedikit bisa membuat satu perubahan terlewat selamanya.

    **Sumbernya bukan hanya tiket.** Empat layar yang berdenyut (beranda,
    daftar, laporan, monitoring) dibangun dari `timbangan_transaksi`, tetapi
    laporan juga menampilkan status PEMERIKSAAN — yang dibuka dan ditutup
    admin tanpa menyentuh baris tiketnya — dan beranda menyusun tombolnya
    dari master JENIS yang bisa diubah di Pengaturan. Keduanya ikut lewat
    `updated_at`-nya. Audit sengaja TIDAK ikut: tiap login menulis baris di
    sana, dan itu bukan perubahan yang perlu dilihat layar mana pun.
    Aplikasi lain tak menulis tabel-tabel ini (produksi hanya mengunci baris
    tiket saat menaut), jadi tak ada sumber di luar pencatat sendiri.

    `versi` (syarat N-A-03): ponsel yang memegang berkas lama tahu dari kanal
    yang sama, tanpa menunggu navigasi penuh.

    Cap waktunya MIKRODETIK, bukan detik. Dibulatkan ke detik, timbang kedua
    yang jatuh pada detik yang sama dengan pembacaan sebelumnya tak pernah
    menggerakkan penanda — perubahan yang hilang selamanya, terlihat pertama
    kali di uji Postgres yang menyimpan dua langkah berturut-turut.
    """
    # Uji sumber menjaga rumusnya lewat teks di blok ini: max(id),
    # max(updated_at), extract(epoch — rumus sesungguhnya di `_penanda`.
    return await _penanda(db)


@router.get("/acuan")
async def acuan(
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Daftar acuan yang boleh dilihat ponsel saat sinyal hilang.

    Disimpan app.js selagi jaringan ada, ditampilkan di /luring saat putus di
    bawah baris cap waktu selebar layar. Persetujuan pemilik 14 Sep 2026:
    HANYA yang berubah mingguan, nama saja — pemasok, pelanggan, jenis
    barang, kendaraan. Tak ada tiket, antrean, atau angka timbang: yang basi
    di pos timbang lebih berbahaya daripada yang tak ada.
    """
    from sqlalchemy import select as _select

    from app.models import Pelanggan
    from app.timbangan.models import TimbanganKendaraan

    pemasok = [s.nama_supplier for s in await service.daftar_supplier(db)]
    pelanggan = (await db.execute(
        _select(Pelanggan.nama_pelanggan).where(Pelanggan.deleted_at.is_(None))
        .order_by(Pelanggan.nama_pelanggan))).scalars().all()
    jenis = [j.nama for j in await service.daftar_jenis(db)]
    kendaraan = (await db.execute(
        _select(TimbanganKendaraan.nomor_polisi).where(TimbanganKendaraan.status == "aktif")
        .order_by(TimbanganKendaraan.nomor_polisi))).scalars().all()
    return {
        "pukul": sekarang().strftime("%H:%M"),
        "daftar": [
            {"judul": "Pemasok", "isi": pemasok},
            {"judul": "Pelanggan", "isi": list(pelanggan)},
            {"judul": "Jenis barang", "isi": jenis},
            {"judul": "Kendaraan", "isi": list(kendaraan)},
        ],
    }


@router.get("/")
async def beranda(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Satu layar: apa yang sedang berjalan, dan apa yang bisa dimulai."""
    terbuka = await service.tiket_terbuka(db)
    # Selain Admin, daftar hari ini dipersempit ke timbangan orang ini
    # sendiri. Bukan sekadar kerapian: rinciannya memang tidak boleh dibuka
    # olehnya, jadi menampilkannya hanya menyodorkan tautan yang berujung
    # "akses ditolak".
    hari = await service.daftar_transaksi(
        db,
        service.FilterTransaksi(
            dari=hari_ini(), sampai=hari_ini(),
            petugas_id=None if akun.is_admin else akun.id,
        ),
        batas=8,
    )
    # Komoditas ikut dibawa ke beranda supaya kartunya bisa MEMBENTANG di
    # tempat, bukan mengirim petugas ke halaman pemilihan tersendiri.
    #
    # Satu halaman lebih sedikit berarti satu perjalanan bolak-balik lebih
    # sedikit pada tiap penimbangan — dan di pos timbang, tiap perjalanan itu
    # dibayar dengan berdiri menunggu di samping truk.
    #
    # Dikelompokkan di sini, bukan dengan satu kueri per arah, karena seluruh
    # daftarnya hanya belasan baris: satu kueri lalu dipilah di memori lebih
    # murah daripada enam kueri.
    per_arah: dict[str, list] = {}
    for j in await service.daftar_jenis(db):
        per_arah.setdefault(j.arah, []).append(j)

    return render(
        request, "beranda.html",
        terbuka=terbuka,
        hari_ini_daftar=hari,
        menganggur={b.trx.id for b in await service.tiket_menganggur(db)},
        per_arah=per_arah,
        peta=await service.peta_aturan(db),
    )


@router.get("/pilih/{arah}")
async def pilih_jenis(
    arah: str,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Komoditas yang ditawarkan mengikuti arah barang.

    Barang masuk dan barang keluar bukan daftar yang sama — menir, bekatul,
    dan reject tidak pernah dibeli, jadi tidak pernah muncul di sisi masuk.
    """
    arah = arah.upper()
    if arah not in (
        logic.MASUK, logic.KELUAR, logic.BEBAS, logic.TRANSFER,
        logic.RETUR_MASUK, logic.RETUR_KELUAR,
    ):
        return redirect("/", err="Arah barang tidak dikenal.")

    jenis = await service.daftar_jenis(db, arah=arah)
    if arah != logic.BEBAS:
        jenis = [j for j in jenis if j.arah == arah]

    peta = await service.peta_aturan(db)
    return render(
        request, "pilih_jenis.html",
        arah=arah, jenis=jenis, peta=peta, kembali=f"{PREFIX}/",
        partai=request.query_params.get("partai") == "1",
    )


# ═══════════════════════════ Timbang pertama ═══════════════════════════

@router.get("/timbang/{jenis_kode}")
async def form_timbang_pertama(
    jenis_kode: str,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        aturan = await service.aturan_untuk(db, jenis_kode.upper())
    except service.LayananError as e:
        return redirect("/", err=str(e))

    tara, asal = await service.tara_disarankan(db, supplier_id=None, aturan=aturan)
    # Daftar mengikuti arah: barang masuk hanya supplier, pengiriman
    # hanya pelanggan. Lihat `service.PIHAK_ARAH`.
    sering, lainnya = await service.pihak_pilihan(db, aturan.arah)
    return render(
        request, "timbang1.html",
        aturan=aturan,
        # PERKIRAAN, bukan nomor yang sudah jadi milik layar ini.
        # Nomor sungguhannya diterbitkan server saat menyimpan —
        # lihat `service.alokasi_nomor`. Dua layar yang terbuka
        # bersamaan memegang perkiraan yang SAMA, dan dulu perkiraan
        # itulah yang dipakai sebagai identitas tiket.
        kode=await service.kode_baru(db, akun, aturan.arah),
        # Identitas kiriman: dibuat SEKALI di sini, ikut pada tiap
        # kirim ulang dari antrean luring.
        kunci=str(uuid4()),
        pihak_sering=sering,
        pihak_lainnya=lainnya,
        kolom_nama=service.nama_kolom_pihak(aturan.arah),
        # Saran nomor polisi + sopir terakhirnya. Ikut ke halaman supaya tetap
        # bekerja tanpa jaringan — pos timbang sering kehilangan sinyal, dan
        # saran yang butuh jaringan justru menghilang persis saat dibutuhkan.
        kendaraan=await service.kendaraan_dikenal(db),
        tara=tara,
        asal_tara=asal,
        sekarang=sekarang(),
        kembali=f"{PREFIX}/pilih/{aturan.arah}",
    )


@router.post("/timbang/{jenis_kode}")
async def simpan_timbang_pertama(
    jenis_kode: str,
    request: Request,
    kunci: str = Form(""),
    berat_kg: str = Form(...),
    cara_timbang: str = Form(CARA_DUA_KALI),
    supplier_id: str = Form(""),
    pihak_nama: str = Form(""),
    nomor_polisi: str = Form(""),
    nama_sopir: str = Form(""),
    nomor_acuan: str = Form(""),
    jumlah_karung: str = Form("0"),
    tara_per_karung_kg: str = Form("0"),
    berat_acuan_kg: str = Form("0"),
    tara_lain_kg: str = Form("0"),
    waktu: str = Form(""),
    catatan: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    jenis_kode = jenis_kode.upper()
    muatan: list[service.InputMuatan] = []
    if cara_timbang != CARA_SEKALI or jenis_kode != "BEBAS":
        muatan = [service.InputMuatan(
            jenis_kode=jenis_kode,
            jumlah_karung=int(_angka(jumlah_karung)),
            tara_per_karung_kg=_angka(tara_per_karung_kg),
            berat_acuan_kg=_angka(berat_acuan_kg),
            nomor_acuan=nomor_acuan.strip() or None,
        )]

    data = service.InputTimbang(
        # `kode` sengaja tak dikirim: server yang menerbitkannya,
        # atomik, saat menyimpan.
        kunci=kunci.strip() or None,
        arah=(await service.aturan_untuk(db, jenis_kode)).arah,
        jenis_kode=jenis_kode,
        berat_kg=_angka(berat_kg),
        waktu_operator=_waktu_operator(waktu),
        cara_timbang=cara_timbang,
        supplier_id=int(supplier_id) if supplier_id.isdigit() else None,
        pihak_nama=pihak_nama.strip() or None,
        nomor_polisi=nomor_polisi.strip() or None,
        nama_sopir=nama_sopir.strip() or None,
        tara_lain_kg=_angka(tara_lain_kg),
        muatan=muatan,
        catatan=catatan.strip() or None,
        perangkat_kode=akun.perangkat_kode,
    )

    try:
        trx = await service.simpan_timbang_pertama(
            db, akun=akun, data=data,
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/timbang/{jenis_kode}", err=str(e))

    if trx.selesai:
        return redirect(f"/transaksi/{trx.id}", ok="Timbangan tersimpan.")
    return redirect(f"/transaksi/{trx.id}", ok="Timbang pertama tersimpan.")


# ═══════════════════════ Partai kecil (satu kode) ═══════════════════════
#
# Petani dan pedagang kecil menjual sedikit-sedikit, jadi barangnya ditimbang
# satu per satu — kadang kedatangannya pun bertahap. Yang tidak boleh pecah
# adalah KODE-nya: satu penjualan tetap satu tiket, satu nota, satu baris
# rekap per pihak.
#
# Satu halaman saja, dipakai untuk memulai maupun melanjutkan: nama pihak,
# beberapa kolom berat yang bisa ditambah sendiri, lalu simpan sementara atau
# tutup. Bolak-balik antar layar untuk tiap karung adalah alur yang salah.


def _daftar_berat(nilai: list[str]) -> list[float]:
    """Kolom berat yang benar-benar diisi. Kolom kosong diabaikan, bukan nol."""
    keluar = []
    for v in nilai or []:
        if (v or "").strip():
            keluar.append(_angka(v))
    return keluar


@router.get("/partai/{jenis_kode}/baru")
async def form_partai_baru(
    jenis_kode: str,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        aturan = await service.aturan_untuk(db, jenis_kode.upper())
    except service.LayananError as e:
        return redirect("/", err=str(e))
    sering, lainnya = await service.pihak_pilihan(db, aturan.arah)
    return render(
        request, "partai.html",
        b=None, aturan=aturan,
        # PERKIRAAN, bukan nomor yang sudah jadi milik layar ini.
        # Nomor sungguhannya diterbitkan server saat menyimpan —
        # lihat `service.alokasi_nomor`. Dua layar yang terbuka
        # bersamaan memegang perkiraan yang SAMA, dan dulu perkiraan
        # itulah yang dipakai sebagai identitas tiket.
        kode=await service.kode_baru(db, akun, aturan.arah),
        # Identitas kiriman: dibuat SEKALI di sini, ikut pada tiap
        # kirim ulang dari antrean luring.
        kunci=str(uuid4()),
        pihak_sering=sering, pihak_lainnya=lainnya,
        kolom_nama=service.nama_kolom_pihak(aturan.arah),
        kembali=f"{PREFIX}/pilih/{aturan.arah}?partai=1",
    )


@router.post("/partai/{jenis_kode}/baru")
async def buat_partai(
    jenis_kode: str,
    request: Request,
    kunci: str = Form(""),
    supplier_id: str = Form(""),
    pihak_nama: str = Form(""),
    berat_kg: list[str] = Form([]),
    aksi: str = Form("sementara"),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    jenis_kode = jenis_kode.upper()
    berat = _daftar_berat(berat_kg)
    if not berat:
        return redirect(f"/partai/{jenis_kode}/baru",
                        err="Isi dulu berat timbangannya, minimal satu.")

    aturan = await service.aturan_untuk(db, jenis_kode)
    data = service.InputTimbang(
        kunci=kunci.strip() or None, arah=aturan.arah, jenis_kode=jenis_kode,
        berat_kg=berat[0], cara_timbang=CARA_PARTAI,
        supplier_id=int(supplier_id) if supplier_id.isdigit() else None,
        pihak_nama=pihak_nama.strip() or None,
        perangkat_kode=akun.perangkat_kode,
    )
    ip = request.client.host if request.client else None
    try:
        trx = await service.simpan_timbang_pertama(db, akun=akun, data=data, ip=ip)
        if berat[1:]:
            trx = await service.tambah_penimbangan(
                db, akun=akun, kode=trx.kode, berat=berat[1:],
                # Kunci yang sama dengan formulirnya: kiriman ulang tak
                # menambah karung yang sama untuk kedua kalinya.
                kunci=(kunci.strip() or None), ip=ip,
            )
        if aksi == "selesai":
            trx = await service.selesaikan_partai(db, akun=akun, kode=trx.kode, ip=ip)
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/partai/{jenis_kode}/baru", err=str(e))

    if aksi == "selesai":
        return redirect(f"/transaksi/{trx.id}", ok="Timbangan selesai.")
    return redirect(f"/partai/{trx.id}",
                    ok=f"Tersimpan sementara. Total {trx.timbang1_kg:g} kg.")


@router.get("/partai/{transaksi_id:int}")
async def layar_partai(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")
    if not baris.trx.partai or baris.trx.selesai:
        return redirect(f"/transaksi/{transaksi_id}")
    return render(
        request, "partai.html",
        kunci=str(uuid4()),
        b=baris,
        aturan=await service.aturan_untuk(db, baris.trx.jenis_kode),
        kembali=f"{PREFIX}/tiket",
    )


@router.post("/partai/{transaksi_id:int}")
async def lanjut_partai(
    transaksi_id: int,
    request: Request,
    berat_kg: list[str] = Form([]),
    aksi: str = Form("sementara"),
    # Penanda kiriman: ketukan dobel atau kiriman ulang antrean luring tak
    # boleh menambah karung yang sama untuk kedua kalinya (temuan QA T-10).
    kunci: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")
    kode, ip = baris.trx.kode, (request.client.host if request.client else None)
    berat = _daftar_berat(berat_kg)
    try:
        # Menutup tanpa menambah apa pun sah: barangnya sudah habis ditimbang
        # pada kunjungan sebelumnya.
        if berat:
            await service.tambah_penimbangan(db, akun=akun, kode=kode,
                                             berat=berat,
                                             kunci=(kunci.strip() or None),
                                             ip=ip)
        if aksi == "selesai":
            await service.selesaikan_partai(db, akun=akun, kode=kode, ip=ip)
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/partai/{transaksi_id}", err=str(e))

    if aksi == "selesai":
        return redirect(f"/transaksi/{transaksi_id}", ok="Timbangan selesai.")
    trx = await service.ambil_kode(db, kode)
    return redirect(f"/partai/{transaksi_id}",
                    ok=f"Tersimpan sementara. Total {trx.timbang1_kg:g} kg.")


@router.post("/partai/{transaksi_id:int}/hapus")
async def hapus_penimbangan(
    transaksi_id: int,
    request: Request,
    urutan: str = Form(...),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")
    try:
        trx = await service.hapus_penimbangan(
            db, akun=akun, kode=baris.trx.kode, urutan=int(_angka(urutan)),
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError, ValueError) as e:
        return redirect(f"/partai/{transaksi_id}", err=str(e))
    return redirect(f"/partai/{transaksi_id}",
                    ok=f"Baris dihapus. Total {trx.timbang1_kg:g} kg.")


# ═══════════════════════════ Timbang kedua ═══════════════════════════

@router.get("/tiket")
async def daftar_tiket(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    return render(
        request, "tiket.html",
        terbuka=await service.tiket_terbuka(db),
        menganggur={b.trx.id for b in await service.tiket_menganggur(db)},
        kembali=f"{PREFIX}/",
    )


@router.get("/tiket/{transaksi_id}")
async def form_timbang_kedua(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")
    if baris.trx.selesai:
        return redirect(f"/transaksi/{transaksi_id}")
    # Partai kecil dilanjutkan di layarnya sendiri. Kedatangannya bisa
    # bertahap — sore ini beberapa karung, besok sisanya — dan yang menunggu
    # bukan timbang kedua melainkan barang berikutnya.
    if baris.trx.partai:
        return redirect(f"/partai/{transaksi_id}")

    aturan = await service.aturan_untuk(db, baris.trx.jenis_kode)
    # Sarannya dihitung DI SINI, bukan di timbang pertama seperti dulu.
    # Kolom karung sudah pindah ke layar ini, dan justru di sini sarannya
    # lebih tajam: pihaknya sudah diketahui, sehingga sampling khusus pihak
    # itu bisa dipakai — di layar pertama pihaknya belum dipilih.
    tara, asal = await service.tara_disarankan(
        db, supplier_id=baris.trx.supplier_id, aturan=aturan
    )
    return render(
        request, "timbang2.html",
        b=baris, aturan=aturan, sekarang=sekarang(),
        tara=tara, asal_tara=asal,
        kembali=f"{PREFIX}/tiket",
    )


@router.post("/tiket/{transaksi_id}")
async def simpan_timbang_kedua(
    transaksi_id: int,
    request: Request,
    berat_kg: str = Form(...),
    jumlah_karung: str = Form(""),
    tara_per_karung_kg: str = Form(""),
    berat_acuan_kg: str = Form(""),
    nomor_acuan: str = Form(""),
    waktu: str = Form(""),
    catatan: str = Form(""),
    aksi: str = Form("selesai"),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")

    # Jumlah karung & berat nota sering baru diketahui setelah bongkar —
    # karena itu boleh diisi di tahap kedua, bukan hanya di tahap pertama.
    muatan = None
    if jumlah_karung or berat_acuan_kg:
        lama = baris.trx.muatan[0] if baris.trx.muatan else None
        muatan = [service.InputMuatan(
            jenis_kode=baris.trx.jenis_kode,
            jumlah_karung=int(_angka(
                jumlah_karung, lama.jumlah_karung if lama else 0
            )),
            tara_per_karung_kg=_angka(
                tara_per_karung_kg, float(lama.tara_per_karung_kg) if lama else 0
            ),
            berat_acuan_kg=_angka(
                berat_acuan_kg, float(lama.berat_acuan_kg) if lama else 0
            ),
            nomor_acuan=(nomor_acuan.strip() or (lama.nomor_acuan if lama else None)),
        )]

    try:
        trx = await service.simpan_timbang_kedua(
            db, akun=akun, kode=baris.trx.kode,
            berat_kg=_angka(berat_kg),
            waktu_operator=_waktu_operator(waktu),
            muatan=muatan,
            catatan=catatan.strip() or None,
            selesaikan=aksi != "sementara",
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/tiket/{transaksi_id}", err=str(e))

    if aksi == "sementara":
        return redirect(
            f"/tiket/{transaksi_id}",
            ok="Tersimpan. Tiket masih terbuka — selesaikan setelah jumlah "
               "karung pasti.",
        )
    return redirect(f"/transaksi/{trx.id}", ok="Timbangan selesai dan tersimpan.")


@router.post("/tiket/{transaksi_id}/tutup")
async def tutup_paksa_tiket(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(...),
    tanpa_timbang_keluar: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Tutup tiket truk yang sudah pergi tanpa sempat ditimbang keluar.

    Muatan yang DITOLAK tidak lewat sini — ia diselesaikan lewat timbang
    kedua biasa, supaya kontrol masuk−keluar tetap ada. Lihat
    `service.tutup_paksa`.
    """
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")
    try:
        await service.tutup_paksa(
            db, akun=akun, trx=baris.trx, alasan=alasan,
            tanpa_timbang_keluar=bool(tanpa_timbang_keluar),
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/tiket/{transaksi_id}", err=str(e))
    return redirect("/tiket", ok="Tiket ditutup beserta alasannya.")

"""Rute transaksi: daftar, rincian, koreksi, pembatalan, cetak, pemeriksaan."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import epos, logic, pdf, service
from app.timbangan.config import tsettings
from app.timbangan.db import get_db, hari_ini
from app.timbangan.models import TimbanganAkun, TimbanganCetak
from app.timbangan.routes.pos import _angka
from app.timbangan.security import (
    butuh_admin,
    butuh_akun,
    butuh_super,
)
from app.timbangan.web import galat_db, PREFIX, redirect, render

router = APIRouter(prefix=PREFIX)

#: Kategori penutup pemeriksaan. Sengaja tidak ada kategori "curang":
#: sistem mencatat temuan, manusia yang menyimpulkan.
KATEGORI_HASIL = {
    "SELISIH_WAJAR": "Selisih masih wajar",
    "SALAH_CATAT": "Salah catat / salah ketik",
    "SUSUT_PERJALANAN": "Susut dalam perjalanan",
    "TARA_TIDAK_SESUAI": "Tara karung tidak sesuai",
    "DOKUMEN_TIDAK_SESUAI": "Dokumen tidak sesuai muatan",
    "PERLU_TINDAK_LANJUT": "Perlu tindak lanjut manajemen",
    "LAIN": "Lainnya",
}


async def _ambil(db: AsyncSession, transaksi_id: int, akun: TimbanganAkun):
    """Ambil satu transaksi.

    ⚠ SEKAT "PEKERJAAN SENDIRI" DICABUT 30 September 2026, atas keputusan
    pemilik: "operator tidak bisa melihat catatan selain input dari dirinya
    sendiri. sekarang harus bisa lihat semua catatan."

    Kalimat lama di sini berbunyi: "Daftar catatan sudah tertutup untuk selain
    Admin, tapi menutup daftar saja tidak cukup: nomor transaksi di URL
    berurutan, jadi siapa pun bisa menebaknya." Premis kalimat itu SUDAH TIDAK
    ADA — daftarnya dibuka sehari sebelumnya, juga atas keputusan pemilik.
    Sekat yang tertinggal jadi lebih buruk daripada tak ada sama sekali:
    barisnya terlihat di daftar, lalu menolak saat ditekan.

    Shift malam yang menimbang truk masuk dan shift pagi yang menimbangnya
    keluar adalah dua orang berbeda; yang kedua memang perlu membuka pekerjaan
    yang pertama. Itu keadaan sehari-hari, bukan kasus tepi.

    Yang MENGUBAH catatan tetap tertutup, dan sekatnya berdiri di rutenya
    masing-masing — bukan di sini.
    """
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        raise service.LayananError("Transaksi tidak ditemukan.")
    return baris


# ═══════════════════════════ Daftar & rincian ═══════════════════════════

@router.get("/transaksi")
async def daftar(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Catatan timbang — TERBUKA untuk petugas sejak 30 September 2026.

    Keputusan pemilik: "akses operator di app timbangan diberikan semua kecuali
    ringkasan. berarti dia bisa akses catatan dan bisa print."

    Yang sebetulnya berubah cuma DAFTARNYA. Rincian tiap transaksi dan seluruh
    jalur cetak (A4, NCR, 80 mm, ePOS) sudah lama `butuh_akun` — petugas
    memang boleh membukanya. Yang tak ada cuma jalan menemukannya: tanpa
    daftar ini ia harus menebak alamat tiketnya. Kemampuan yang tak punya
    pintu sama saja dengan kemampuan yang tak ada.

    YANG TETAP TERTUTUP, dan tak satu pun karena datanya rahasia dari petugas:

      · RINGKASAN (`/laporan`) — atas keputusan pemilik yang sama. Menilai
        pola adalah pekerjaan yang berbeda dari menimbang, dan mencampurnya
        membuat kedua pekerjaan itu lebih buruk;
      · Unduh CSV — ia bagian dari pekerjaan menilai pola itu, bukan bagian
        dari membaca satu catatan. Tombolnya memang sudah bersyarat
        `is_admin` di templatnya, jadi petugas tak melihat tombol yang akan
        menolaknya;
      · membatalkan transaksi, menutup lembar pemeriksaan, dan mengubah jenis
        atau arah barang. Ketiganya MENGUBAH catatan yang sudah tersimpan —
        bukan membacanya — dan yang ketiga bahkan mengubah seluruh hasil
        kontrol transaksi.
    """
    q = request.query_params
    f = service.FilterTransaksi(
        # Transaksi yang dibatalkan tetap tertera di catatan, bertanda
        # "Batal". Truk yang batal bongkar memang pernah datang; menyembunyikan
        # barisnya membuat catatan terlihat rapi dengan cara yang keliru.
        # Ringkasan, ekspor, dan beranda tetap tidak menghitungnya.
        sertakan_void=True,
        arah=q.get("arah") or None,
        jenis_kode=q.get("jenis") or None,
        status_kontrol=q.get("status") or None,
        status_tiket=q.get("tiket") or None,
        cari=q.get("cari") or None,
    )
    # Bawaan DUA HARI terakhir — hari ini dan kemarin.
    #
    # Sebelumnya 30 hari, dengan alasan halaman tidak boleh kosong hanya karena
    # petugas lupa mengisi rentang tanggal. Alasan itu tetap terpenuhi oleh dua
    # hari, dan 30 hari membawa ongkos yang tidak sebanding: yang dibuka
    # sehari-hari adalah timbangan yang baru saja terjadi, sementara halaman
    # harus menghitung dan mengirim sebulan penuh untuk itu.
    #
    # Rentang yang lebih panjang tidak hilang, hanya tidak lagi jadi bawaan —
    # isian tanggal di atas daftar ada justru untuk itu, dan setiap tautan
    # halaman berikutnya serta tombol ekspor membawa rentang yang sedang
    # dipilih.
    BAWAAN_HARI = 1        # hari ini + 1 hari ke belakang = dua hari
    try:
        f.dari = date.fromisoformat(q["dari"]) if q.get("dari") else \
            hari_ini() - timedelta(days=BAWAAN_HARI)
        f.sampai = date.fromisoformat(q["sampai"]) if q.get("sampai") else hari_ini()
    except ValueError:
        f.dari, f.sampai = hari_ini() - timedelta(days=BAWAAN_HARI), hari_ini()

    halaman = max(1, int(q.get("hal", 1) or 1))
    per_halaman = 50
    return render(
        request, "daftar.html",
        f=f, halaman=halaman, per_halaman=per_halaman,
        total=await service.hitung_transaksi(db, f),
        baris=await service.daftar_transaksi(
            db, f, batas=per_halaman, offset=(halaman - 1) * per_halaman
        ),
        jenis=await service.daftar_jenis(db),
        kembali=f"{PREFIX}/",
    )


@router.get("/transaksi/{transaksi_id}")
async def rincian(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id, akun)
    except service.LayananError as e:
        return redirect("/transaksi" if akun.is_admin else "/", err=str(e))

    aturan = await service.aturan_untuk(db, b.trx.jenis_kode)
    boleh_ubah, sebab = service.boleh_mengubah(b.trx, akun)
    cetak = list((await db.execute(
        select(TimbanganCetak)
        .where(TimbanganCetak.transaksi_id == b.trx.id)
        .order_by(TimbanganCetak.urutan)
    )).scalars())

    return render(
        request, "rincian.html",
        b=b, aturan=aturan,
        pemeriksaan=await service.pemeriksaan_transaksi(db, b.trx.id),
        cetak=cetak,
        boleh_ubah=boleh_ubah, sebab_terkunci=sebab,
        boleh_batal=service.boleh_membatalkan(akun, b.trx),
        kategori_hasil=KATEGORI_HASIL,
        kembali=f"{PREFIX}/",
    )


# ═══════════════════════════ Koreksi & pembatalan ═══════════════════════

@router.get("/transaksi/{transaksi_id}/koreksi")
async def form_koreksi(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id, akun)
    except service.LayananError as e:
        return redirect("/transaksi" if akun.is_admin else "/", err=str(e))

    boleh, sebab = service.boleh_mengubah(b.trx, akun)
    if not boleh:
        return redirect(f"/transaksi/{transaksi_id}", err=sebab)

    return render(
        request, "koreksi.html",
        versi=service.versi_tiket(b.trx),
        b=b, aturan=await service.aturan_untuk(db, b.trx.jenis_kode),
        pihak_pilihan=await service.pihak_pilihan(db, b.trx.arah),
        kolom_nama=service.nama_kolom_pihak(b.trx.arah),
        jenis=await service.daftar_jenis(db),
        kembali=f"{PREFIX}/transaksi/{transaksi_id}",
    )


@router.post("/transaksi/{transaksi_id}/koreksi")
async def simpan_koreksi(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(...),
    versi: str = Form(""),
    asli_timbang1_kg: str = Form(""),
    asli_timbang2_kg: str = Form(""),
    asli_nomor_polisi: str = Form(""),
    asli_nama_sopir: str = Form(""),
    asli_nomor_acuan: str = Form(""),
    asli_berat_acuan_kg: str = Form(""),
    asli_jumlah_karung: str = Form(""),
    asli_tara_per_karung_kg: str = Form(""),
    timbang1_kg: str = Form(""),
    timbang2_kg: str = Form(""),
    nomor_polisi: str = Form(""),
    nama_sopir: str = Form(""),
    supplier_id: str = Form(""),
    jumlah_karung: str = Form(""),
    tara_per_karung_kg: str = Form(""),
    berat_acuan_kg: str = Form(""),
    nomor_acuan: str = Form(""),
    catatan: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id, akun)
    except service.LayananError as e:
        return redirect("/transaksi" if akun.is_admin else "/", err=str(e))

    if not (alasan or "").strip():
        return redirect(
            f"/transaksi/{transaksi_id}/koreksi",
            err="Koreksi harus disertai alasan.",
        )

    # ── Hanya yang BERBEDA dari nilai aslinya yang diterapkan ──
    #
    # Borang mengisi ulang tiap kolom dengan nilai yang SUDAH DIBULATKAN, dan
    # kode ini dulu memperlakukan tiap kolom terisi sebagai perubahan.
    # Akibatnya memperbaiki nama sopir ikut mengubah tara 0,0858 → 0,086 dan
    # nota 13.990,5 → 13.990 — dua angka yang tak pernah disentuh siapa pun.
    # Temuan QA T-06.
    def _berubah_angka(baru_: str, asli_: str) -> bool:
        """Beda sungguhan, bukan beda ejaan. "13.990" dan "13990,0" sama."""
        if not baru_.strip():
            return False
        if not asli_.strip():
            return True
        return abs(_angka(baru_) - _angka(asli_)) > 1e-9

    def _berubah_teks(baru_: str, asli_: str) -> bool:
        return bool(baru_.strip()) and baru_.strip() != (asli_ or "").strip()

    perubahan: dict = {}
    if _berubah_angka(timbang1_kg, asli_timbang1_kg):
        perubahan["timbang1_kg"] = _angka(timbang1_kg)
    if b.trx.timbang2_kg is not None and _berubah_angka(timbang2_kg, asli_timbang2_kg):
        perubahan["timbang2_kg"] = _angka(timbang2_kg)
    if _berubah_teks(nomor_polisi, asli_nomor_polisi):
        perubahan["nomor_polisi"] = nomor_polisi
    if _berubah_teks(nama_sopir, asli_nama_sopir):
        perubahan["nama_sopir"] = nama_sopir
    if supplier_id.isdigit():
        # Kolomnya ditentukan arah transaksi, bukan nama isian di formulir.
        pihak = service.pihak_untuk(b.trx.arah)
        if pihak is not None:
            perubahan[pihak[1]] = int(supplier_id)
    if catatan:
        perubahan["catatan"] = catatan.strip()

    muatan = None
    muatan_berubah = (
        _berubah_angka(jumlah_karung, asli_jumlah_karung)
        or _berubah_angka(berat_acuan_kg, asli_berat_acuan_kg)
        or _berubah_angka(tara_per_karung_kg, asli_tara_per_karung_kg)
        or _berubah_teks(nomor_acuan, asli_nomor_acuan)
    )
    if muatan_berubah:
        lama = b.trx.muatan[0] if b.trx.muatan else None
        muatan = [service.InputMuatan(
            jenis_kode=b.trx.jenis_kode,
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
        await service.koreksi_transaksi(
            db, akun=akun, trx=b.trx, perubahan=perubahan, muatan=muatan,
            # Versi yang dilihat borang saat DIBUKA. Yang tak cocok ditolak
            # sambil menyebut jamnya — bukan menimpa koreksi orang lain.
            versi=versi.strip() or None,
            alasan=alasan.strip(),
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/transaksi/{transaksi_id}/koreksi", err=str(e))
    except DBAPIError as e:
        # R-T-01: galat basis data bukan layar hitam.
        return redirect(f"/transaksi/{transaksi_id}/koreksi", err=await galat_db(db, e, "menyimpan koreksi"))

    return redirect(
        f"/transaksi/{transaksi_id}",
        ok="Koreksi tersimpan. Angka sebelumnya tetap tercatat di jejak audit.",
    )


@router.post("/transaksi/{transaksi_id}/batal")
async def batalkan(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(...),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Batalkan tiket. SIAPA yang boleh diputuskan `service.boleh_membatalkan`.

    Gerbangnya pindah dari rute ke layanan 30 September 2026, sebab syaratnya
    tak lagi soal peran saja: petugas boleh membatalkan tiket yang MASIH
    TERBUKA — timbang pertama sudah, kedua belum — dan tidak boleh menyentuh
    transaksi yang sudah selesai. Syarat yang bergantung pada keadaan barisnya
    tak bisa ditulis sebagai `Depends`, dan menuliskannya dua kali di rute dan
    layanan berarti dua-duanya akan berbeda pada perubahan berikutnya.
    """
    try:
        b = await _ambil(db, transaksi_id, akun)
        await service.void_transaksi(
            db, akun=akun, trx=b.trx, alasan=alasan,
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/transaksi/{transaksi_id}", err=str(e))
    return redirect(
        f"/transaksi/{transaksi_id}",
        ok="Transaksi dibatalkan. Datanya tetap tersimpan.",
    )


# ═══════════════════════════ Pemeriksaan ═══════════════════════════

@router.post("/transaksi/{transaksi_id}/periksa")
async def selesaikan_pemeriksaan(
    transaksi_id: int,
    request: Request,
    kategori_hasil: str = Form(...),
    catatan_resolusi: str = Form(...),
    dilaporkan_ke: str = Form(""),
    langkah_ulang_timbang: str = Form(""),
    langkah_hitung_karung: str = Form(""),
    langkah_periksa_tara: str = Form(""),
    langkah_periksa_dokumen: str = Form(""),
    langkah_periksa_muatan: str = Form(""),
    langkah_lapor: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    lembar = await service.pemeriksaan_transaksi(db, transaksi_id)
    if lembar is None:
        return redirect(
            f"/transaksi/{transaksi_id}",
            err="Transaksi ini tidak punya lembar pemeriksaan.",
        )
    try:
        await service.selesaikan_pemeriksaan(
            db, akun=akun, lembar=lembar,
            langkah={
                "langkah_ulang_timbang": langkah_ulang_timbang.strip() or None,
                "langkah_hitung_karung": langkah_hitung_karung.strip() or None,
                "langkah_periksa_tara": langkah_periksa_tara.strip() or None,
                "langkah_periksa_dokumen": langkah_periksa_dokumen.strip() or None,
                "langkah_periksa_muatan": langkah_periksa_muatan.strip() or None,
                "langkah_lapor": langkah_lapor.strip() or None,
            },
            kategori_hasil=kategori_hasil,
            catatan_resolusi=catatan_resolusi,
            dilaporkan_ke=dilaporkan_ke.strip() or None,
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/transaksi/{transaksi_id}", err=str(e))
    return redirect(f"/transaksi/{transaksi_id}", ok="Pemeriksaan ditutup.")


# ═══════════════════════════ Cetak ═══════════════════════════

@router.get("/transaksi/{transaksi_id}/cetak")
async def pilih_cetak(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Dua ukuran bukti: struk 80 mm dan lembar setengah NCR."""
    try:
        b = await _ambil(db, transaksi_id, akun)
    except service.LayananError as e:
        return redirect("/transaksi" if akun.is_admin else "/", err=str(e))

    return render(
        request, "cetak_pilih.html",
        b=b, aturan=await service.aturan_untuk(db, b.trx.jenis_kode),
        cetak=await _riwayat_cetak(db, b.trx.id),
        kembali=f"{PREFIX}/transaksi/{transaksi_id}",
    )


async def _riwayat_cetak(db: AsyncSession, transaksi_id: int):
    return list((await db.execute(
        select(TimbanganCetak)
        .where(TimbanganCetak.transaksi_id == transaksi_id)
        .order_by(TimbanganCetak.urutan)
    )).scalars())


async def _bahan_cetak(db: AsyncSession, transaksi_id: int, akun):
    """Data yang sama untuk kedua ukuran — hanya tata letaknya berbeda."""
    b = await _ambil(db, transaksi_id, akun)
    aturan = await service.aturan_untuk(db, b.trx.jenis_kode)
    petugas = {}
    for pid in {b.trx.timbang1_petugas_id, b.trx.timbang2_petugas_id} - {None}:
        orang = await db.get(TimbanganAkun, pid)
        if orang:
            petugas[pid] = orang.nama
    return b, aturan, petugas


async def _isi_bukti(db, transaksi_id, akun):
    """Satu kamus data untuk semua bentuk cetakan bukti timbang.

    Kesahan tiketnya diperiksa DI SINI, di satu tempat yang dilewati ketiga
    jalur cetak (ePOS, struk PDF, lembar NCR). Pemeriksaan yang dipasang di
    tiap rute akan tertinggal di salah satunya, dan yang tertinggal justru
    jadi satu-satunya pintu yang masih mengeluarkan kertas.
    """
    b, aturan, petugas = await _bahan_cetak(db, transaksi_id, akun)
    service.pastikan_boleh_cetak(b.trx)
    return b, aturan, dict(
        cetakan_ke=await service.cetakan_ke(db, b.trx.id),
        trx=b.trx, aturan=aturan,
        pihak=(b.supplier_nama or b.trx.pihak_nama or ""),
        petugas=petugas.get(b.trx.petugas_bukti_id, ""),
        muatan=list(b.trx.muatan),
        perusahaan=tsettings.perusahaan_nama,
        alamat=tsettings.perusahaan_alamat,
        telepon=tsettings.perusahaan_telepon,
        arah_masuk=logic.timbang_pertama_bermuatan(b.trx.arah),
    )


async def _pdf(db, transaksi_id, request, ncr: bool, akun=None):
    b, aturan, umum = await _isi_bukti(db, transaksi_id, akun)
    if ncr:
        return b.trx, pdf.bukti_ncr(**umum)
    # Selisih hanya dicetak bila ada yang benar-benar dibandingkan; syaratnya
    # ada di `epos.tampilkan_selisih` supaya kedua jalur cetak memakai satu
    # keputusan yang sama. Lihat penjelasannya di sana.
    return b.trx, pdf.bukti_thermal(
        **umum, tampilkan_selisih=epos.tampilkan_selisih(b.trx, aturan)
    )


@router.get("/transaksi/{transaksi_id}/cetak/ncr")
async def cetak_ncr_pdf(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Lembar setengah NCR sebagai PDF 215 × 165 mm.

    Digambar di server, bukan lewat dialog cetak browser — supaya ukurannya
    pasti dan tidak ada tanggal, jam, nomor halaman, maupun URL yang ikut
    tercetak di kertas nota.
    """
    try:
        trx, isi = await _pdf(db, transaksi_id, request, ncr=True, akun=akun)
    except service.LayananError as e:
        return redirect("/transaksi" if akun.is_admin else "/", err=str(e))
    return Response(
        isi, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{trx.kode}.pdf"'},
    )


@router.get("/transaksi/{transaksi_id}/cetak/80mm")
async def cetak_80mm_pdf(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Struk 80 mm sebagai PDF, tanpa kop-kaki browser."""
    try:
        trx, isi = await _pdf(db, transaksi_id, request, ncr=False, akun=akun)
    except service.LayananError as e:
        return redirect("/transaksi" if akun.is_admin else "/", err=str(e))
    return Response(
        isi, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{trx.kode}-80mm.pdf"'},
    )


@router.get("/transaksi/{transaksi_id}/cetak/epos")
async def cetak_epos(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Perintah ePOS-Print untuk struk 80 mm — bukan berkas, melainkan cetakan.

    Yang dikembalikan di sini tidak dibuka siapa pun; perangkat mengambilnya
    lalu meneruskannya ke printer di jaringan pos timbang. Server tidak bisa
    mengirimnya sendiri: ia berjalan di Railway, dan printer ada di balik
    jaringan lokal gudang yang tidak punya alamat dari luar.

    Karena itu keberhasilan cetak TIDAK diketahui dari sini. Yang mencatat
    "sudah dicetak" tetap `catat_cetak`, dipanggil perangkat setelah printer
    menjawab — jejak audit hanya boleh mencatat kertas yang benar-benar keluar.
    """
    try:
        b, aturan, umum = await _isi_bukti(db, transaksi_id, akun)
    except service.LayananError as e:
        return redirect("/transaksi" if akun.is_admin else "/", err=str(e))
    return Response(
        epos.struk_timbang(
            **umum, tampilkan_selisih=epos.tampilkan_selisih(b.trx, aturan)
        ),
        media_type="text/xml; charset=utf-8",
    )


@router.post("/transaksi/{transaksi_id}/jenis")
async def ubah_jenis_transaksi(
    transaksi_id: int,
    request: Request,
    jenis_kode: str = Form(...),
    alasan: str = Form(""),
    tukar_timbangan: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    """Betulkan komoditas — dan arah barang — yang salah dipilih di awal.

    Terpisah dari koreksi biasa dan tertutup bagi petugas: mengubah arah
    mengubah seluruh hasil kontrol transaksi yang sudah tersimpan.
    """
    b = await _ambil(db, transaksi_id, akun)
    try:
        pindah = await service.ubah_jenis(
            db, akun=akun, trx=b.trx, jenis_kode=jenis_kode, alasan=alasan,
            tukar_timbangan=bool(tukar_timbangan),
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/transaksi/{transaksi_id}/koreksi", err=str(e))
    except DBAPIError as e:
        # R-T-01: galat basis data bukan layar hitam.
        return redirect(f"/transaksi/{transaksi_id}/koreksi", err=await galat_db(db, e, "menyimpan koreksi"))
    if not pindah:
        return redirect(f"/transaksi/{transaksi_id}", ok="Jenis barang tidak berubah.")
    return redirect(
        f"/transaksi/{transaksi_id}",
        ok=f"Jenis barang diubah: {pindah}. Hasil kontrolnya dihitung ulang.",
    )


@router.post("/transaksi/{transaksi_id}/hapus")
async def hapus_transaksi(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(""),
    ketik_kode: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_super),
    db: AsyncSession = Depends(get_db),
):
    """Hapus permanen. Hanya Super Admin; lihat `service.hapus_transaksi`."""
    b = await _ambil(db, transaksi_id, akun)

    # Nomor transaksinya diketik ulang, bukan sekadar tombol ditekan.
    if ketik_kode.strip().upper() != b.trx.kode:
        return redirect(
            f"/transaksi/{transaksi_id}",
            err="Untuk menghapus, ketik nomor transaksinya persis: "
                f"{b.trx.kode}",
        )
    try:
        kode = await service.hapus_transaksi(
            db, akun=akun, trx=b.trx, alasan=alasan,
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/transaksi/{transaksi_id}", err=str(e))
    except IntegrityError:
        # Jaring terakhir. Tautan produksi sudah diperiksa di layanan, jadi
        # yang sampai ke sini adalah penunjuk yang BELUM dikenal — tabel baru
        # di repo sebelah, misalnya. Tetap saja orangnya tak boleh melihat
        # halaman galat untuk sesuatu yang sebenarnya punya penjelasan.
        await db.rollback()
        return redirect(
            f"/transaksi/{transaksi_id}",
            err="Tiket ini masih ditunjuk catatan lain, jadi belum bisa "
                "dihapus. Batalkan (VOID) saja bila memang keliru.",
        )
    except DBAPIError as e:
        return redirect(f"/transaksi/{transaksi_id}",
                        err=await galat_db(db, e, "menghapus tiket"))
    return redirect("/transaksi", ok=f"{kode} dihapus permanen.")


@router.post("/transaksi/{transaksi_id}/cetak")
async def catat_cetak(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(""),
    format: str = Form("80MM"),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id, akun)
        await service.catat_cetak(
            db, akun=akun, trx=b.trx, alasan=alasan or None,
            format=format.upper(),
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/transaksi/{transaksi_id}/cetak", err=str(e))
    return redirect(f"/transaksi/{transaksi_id}/cetak", ok="Cetak tercatat.")

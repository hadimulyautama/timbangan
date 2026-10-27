"""Rute transaksi: daftar, rincian, koreksi, pembatalan, cetak, pemeriksaan."""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response, JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import epos, logic, pdf, service, sopir, koreksi as borang_koreksi
from app.timbangan.config import tsettings
from app.timbangan.db import get_db, hari_ini
from app.timbangan.models import TimbanganAkun, TimbanganCetak, TimbanganPemeriksaan
from app.config import settings
from app.timbangan.routes.pos import _angka
from app.timbangan.security import (
    butuh_admin,
    butuh_akun,
    butuh_super,
)
from app.timbangan.web import galat_db, PREFIX, redirect, render

from app.timbangan import pengiriman, klien_produksi, rincian_keluar, rincian_retur, rincian_masuk, format as fmt

router = APIRouter(prefix=PREFIX)

#: Dua arah retur digabung jadi satu pilihan filter — lihat `daftar()`.
ARAH_RETUR = (logic.RETUR_MASUK, logic.RETUR_KELUAR)


def _kembali_riwayat(request):
    """Konteks daftar baca saja, dibatasi ke URL lokal daftar yang lama."""
    url = request.query_params.get("kembali", "")
    try:
        bagian = urlsplit(url)
    except ValueError:
        return None
    if not bagian.scheme and not bagian.netloc and bagian.path in {PREFIX + p for p in ("/transaksi", "/laporan", "/monitoring")}:
        return url
    return None

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
    # "Retur" di filter ini SATU pilihan, bukan dua — RETUR_MASUK (dari
    # pelanggan) dan RETUR_KELUAR (ke supplier) digabung, sebab yang mencari
    # "transaksi retur apa saja hari ini" biasanya tak peduli arahnya dulu.
    # Bawaan TANPA filter: alamat tanpa `arah` menampilkan semua, persis
    # seperti tanpa filter lain mana pun di borang ini.
    arah_pilih = q.get("arah") or ""
    arah_filter = ARAH_RETUR if arah_pilih == "RETUR" else (arah_pilih or None)
    f = service.FilterTransaksi(
        # Transaksi yang dibatalkan tetap tertera di catatan, bertanda
        # "Batal". Truk yang batal bongkar memang pernah datang; menyembunyikan
        # barisnya membuat catatan terlihat rapi dengan cara yang keliru.
        # Ringkasan, ekspor, dan beranda tetap tidak menghitungnya.
        sertakan_void=True,
        arah=arah_filter,
        jenis_kode=q.get("jenis") or None,
        status_kontrol=q.get("status") or None,
        status_tiket=q.get("tiket") or None,
        cari=q.get("cari") or None,
    )
    # Bawaan DUA MINGGU terakhir — diubah dari dua hari atas permintaan
    # pemilik, 4 Oktober 2026.
    #
    # Sempat 30 hari, lalu dipotong ke dua hari dengan alasan performa
    # (halaman tak perlu menghitung & mengirim sebulan penuh untuk kerja
    # sehari-hari). Dua minggu adalah titik tengah: masih jauh lebih ringan
    # dari 30 hari, tapi cukup panjang untuk menoleh ke belakang tanpa harus
    # mengisi tanggal secara manual tiap kali.
    #
    # Rentang yang lebih panjang tidak hilang, hanya tidak lagi jadi bawaan —
    # isian tanggal di atas daftar ada justru untuk itu, dan setiap tautan
    # halaman berikutnya serta tombol ekspor membawa rentang yang sedang
    # dipilih.
    BAWAAN_HARI = 13        # hari ini + 13 hari ke belakang = 14 hari (2 minggu)
    try:
        f.dari = date.fromisoformat(q["dari"]) if q.get("dari") else \
            hari_ini() - timedelta(days=BAWAAN_HARI)
        f.sampai = date.fromisoformat(q["sampai"]) if q.get("sampai") else hari_ini()
    except ValueError:
        f.dari, f.sampai = hari_ini() - timedelta(days=BAWAAN_HARI), hari_ini()

    try:
        halaman = max(1, int(q.get("hal", 1) or 1))
    except ValueError:
        halaman = 1
    per_halaman = 50
    total = await service.hitung_transaksi(db, f)
    jumlah_halaman = max(1, (total + per_halaman - 1) // per_halaman)
    halaman = min(halaman, jumlah_halaman)
    baris = await service.daftar_transaksi(
        db, f, batas=per_halaman, offset=(halaman - 1) * per_halaman)
    # Hanya membaca keadaan lembar yang nyata. Status kontrol yang tersimpan
    # tidak membuktikan lembar masih dibuka (atau bahwa Produksi memverifikasi).
    pemeriksaan = {}
    if baris:
        pemeriksaan = dict((await db.execute(
            select(TimbanganPemeriksaan.transaksi_id, TimbanganPemeriksaan.status)
            .where(TimbanganPemeriksaan.transaksi_id.in_([b.trx.id for b in baris]))
            .order_by(TimbanganPemeriksaan.id)
        )).all())

    def alamat(**ganti):
        # Satu pembentuk URL untuk semua halaman. Tidak menyalin query mentah
        # agar pesan kilat dan parameter lain tak menjadi filter tersembunyi.
        nilai = {"dari": f.dari.isoformat(), "sampai": f.sampai.isoformat(),
                 "arah": arah_pilih, "jenis": f.jenis_kode, "status": f.status_kontrol,
                 "tiket": f.status_tiket, "cari": f.cari, "hal": halaman, **ganti}
        return PREFIX + "/transaksi?" + urlencode({k: v for k, v in nilai.items() if v})

    def tujuan(path):
        return PREFIX + path + "?" + urlencode({"kembali": alamat()})

    master = await service.daftar_jenis(db, hanya_aktif=False)
    belum_ada = total == 0 and not await service.hitung_transaksi(
        db, service.FilterTransaksi(sertakan_void=True))
    return render(
        request, "daftar.html",
        f=f, halaman=halaman, per_halaman=per_halaman,
        arah_pilih=arah_pilih,
        total=total, baris=baris, jumlah_halaman=jumlah_halaman, alamat=alamat, tujuan=tujuan,
        pemeriksaan=pemeriksaan, belum_ada=belum_ada,
        jenis=[j for j in master if j.status == "aktif" or j.kode == f.jenis_kode],
        NAMA_JENIS={j.kode: j.nama for j in master},
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

    pemeriksaan = await service.pemeriksaan_transaksi(db, b.trx.id)
    keluar = await rincian_keluar.baca(db, b.trx, pemeriksaan, cetak) if b.trx.arah == logic.KELUAR and not b.trx.partai else None
    retur = await rincian_retur.baca(db, b.trx, akun, pemeriksaan, cetak) if b.trx.arah == logic.RETUR_MASUK and not b.trx.partai else None
    masuk = await rincian_masuk.baca(db, b.trx, akun, pemeriksaan, cetak,
        lihat=request.cookies.get('produksi_lihat')) if b.trx.arah == logic.MASUK and not b.trx.partai else None
    response = render(
        request, "rincian_masuk.html" if masuk else "rincian_retur.html" if retur else "rincian_keluar.html" if keluar else "rincian.html",
        layar="rincian", keluar=keluar, retur=retur, masuk=masuk, produksi_url=settings.produksi_web_url,
        b=b, aturan=aturan,
        pemeriksaan=pemeriksaan,
        cetak=cetak,
        boleh_ubah=boleh_ubah, sebab_terkunci=sebab,
        boleh_batal=service.boleh_membatalkan(akun, b.trx),
        tautan_produksi=(
            f"{settings.produksi_web_url}/barang-keluar?buka=verifikasi_keluar&tiket={b.trx.id}"
            if b.trx.arah == logic.KELUAR and b.trx.status_tiket == "SELESAI"
            and b.trx.status_transaksi != "VOID" else None
        ),
        kategori_hasil=KATEGORI_HASIL,
        kembali=_kembali_riwayat(request) or f"{PREFIX}/",
    )
    if retur or masuk:
        response.headers['Cache-Control'] = 'private, no-store'
    return response


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

    boleh, sebab = service.boleh_mengubah(b.trx, akun, (await service.setelan.semua(db))["jam_kunci_otomatis"])
    if not boleh:
        return redirect(f"/transaksi/{transaksi_id}", err=sebab)

    batas_tautan = None
    try:
        async with db.begin_nested():
            await service.pastikan_bebas_tautan(db, b.trx, tindakan="Koreksi identitas")
    except service.LayananError:
        batas_tautan = ("Tiket tertaut PadiFlow. Identitas yang sudah disalin dilindungi; nama sopir dan catatan mengikuti izin lama. Bobot dan kemasan retur tertaut dilindungi lebih ketat.")
    except DBAPIError:
        batas_tautan = "Tautan PadiFlow belum dapat dipastikan. Server tetap memeriksa pembatasannya saat menyimpan."
    return render(
        request, "koreksi.html",
        versi=service.versi_tiket(b.trx), batas_tautan=batas_tautan,
        sopir_pilihan=await sopir.daftar_pilihan(db),
        kendaraan=await service.kendaraan_pilihan(db),
        b=b, aturan=await service.aturan_untuk(db, b.trx.jenis_kode),
        pihak_pilihan=await service.pihak_pilihan(db, b.trx.arah, jasa=b.trx.jasa),
        kolom_nama=service.nama_kolom_pihak(b.trx.arah, jasa=b.trx.jasa),
        jenis=await service.daftar_jenis(db),
        kembali=f"{PREFIX}/transaksi/{transaksi_id}",
    )


@router.post("/transaksi/{transaksi_id}/koreksi/pratinjau")
async def pratinjau_koreksi(
    transaksi_id: int, request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Tidak memanggil penyimpanan, audit, sinkronisasi atau stok."""
    def jawab(data, status=200):
        return JSONResponse(data, status_code=status, headers={"Cache-Control":"no-store"})
    try:
        b=await _ambil(db, transaksi_id, akun)
        boleh,sebab=service.boleh_mengubah(b.trx,akun,(await service.setelan.semua(db))["jam_kunci_otomatis"])
        if not boleh:return jawab({"tersedia":False,"pesan":sebab},403)
        data=await request.form()
        service.pastikan_versi(b.trx, str(data.get("versi", "")).strip() or None)
        perubahan,muatan,ringkasan=borang_koreksi.baca(b.trx,data)
        if data.get('perbarui_muatan') == '1':
            sumber = await pengiriman.baca(db, transaksi_id)
            if not b.trx.pengiriman_snapshot or sumber['kiriman_id'] != b.trx.pengiriman_snapshot['kiriman_id']:
                raise service.LayananError('Rincian bukan dari kiriman yang tersimpan pada tiket.')
            muatan = pengiriman.input_muatan(sumber)
            if sumber != b.trx.pengiriman_snapshot:
                ringkasan.append({'field':'pengiriman_snapshot','label':'Cuplikan muatan PadiFlow',
                    'lama':pengiriman.ringkasan(b.trx.pengiriman_snapshot),'baru':pengiriman.ringkasan(sumber) + ' · data sumber terbaru'})
                ringkasan.append({'field':'acuan_pengiriman','label':'Total acuan muatan PadiFlow',
                    'lama':fmt.kg(sum(p['subtotal'] for p in pengiriman.kelompok(b.trx.pengiriman_snapshot))),
                    'baru':fmt.kg(sum(p['subtotal'] for p in pengiriman.kelompok(sumber)))})
        hasil=await borang_koreksi.pratinjau(db,b.trx,perubahan,muatan)
        # Nama pihak dibaca dari keluarga ID yang benar; tidak membocorkan
        # tabel kontak di luar cakupan yang sudah disediakan formulir.
        pihak=service.pihak_untuk(b.trx.arah,jasa=b.trx.jasa)
        if pihak:
            model,kolom,_=pihak
            for r in ringkasan:
                if r["field"]==kolom:
                    for k in ("lama","baru"):
                        obj=await db.get(model,int(r[k])) if r[k].isdigit() else None
                        if obj:r[k]=getattr(obj,service.nama_kolom_pihak(b.trx.arah,jasa=b.trx.jasa))
        nilai={"Berat barang sebelum koreksi":borang_koreksi.tampil(b.trx.berat_barang_kg,"berat_acuan_kg")}
        if hasil is None:
            nilai.update({"Netto timbangan":"Belum tersedia", "Total tara":"Belum final", "Berat barang setelah koreksi":"Belum tersedia", "Status kontrol":"Belum dinilai"})
        if hasil:
            nilai.update({"Netto timbangan":borang_koreksi.tampil(hasil.netto_timbangan_kg,"timbang1_kg"),"Total tara":borang_koreksi.tampil(hasil.total_tara_kg,"timbang1_kg"),"Berat barang setelah koreksi":borang_koreksi.tampil(hasil.berat_barang_kg,"timbang1_kg"),"Status kontrol":hasil.status_label})
            if hasil.berat_acuan_kg>0 and hasil.status!="TANPA_KONTROL":
                nilai["Berat dokumen"]=borang_koreksi.tampil(hasil.berat_acuan_kg,"berat_acuan_kg")
                nilai["Selisih"]=("+" if hasil.selisih_kg>0 else "")+borang_koreksi.tampil(hasil.selisih_kg,"timbang1_kg")
        return jawab({"tersedia":True,"perubahan":ringkasan,"nilai":nilai,"terbuka":hasil is None})
    except (service.LayananError,logic.ValidasiError,pengiriman.MuatanTidakSah,klien_produksi.ProduksiTakTersedia) as e:
        return jawab({"tersedia":False,"pesan":str(e)},409 if "sudah diubah orang lain" in str(e) else 422)


@router.post("/transaksi/{transaksi_id}/koreksi")
async def simpan_koreksi(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(...),
    versi: str = Form(""),
    perbarui_muatan: str = Form(""),
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

    data_form = locals()
    try:
        perubahan, muatan, _ = borang_koreksi.baca(b.trx, data_form)
        service.pastikan_versi(b.trx,versi.strip() or None)
        await borang_koreksi.periksa_bacaan_terbuka(db,b.trx,perubahan)
        sumber = await pengiriman.baca(db, transaksi_id) if perbarui_muatan == '1' else None
        await service.koreksi_transaksi(
            db, akun=akun, trx=b.trx, perubahan=perubahan, muatan=muatan,
            # Versi yang dilihat borang saat DIBUKA. Yang tak cocok ditolak
            # sambil menyebut jamnya — bukan menimpa koreksi orang lain.
            versi=versi.strip() or None,
            alasan=alasan.strip(), pengiriman_snapshot=sumber,
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError, pengiriman.MuatanTidakSah, klien_produksi.ProduksiTakTersedia) as e:
        return redirect(f"/transaksi/{transaksi_id}/koreksi", err=str(e))
    except DBAPIError as e:
        # R-T-01: galat basis data bukan layar hitam.
        return redirect(f"/transaksi/{transaksi_id}/koreksi", err=await galat_db(db, e, "menyimpan koreksi"))

    if sumber and akun.akun_id:
        try:
            hasil = await klien_produksi.selesaikan_pengiriman(transaksi_id, akun.akun_id,
                         sidik_sumber=b.trx.pengiriman_snapshot.get('sidik_sumber'))
            if not hasil.get('selesai'):
                return redirect(f"/transaksi/{transaksi_id}", err="Koreksi tersimpan; verifikasi PadiFlow masih menunggu pemeriksaan.")
        except klien_produksi.ProduksiTakTersedia as e:
            return redirect(f"/transaksi/{transaksi_id}", err=f"Koreksi tersimpan; verifikasi PadiFlow belum terkonfirmasi: {e}")
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
        kembali=_kembali_riwayat(request) or f"{PREFIX}/transaksi/{transaksi_id}",
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
    return b, aturan


async def _isi_bukti(db, transaksi_id, akun):
    """Satu kamus data untuk semua bentuk cetakan bukti timbang.

    Kesahan tiketnya diperiksa DI SINI, di satu tempat yang dilewati ketiga
    jalur cetak (ePOS, struk PDF, lembar NCR). Pemeriksaan yang dipasang di
    tiap rute akan tertinggal di salah satunya, dan yang tertinggal justru
    jadi satu-satunya pintu yang masih mengeluarkan kertas.
    """
    b, aturan = await _bahan_cetak(db, transaksi_id, akun)
    service.pastikan_boleh_cetak(b.trx)
    return b, aturan, dict(
        cetakan_ke=await service.cetakan_ke(db, b.trx.id),
        trx=b.trx, aturan=aturan,
        pihak=b.pihak_tampil,
        # ── NAMA YANG MENCETAK, bukan yang menimbang ──
        #
        # Keputusan pemilik 30 September 2026: "yang di struk bukan petugas
        # timbang awal. yang di struk haruslah nama akun siapa yang print."
        #
        # Sampai hari ini yang tertera `petugas_bukti_id` — pelaku timbang
        # TERAKHIR. Pada satu orang keduanya sama, jadi selisihnya tak pernah
        # terlihat; begitu dua shift berganti di tengah satu tiket, kertasnya
        # menyebut orang yang tidak sedang berdiri di pos.
        #
        # Blok itu ruang TANDA TANGAN, dan yang menandatangani adalah orang
        # yang menyerahkan kertasnya kepada sopir — yaitu yang menekan cetak.
        # Nama tercetak yang bukan nama penanda tangan membuat kertasnya
        # bertentangan dengan dirinya sendiri.
        #
        # Siapa yang MENIMBANG tidak hilang: ia tetap tercatat di
        # `timbang1_petugas_id` / `timbang2_petugas_id` dan terbaca di layar
        # rincian. Yang berubah cuma isi selembar kertas yang ditandatangani.
        petugas=akun.nama,
        muatan=list(b.trx.muatan),
        perusahaan=tsettings.perusahaan_nama,
        alamat=tsettings.perusahaan_alamat,
        telepon=tsettings.perusahaan_telepon,
        arah_masuk=logic.timbang_pertama_bermuatan(b.trx.arah),
    )


async def _pdf(db, transaksi_id, request, ncr: bool, akun):
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


@router.post("/transaksi/hapus-massal")
async def hapus_massal(
    request: Request,
    transaksi_id: list[int] = Form([]),
    alasan: str = Form(""),
    konfirmasi: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_super),
    db: AsyncSession = Depends(get_db),
):
    """Hapus permanen banyak catatan sekaligus — satu per satu lewat
    `service.hapus_transaksi` yang SAMA dengan hapus satu baris.

    Aturan dan jejak auditnya tidak berbeda; yang berbeda cuma dipanggil
    berulang. Konfirmasinya pun sengaja BUKAN ketik nomor transaksi (banyak
    baris, banyak nomor berbeda) melainkan ketik JUMLAH baris yang dipilih —
    pemeriksaan bahwa orangnya sungguh menghitung apa yang akan hilang,
    bukan sekadar menekan tombol.

    Baris yang masih tertaut catatan produksi DILEWATI, bukan membatalkan
    seluruh batch: Super Admin yang memilih 20 baris tak perlu mengulang
    dari awal hanya karena satu di antaranya tertaut.
    """
    ids = sorted(set(transaksi_id))
    if not ids:
        return redirect("/transaksi", err="Tidak ada catatan yang dipilih.")
    if konfirmasi.strip() != str(len(ids)):
        return redirect(
            "/transaksi",
            err=f"Untuk menghapus {len(ids)} catatan, ketik angka {len(ids)} persis.",
        )
    if not (alasan or "").strip():
        return redirect("/transaksi", err="Penghapusan harus disertai alasan.")

    dihapus = 0
    dilewati: list[str] = []
    for tid in ids:
        label = f"#{tid}"
        try:
            b = await _ambil(db, tid, akun)
            label = b.trx.kode
            await service.hapus_transaksi(
                db, akun=akun, trx=b.trx, alasan=alasan,
                ip=request.client.host if request.client else None,
            )
            dihapus += 1
        except service.LayananError as e:
            await db.rollback()
            dilewati.append(f"{label}: {e}")
        except IntegrityError:
            await db.rollback()
            dilewati.append(f"{label}: masih tertaut catatan lain")
        except DBAPIError as e:
            dilewati.append(f"{label}: {await galat_db(db, e, 'menghapus tiket')}")

    if dihapus == 0:
        pesan = f"Tidak ada yang dihapus. {len(dilewati)} dilewati: " + "; ".join(dilewati[:5])
        if len(dilewati) > 5:
            pesan += f"; dan {len(dilewati) - 5} lainnya."
        return redirect("/transaksi", err=pesan)

    pesan = f"{dihapus} catatan dihapus permanen."
    if dilewati:
        pesan += f" {len(dilewati)} dilewati: " + "; ".join(dilewati[:5])
        if len(dilewati) > 5:
            pesan += f"; dan {len(dilewati) - 5} lainnya."
    return redirect("/transaksi", ok=pesan)


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

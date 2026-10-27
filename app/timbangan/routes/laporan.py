"""Rute rekapitulasi: ringkasan harian, monitoring pihak, dan ekspor.

Semua halaman di sini butuh peran Admin — bukan karena datanya
rahasia dari petugas, tetapi karena menilai pola adalah pekerjaan yang berbeda
dari menimbang, dan mencampurnya membuat kedua pekerjaan itu lebih buruk.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import format as fmt
from app.timbangan import logic, service
from app.timbangan.db import get_db, hari_ini
from app.timbangan.models import TimbanganAkun, TimbanganPemeriksaan
from app.timbangan.security import butuh_admin
from app.timbangan.web import PREFIX, render

router = APIRouter(prefix=PREFIX)


def _rentang(q) -> tuple[date, date]:
    try:
        dari = date.fromisoformat(q["dari"]) if q.get("dari") else \
            hari_ini() - timedelta(days=30)
        sampai = date.fromisoformat(q["sampai"]) if q.get("sampai") else hari_ini()
    except ValueError:
        dari, sampai = hari_ini() - timedelta(days=30), hari_ini()
    return dari, sampai


@router.get("/laporan")
async def laporan(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _halaman(request, db)


async def _halaman(request, db, tab_awal="rekap"):
    """Hanya susunan baca: cakupan dan rumus tetap milik layanan lama."""
    dari, sampai = _rentang(request.query_params)
    f = service.FilterTransaksi(dari=dari, sampai=sampai)
    tab = request.query_params.get("tab", tab_awal)
    if tab not in ("rekap", "pemeriksaan", "pemantauan"):
        tab = tab_awal
    tautan = {t: f"{PREFIX}/laporan?" + urlencode({
        "tab": t, "dari": dari.isoformat(), "sampai": sampai.isoformat(),
    }) for t in ("rekap", "pemeriksaan", "pemantauan")}
    ctx = dict(f=f, tab=tab, tautan=tautan, konteks=tautan[tab],
               lembar_terbuka=await service.daftar_pemeriksaan_terbuka(db),
               kembali=f"{PREFIX}/")
    if tab == "rekap":
        ctx["ringkasan"] = await service.ringkasan_dashboard(db, f)
        ctx["perlu_periksa"] = await service.daftar_transaksi(
            db, service.FilterTransaksi(
                dari=dari, sampai=sampai,
                status_kontrol=sorted(logic.STATUS_WAJIB_PERIKSA)),
            batas=20,
        )
    elif tab == "pemantauan":
        ctx["baris"] = await service.monitoring_supplier(db, f)
    # Status lembar dipisahkan dari status kontrol; tidak disimpulkan dari
    # angka selisih. Query terbatas pada tiket yang benar-benar ditampilkan.
    ids = {b.trx.id for b in ctx["lembar_terbuka"]}
    ids.update(b.trx.id for b in ctx.get("perlu_periksa", []))
    lembar = (await db.scalars(select(TimbanganPemeriksaan).where(
        TimbanganPemeriksaan.transaksi_id.in_(ids)
    ).order_by(TimbanganPemeriksaan.id))).all() if ids else []
    ctx["lembar_per_tiket"] = {l.transaksi_id: l for l in lembar}
    return render(request, "laporan.html", **ctx)


@router.get("/monitoring")
async def monitoring(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    """Skor & pola per pihak.

    Bahasanya selalu 'perlu diperiksa', tidak pernah menuduh. Angka di sini
    adalah alasan untuk bertanya, bukan kesimpulan.
    """
    return await _halaman(request, db, "pemantauan")


@router.get("/ekspor.csv")
async def ekspor(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    """Ekspor CSV — tanpa satu pun kolom harga, sama seperti seluruh modul."""
    dari, sampai = _rentang(request.query_params)
    baris = await service.daftar_transaksi(
        db, service.FilterTransaksi(dari=dari, sampai=sampai), batas=10_000
    )

    buf = io.StringIO()
    tulis = csv.writer(buf)
    tulis.writerow([
        "kode", "tanggal", "arah", "komoditas", "pihak", "nomor_polisi",
        "timbang1_kg", "jam1", "timbang2_kg", "jam2",
        "netto_timbangan_kg", "jumlah_karung", "total_tara_kg",
        "berat_barang_kg", "berat_acuan_kg", "selisih_kg", "selisih_persen",
        "status_kontrol", "status_tiket", "status_transaksi", "revisi",
    ])
    for b in baris:
        t = b.trx
        tulis.writerow([jinakkan_sel(x) for x in [
            t.kode, t.tanggal, t.arah, t.jenis_kode,
            (b.pihak_tampil if t.pengiriman_snapshot else b.supplier_nama or t.pihak_nama or ""), t.nomor_polisi or "",
            # Lewat fmt.jam, bukan strftime langsung: Postgres mengembalikan
            # waktu dalam UTC, dan ekspor ini dibandingkan dengan nota cetak.
            t.timbang1_kg, fmt.jam(t.timbang1_waktu) if t.timbang1_waktu else "",
            t.timbang2_kg or "", fmt.jam(t.timbang2_waktu) if t.timbang2_waktu else "",
            t.netto_timbangan_kg or "", t.jumlah_karung, t.total_tara_kg,
            t.berat_barang_kg or "", t.berat_acuan_kg, t.selisih_kg,
            t.selisih_persen, t.status_kontrol or "", t.status_tiket,
            t.status_transaksi, t.jumlah_revisi,
        ]])

    buf.seek(0)
    nama = f"timbangan-{dari:%Y%m%d}-{sampai:%Y%m%d}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )


#: Karakter yang membuat Excel dan Google Sheets memperlakukan sebuah sel
#: sebagai RUMUS, bukan sebagai teks.
_AWALAN_RUMUS = ("=", "+", "-", "@")


def jinakkan_sel(nilai):
    """Pastikan satu sel CSV terbaca sebagai teks, bukan sebagai rumus.

    Isi kolom di sini diketik petugas: nama sopir, nomor nota, keterangan.
    Nama sopir `=HYPERLINK("https://…","klik")` dulu ditulis apa adanya, dan
    dijalankan saat berkasnya dibuka — biasanya oleh bagian keuangan, di
    komputer yang punya akses ke hal lain. Temuan QA T-25.

    Angka tetap angka. Mengubahnya jadi teks membuat kolom jumlah di Excel
    berhenti menjumlah, dan kerusakan itu tak terlihat sampai angkanya
    dipakai.
    """
    if nilai is None or isinstance(nilai, (int, float, bool)):
        return nilai
    teks = str(nilai)
    return "'" + teks if teks[:1] in _AWALAN_RUMUS else teks

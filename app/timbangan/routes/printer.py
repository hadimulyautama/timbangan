"""Printer struk: penyiapan per perangkat dan cetakan uji.

Halaman ini ada karena satu kenyataan yang tidak bisa dihapus dengan kode:
**server tidak bisa mencetak.** Aplikasi berjalan di Railway, printer berdiri
di jaringan lokal gudang, dan tidak ada jalan dari yang pertama ke yang kedua.
Yang mengirim perintah cetak adalah browser petugas, dan browser menuntut dua
izin sebelum mau menghubungi alat di jaringan setempat. Keduanya sekali seumur
perangkat — tetapi bila tidak dijelaskan, petugas hanya melihat tombol cetak
yang diam saja, dan menyimpulkan aplikasinya rusak.

Alamat printer disimpan di perangkat, bukan di database. Ia memang milik
tempat, bukan milik perusahaan: tablet di pos timbang menunjuk printer pos,
dan ponsel Direksi di kantor tidak menunjuk apa pun.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.timbangan import epos
from app.timbangan.config import tsettings
from app.timbangan.models import TimbanganAkun
from app.timbangan.security import butuh_akun
from app.timbangan.web import PREFIX, render

router = APIRouter(prefix=PREFIX)


@router.get("/printer")
async def penyiapan(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
):
    return render(request, "printer.html", kembali=f"{PREFIX}/")


@router.get("/printer/uji")
async def cetak_uji(akun: TimbanganAkun = Depends(butuh_akun)):
    """Perintah cetak pendek untuk memastikan printer benar-benar terjangkau.

    Seperti struk sungguhan, ia hanya dikembalikan — yang mengirimkannya ke
    printer tetap perangkat yang meminta.
    """
    return Response(
        epos.struk_uji(perusahaan=tsettings.perusahaan_nama),
        media_type="text/xml; charset=utf-8",
    )

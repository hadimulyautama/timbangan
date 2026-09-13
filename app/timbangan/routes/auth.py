"""Rute masuk & keluar.

Sesi bertahan sampai petugas menekan Keluar. Tiap orang memakai perangkatnya
sendiri, jadi membuka aplikasi lagi tidak boleh meminta sandi — di pos timbang,
truk tidak menunggu orang mengetik kata sandi.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import service
from app.timbangan.config import tsettings
from app.timbangan.db import get_db, sekarang
from app.timbangan.models import TimbanganAkun
from app.timbangan import gerbang_masuk as gerbang
from app.timbangan.security import (
    NAMA_COOKIE,
    akun_opsional,
    buat_token,
    buat_token_bersama,
    butuh_akun,
    cek_sandi,
    tujuan_aman,
)
from app.timbangan.web import BASE_DIR, PREFIX, redirect, render
from hmu_identitas import masuk as identitas

router = APIRouter(prefix=PREFIX)


@router.get("/masuk")
async def halaman_masuk(request: Request):
    akun = await akun_opsional(request)
    if akun is not None:
        return RedirectResponse(f"{PREFIX}/", status_code=303)
    return render(
        request, "masuk.html",
        tujuan=tujuan_aman(request.query_params.get("next", "")),
    )


@router.post("/masuk")
async def proses_masuk(
    request: Request,
    username: str = Form(...),
    sandi: str = Form(...),
    tujuan: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    uname = username.strip().lower()
    tujuan = tujuan_aman(tujuan)
    ip = request.client.host if request.client else None

    # ── Pembatas percobaan (RANCANGAN §10) ──
    #
    # Sampai 11 September 2026 tak ada sama sekali: seluruh daftar sandi bisa
    # dicoba satu per satu, dan tak ada baris di mana pun yang mencatatnya.
    sisa = gerbang.boleh_coba(uname, ip or "")
    if sisa is not None:
        return render(
            request, "masuk.html", tujuan=tujuan,
            pesan_err=(f"Terlalu banyak percobaan. Coba lagi "
                       f"{int(sisa // 60) + 1} menit lagi, atau hubungi Admin."),
        )

    akun = (await db.execute(
        select(TimbanganAkun).where(TimbanganAkun.username == uname)
    )).scalars().first()

    async def _tolak(pesan: str):
        """Catat kegagalannya, lalu tolak.

        Login gagal yang tak pernah diaudit berarti penebakan yang berlangsung
        berminggu-minggu tak meninggalkan satu baris pun di mana pun.
        """
        gerbang.catat_gagal(uname, ip or "")
        await service.catat_audit(
            db, akun=akun, aksi="LOGIN_GAGAL", entitas="akun",
            entitas_id=(akun.id if akun else uname[:40]),
            ringkasan=pesan, ip=ip,
        )
        await db.commit()
        return render(request, "masuk.html", tujuan=tujuan, pesan_err=pesan)

    # ── Akun BERSAMA dulu (identitas satu untuk semua aplikasi) ──
    #
    # Kredensial diperiksa paket: waktu jawab sama untuk nama yang tak ada,
    # status akun DAN orangnya di master, pintu pos timbang (operator & admin
    # ke atas). Profil pos timbang dibuat bila belum ada. Yang tak dikenal
    # sebagai akun bersama jatuh ke akun LAMA di bawah — selama belum
    # ditautkan, sandinya sendiri masih berlaku (tak ada hari tanpa sistem).
    bersama = None
    try:
        bersama, akun = await service.masuk_bersama(db, uname, sandi)
    except identitas.Tolak as e:
        if e.kode != 401:
            return await _tolak(e.pesan)
        if akun is None or akun.tertaut or not cek_sandi(sandi, akun.password_hash):
            return await _tolak("Nama pengguna atau kata sandi salah.")
        if akun.status != "aktif":
            return await _tolak("Akun ini sedang dinonaktifkan. Hubungi Admin.")
        # Dinonaktifkan di MASTER berarti tak lagi bekerja di sini sama sekali.
        if akun.user_id:
            from app.models import User as _User

            orang = await db.get(_User, akun.user_id)
            if orang is not None and (orang.status or "").lower() != "aktif":
                return await _tolak("Akun ini sedang dinonaktifkan. Hubungi Admin.")

    gerbang.catat_berhasil(uname, ip or "")

    # Kode perangkat TIDAK lagi diisi di sini. Dulu layar masuk memintanya,
    # dan siapa pun yang mengetik kode perangkat orang lain diam-diam
    # memindahkan deret nomor transaksi ke dirinya — dua perangkat tanpa
    # jaringan lalu bisa membuat nomor yang sama, persis yang hendak dicegah.
    # Sekarang kodenya melekat pada akun dan hanya Admin yang menetapkannya.
    akun.terakhir_login = sekarang()

    await service.catat_audit(
        db, akun=akun, aksi="LOGIN", entitas="akun", entitas_id=akun.id,
        perangkat=akun.perangkat_kode,
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    aman = request.url.scheme == "https"
    balasan = RedirectResponse(tujuan or f"{PREFIX}/", status_code=303)
    # Sesi akun bersama membawa nomor & versi akun BERSAMA: keluar-semua,
    # ganti sandi, reset, dan penonaktifan di Pos Produksi memutusnya di sini.
    if bersama is not None:
        token = buat_token_bersama(bersama.id, versi=bersama.token_version or 1)
        await identitas.catat_login(db, bersama)
    else:
        token = buat_token(akun.id, versi=akun.token_version or 1)
    balasan.set_cookie(
        NAMA_COOKIE, token, max_age=tsettings.sesi_hari * 24 * 3600,
        httponly=True, samesite="lax", secure=aman, path=PREFIX,
    )
    return balasan


@router.post("/keluar")
async def proses_keluar(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    # ── Keluar berarti keluar dari SEMUA perangkat ──
    #
    # Sebelumnya ia hanya menghapus cookie di perangkat yang menekannya, dan
    # token berlaku 180 hari. Di pos timbang perangkatnya dipakai bergantian
    # dan kadang tertinggal di mana saja; "Keluar" yang tak benar-benar
    # mengeluarkan adalah janji yang tak ditepati. Temuan QA T-19.
    akun.token_version = (akun.token_version or 1) + 1
    if akun.tertaut:
        # Akun bersama: versinya naik di paket → putus di semua aplikasi.
        await identitas.naikkan_versi(db, akun.akun_id)
    await service.catat_audit(
        db, akun=akun, aksi="LOGOUT", entitas="akun", entitas_id=akun.id,
        ringkasan="keluar dari semua perangkat",
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    balasan = RedirectResponse(f"{PREFIX}/masuk", status_code=303)
    balasan.delete_cookie(NAMA_COOKIE, path=PREFIX)
    return balasan


@router.get("/luring")
async def halaman_luring(request: Request):
    """Halaman cadangan yang dilayani service worker saat jaringan hilang."""
    return render(request, "luring.html")


@router.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Service worker, dilayani dari akar modul — bukan dari /static/.

    Peramban menolak service worker yang mengaku menaungi cakupan di ATAS
    letaknya sendiri. Disajikan dari `/static/sw.js`, pendaftaran untuk
    cakupan `/timbangan/` selalu gagal — diam-diam, hanya sebagai galat di
    konsol — sehingga halaman cadangan luring tidak pernah benar-benar
    aktif. Di pos timbang yang sinyalnya naik-turun, itu justru bagian yang
    paling dibutuhkan.

    Header `Service-Worker-Allowed` dipertahankan sebagai sabuk pengaman
    kedua bila suatu saat berkasnya dipindah lagi.
    """
    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": f"{PREFIX}/",
            # Jangan di-cache: inilah berkas yang memutuskan versi cache
            # lainnya. Kalau ia sendiri basi, pembaruan tidak pernah sampai.
            "Cache-Control": "no-cache",
        },
    )

"""Keamanan modul Timbangan: sesi cookie dan penjaga peran.

Sandi, bentuk token, dan keputusan "boleh masuk?" milik paket bersama
`hmu_identitas` sejak Tahap 2 rancang ulang (13 September 2026) — sama
dengan Pos Produksi, Meja, Gudang 2, dan Kantor. Perubahan yang HANYA menyentuh
folder vendored `hmu_identitas/` tidak memicu deploy layanan ini di Railway
(watch paths menandainya SKIPPED, 13 Sep 2026) — sentuh berkas di `app/`
juga, atau tambahkan `hmu_identitas/**` ke watch paths di dashboard. Yang tinggal di sini:
kunci HMAC modul ini, cookie, dan cara pos timbang menemukan PROFIL
(`timbangan_akun`) dari sesi.

Dua rupa sesi hidup berdampingan selama masa penautan (lihat
`models.TimbanganAkun`):

  · token BERSAMA (`b`: 1) — `sub` = nomor akun bersama, versi = versi akun
    bersama. Diterbitkan saat orang masuk dengan akun bersama. Keluar-semua,
    ganti sandi, reset, dan penonaktifan di Pos Produksi memutusnya di sini.
  · token LAMA — `sub` = nomor `timbangan_akun`, versi = versi akun lama.
    Masih diterima untuk akun yang belum ditautkan, DAN untuk profil yang
    baru ditautkan sementara petugasnya masih bertugas: penautan tak boleh
    mengeluarkan orang dari pos di tengah truk yang sedang ditimbang. Ia
    berakhir saat orangnya masuk lagi atau tokennya kedaluwarsa, dan tetap
    tunduk pada saklar nonaktif bersama.
"""
from __future__ import annotations

import logging
import os

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan.config import tsettings
from app.timbangan.db import get_db
from app.timbangan.models import ROLE_SUPERADMIN, TimbanganAkun
from hmu_identitas import masuk as identitas
from hmu_identitas import token as _token
from hmu_identitas.sandi import cek_sandi, hash_sandi  # noqa: F401  (pemakai lama)

log = logging.getLogger("timbangan.security")

NAMA_COOKIE = "timbangan_sesi"
#: Isian tambahan di token yang menandai "sub = akun bersama".
TANDA_BERSAMA = "b"


class ButuhLogin(Exception):
    """Belum login — pengguna diarahkan ke halaman masuk."""


class AksesDitolak(Exception):
    """Sudah login tetapi peran tidak mencukupi."""

    def __init__(self, pesan: str = "Halaman ini tidak tersedia untuk peran Anda."):
        super().__init__(pesan)
        self.pesan = pesan


# ─────────────────────────── Sesi ───────────────────────────

_KUNCI_SEMENTARA: bytes | None = None


def _kunci() -> bytes:
    rahasia = tsettings.secret_key
    if not rahasia:
        # Cadangan: kunci acak per proses. Sesi hangus saat restart — cukup
        # aman, tetapi di produksi WAJIB set TIMBANGAN_SECRET_KEY.
        global _KUNCI_SEMENTARA
        if _KUNCI_SEMENTARA is None:
            _KUNCI_SEMENTARA = os.urandom(32)
            log.warning(
                "TIMBANGAN_SECRET_KEY belum diset — memakai kunci sementara; "
                "semua sesi login akan hangus setiap kali server restart."
            )
        return _KUNCI_SEMENTARA
    return _token.kunci_dari(rahasia)


#: Satu-satunya tempat yang sah dituju sesudah masuk.
AKAR = "/timbangan/"


def _umur_detik(hari: int | None = None) -> int:
    return (hari or tsettings.sesi_hari) * 24 * 3600


def buat_token(akun_id: int, *, hari: int | None = None, versi: int = 1) -> str:
    """Token bentuk LAMA: sub = `timbangan_akun.id`. Dipakai akun yang belum
    ditautkan (dan uji lama)."""
    return _token.buat_token(_kunci(), akun_id=akun_id, versi=versi, umur_detik=_umur_detik(hari))


def buat_token_bersama(akun_bersama_id: int, *, versi: int) -> str:
    """Token untuk sesi akun bersama: sub = `produksi_akun.id`, ditandai."""
    return _token.buat_token(_kunci(), akun_id=akun_bersama_id, versi=versi,
                             umur_detik=_umur_detik(), ekstra={TANDA_BERSAMA: 1})


def baca_token(token: str | None) -> tuple[int, int] | None:
    """(id, versi) bila sah — bentuk lama, untuk pemakai lama. Tak melempar."""
    d = _token.baca_token(_kunci(), token)
    return None if d is None else (d["akun_id"], d["versi"])


def token_masih_berlaku(dibaca: tuple[int, int] | None, *, versi_akun: int) -> bool:
    return dibaca is not None and dibaca[1] >= int(versi_akun or 1)


def tujuan_aman(nilai: str | None) -> str:
    """Alamat tujuan sesudah masuk — hanya di dalam modul ini sendiri (QA T-20)."""
    v = (nilai or "").strip()
    if not v.startswith(AKAR):
        return AKAR
    if any(c in v for c in ("\r", "\n", "\\", "..")):
        return AKAR
    return v


# ─────────────────────────── Dependency ───────────────────────────

async def _profil_dari_sesi(db: AsyncSession, d: dict) -> TimbanganAkun | None:
    """Profil pos timbang untuk token yang sudah terbaca — atau None."""
    from app.timbangan import service

    if d.get(TANDA_BERSAMA):
        # SATU fungsi "boleh masuk?" untuk semua aplikasi: akun bersama ada &
        # aktif, orangnya aktif di `users`, versi sepadan (QA X-11, P-S-05).
        bersama = await identitas.akun_aktif(db, d["akun_id"], d["versi"])
        if bersama is None:
            return None
        profil = (await db.execute(
            select(TimbanganAkun).where(TimbanganAkun.akun_id == bersama.id,
                                        TimbanganAkun.status == "aktif")
        )).scalars().first()
        if profil is not None:
            await service.sinkron_profil(db, profil, bersama)
        return profil

    # Bentuk lama: sub = timbangan_akun.id
    akun = (await db.execute(
        select(TimbanganAkun).where(TimbanganAkun.id == d["akun_id"],
                                    TimbanganAkun.status == "aktif")
    )).scalars().first()
    if akun is None or not token_masih_berlaku((d["akun_id"], d["versi"]),
                                               versi_akun=getattr(akun, "token_version", 1)):
        return None
    if akun.tertaut:
        # Petugas yang bertugas saat akunnya ditautkan: token lamanya masih
        # diterima — tetapi saklar nonaktif bersama tetap berlaku.
        bersama = await identitas.akun_aktif(db, akun.akun_id, 10 ** 9)
        if bersama is None:
            return None
        await service.sinkron_profil(db, akun, bersama)
        return akun
    if akun.user_id:
        # Akun lama yang sudah menunjuk orang di master: dinonaktifkan di
        # sana berarti tak lagi bekerja di sini (QA X-11).
        from app.models import User as _User
        orang = await db.get(_User, akun.user_id)
        if orang is not None and (orang.status or "").lower() != "aktif":
            return None
    return akun


async def akun_opsional(request: Request) -> TimbanganAkun | None:
    """Profil dari cookie sesi, atau None. Tidak pernah melempar error."""
    from app.timbangan.db import sesi_db

    d = _token.baca_token(_kunci(), request.cookies.get(NAMA_COOKIE))
    akun = None
    if d is not None:
        async with sesi_db() as db:
            akun = await _profil_dari_sesi(db, d)
    request.state.akun = akun
    return akun


async def butuh_akun(request: Request) -> TimbanganAkun:
    """Wajib login. Bila belum → diarahkan ke halaman masuk."""
    akun = await akun_opsional(request)
    if akun is None:
        raise ButuhLogin()
    return akun


async def butuh_admin(akun: TimbanganAkun = Depends(butuh_akun)) -> TimbanganAkun:
    """Admin maupun Super Admin."""
    if not akun.is_admin:
        raise AksesDitolak("Halaman ini hanya untuk Admin.")
    return akun


async def butuh_super(akun: TimbanganAkun = Depends(butuh_akun)) -> TimbanganAkun:
    """Super Admin saja."""
    if not akun.is_super:
        raise AksesDitolak("Halaman ini hanya untuk Super Admin.")
    return akun


async def ada_super_aktif(db: AsyncSession) -> bool:
    """Super Admin aktif — akun bersama (paket) ATAU akun lama yang belum
    ditautkan. Keduanya dihitung: jaring pengaman "belum ada Super Admin →
    Admin diterima" tak boleh terbuka hanya karena Super Admin-nya sudah
    pindah ke akun bersama."""
    if await identitas.ada_superadmin_aktif(db):
        return True
    return bool((await db.execute(
        select(func.count(TimbanganAkun.id)).where(
            TimbanganAkun.role == ROLE_SUPERADMIN,
            TimbanganAkun.status == "aktif",
            TimbanganAkun.akun_id.is_(None),
        )
    )).scalar_one())


async def butuh_super_atau_pertama(
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
) -> TimbanganAkun:
    """Super Admin — atau Admin, SELAMA belum ada Super Admin yang aktif.

    Pengelolaan pengguna adalah wewenang Super Admin. Tetapi mengunci
    halamannya rapat-rapat akan membuat Super Admin PERTAMA tidak mungkin
    dibuat. Pintunya menutup sendiri begitu ada satu Super Admin aktif.
    """
    if akun.is_super:
        return akun
    if akun.is_admin and not await ada_super_aktif(db):
        return akun
    raise AksesDitolak("Pengelolaan pengguna hanya untuk Super Admin.")

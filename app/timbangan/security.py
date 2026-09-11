"""Keamanan modul Timbangan: sandi, sesi cookie, dan penjaga peran (RBAC).

Tanpa dependensi tambahan — memakai `hashlib.scrypt` (KDF modern di pustaka
standar) dan cookie bertanda tangan HMAC-SHA256.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan.config import tsettings
from app.timbangan.db import get_db
from app.timbangan.models import TimbanganAkun

log = logging.getLogger("timbangan.security")

NAMA_COOKIE = "timbangan_sesi"

# Parameter scrypt: seimbang antara aman & ringan untuk server kecil.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1


class ButuhLogin(Exception):
    """Belum login — pengguna diarahkan ke halaman masuk."""


class AksesDitolak(Exception):
    """Sudah login tetapi peran tidak mencukupi."""

    def __init__(self, pesan: str = "Halaman ini tidak tersedia untuk peran Anda."):
        super().__init__(pesan)
        self.pesan = pesan


# ─────────────────────────── Sandi ───────────────────────────

def hash_sandi(sandi: str) -> str:
    """Hash sandi → 'scrypt$n$r$p$salt$hash' (salt acak per pengguna)."""
    if not sandi or len(sandi) < 6:
        raise ValueError("Kata sandi minimal 6 karakter.")
    salt = secrets.token_bytes(16)
    kunci = hashlib.scrypt(
        sandi.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${kunci.hex()}"


def cek_sandi(sandi: str, tersimpan: str) -> bool:
    """Verifikasi sandi terhadap hash tersimpan (tahan timing attack)."""
    try:
        skema, n, r, p, salt_hex, hash_hex = (tersimpan or "").split("$")
        if skema != "scrypt":
            return False
        kunci = hashlib.scrypt(
            (sandi or "").encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(kunci.hex(), hash_hex)


# ─────────────────────────── Sesi ───────────────────────────

def _kunci() -> bytes:
    rahasia = tsettings.secret_key
    if not rahasia:
        # Cadangan: kunci acak per proses. Sesi hangus saat restart — cukup
        # aman, tetapi di produksi WAJIB set TIMBANGAN_SECRET_KEY.
        global _KUNCI_SEMENTARA
        try:
            return _KUNCI_SEMENTARA
        except NameError:
            _KUNCI_SEMENTARA = os.urandom(32)
            log.warning(
                "TIMBANGAN_SECRET_KEY belum diset — memakai kunci sementara; "
                "semua sesi login akan hangus setiap kali server restart."
            )
            return _KUNCI_SEMENTARA
    return hashlib.sha256(rahasia.encode()).digest()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


#: Batas atas nomor akun yang masuk akal. Id di luar rentang ini dulu sampai
#: ke basis data apa adanya.
_MAKS_ID = 2 ** 31 - 1

#: Satu-satunya tempat yang sah dituju sesudah masuk.
AKAR = "/timbangan/"


def buat_token(akun_id: int, *, hari: int | None = None, versi: int = 1) -> str:
    """Token sesi bertanda tangan: <payload>.<signature>.

    Sesi berlaku sampai petugas menekan Keluar — tiap orang memakai
    perangkatnya sendiri, jadi membukanya lagi tidak boleh meminta login.
    Batas hari di sini hanya jaring pengaman, bukan pengusir harian.

    `versi` adalah versi sesi akun, dan ia yang membuat Keluar berarti sesuatu
    di perangkat yang TIDAK sedang dipegang. Tanpanya token berlaku 180 hari
    tanpa bisa dicabut oleh apa pun: sesudah petugas mengganti sandinya lalu
    menekan Keluar, cookie lama di perangkat lain tetap dijawab 200.
    Temuan QA T-19.
    """
    kedaluwarsa = datetime.now(timezone.utc) + timedelta(
        days=hari or tsettings.sesi_hari
    )
    payload = _b64e(json.dumps(
        {"sub": int(akun_id), "exp": int(kedaluwarsa.timestamp()),
         "v": int(versi or 1)},
        separators=(",", ":"),
    ).encode())
    tanda = _b64e(hmac.new(_kunci(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{tanda}"


def baca_token(token: str | None) -> tuple[int, int] | None:
    """(akun_id, versi) bila token sah & belum kedaluwarsa; selain itu None.

    Tak pernah melempar: cookie datang dari luar, jadi isinya bisa apa saja —
    termasuk huruf non-ASCII, yang menjatuhkan `compare_digest` dengan
    TypeError dan membuat setiap halaman menjawab 500.
    """
    if not token or "." not in token:
        return None
    try:
        payload, _, tanda = token.partition(".")
        harapan = _b64e(hmac.new(_kunci(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(tanda, harapan):
            return None
        data = json.loads(_b64d(payload))
        if int(data["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            return None
        akun_id = int(data["sub"])
        if not 0 < akun_id <= _MAKS_ID:
            return None
        # Token lama (dibuat sebelum kolom versi ada) dianggap versi 1: deploy
        # tak boleh memutus semua petugas sekaligus.
        return akun_id, int(data.get("v", 1) or 1)
    except (ValueError, KeyError, TypeError, UnicodeError, AttributeError):
        return None


def token_masih_berlaku(dibaca: tuple[int, int] | None, *, versi_akun: int) -> bool:
    """Apakah token yang sudah dibaca masih sepadan dengan versi akunnya."""
    return dibaca is not None and dibaca[1] >= int(versi_akun or 1)


def tujuan_aman(nilai: str | None) -> str:
    """Alamat tujuan sesudah masuk — hanya di dalam modul ini sendiri.

    Halaman masuk yang mengantar petugas ke situs lain bisa dipakai memanen
    sandinya: alamat yang diketik benar, tampilannya benar, dan yang terbuka
    berikutnya bukan milik kita. `//evil.example` bentuk yang paling sering
    terlewat — peramban membacanya sebagai alamat lengkap tanpa skema.
    Temuan QA T-20.
    """
    v = (nilai or "").strip()
    if not v.startswith(AKAR):
        return AKAR
    if any(c in v for c in ("\r", "\n", "\\", "..")):
        return AKAR
    return v


# ─────────────────────────── Dependency ───────────────────────────

async def akun_opsional(request: Request) -> TimbanganAkun | None:
    """Akun dari cookie sesi, atau None. Tidak pernah melempar error."""
    from sqlalchemy import select

    from app.models import User as _User
    from app.timbangan.db import sesi_db

    dibaca = baca_token(request.cookies.get(NAMA_COOKIE))
    if dibaca is None:
        return None
    akun_id, _versi = dibaca
    async with sesi_db() as db:
        akun = (
            await db.execute(
                select(TimbanganAkun).where(
                    TimbanganAkun.id == akun_id,
                    TimbanganAkun.status == "aktif",
                )
            )
        ).scalars().first()
        # Versi sesi: token yang dibuat sebelum petugas keluar, mengganti
        # sandinya, atau perannya berubah sudah bukan miliknya lagi.
        if akun is not None and not token_masih_berlaku(
                dibaca, versi_akun=getattr(akun, "token_version", 1)):
            akun = None
        # ── Dinonaktifkan di MASTER berarti tak lagi bekerja di sini ──
        #
        # Ada tiga bendera nonaktif yang terpisah — `users.status`,
        # `produksi_akun.status`, dan `timbangan_akun.status` — dan modul ini
        # hanya pernah melihat yang terakhir. Orang yang dinonaktifkan di
        # Kelola pengguna produksi karenanya tetap bisa menimbang truk.
        # Temuan QA X-11.
        #
        # Akun tanpa `user_id` tetap diterima: petugas timbang lama memang
        # belum tertaut ke master, dan menolak mereka berarti menutup pos
        # timbang atas nama data yang belum dirapikan.
        if akun is not None and akun.user_id:
            orang = await db.get(_User, akun.user_id)
            if orang is not None and (orang.status or "").lower() != "aktif":
                akun = None
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
    from app.timbangan.models import ROLE_SUPERADMIN

    return bool((await db.execute(
        select(func.count(TimbanganAkun.id)).where(
            TimbanganAkun.role == ROLE_SUPERADMIN,
            TimbanganAkun.status == "aktif",
        )
    )).scalar_one())


async def butuh_super_atau_pertama(
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
) -> TimbanganAkun:
    """Super Admin — atau Admin, SELAMA belum ada Super Admin yang aktif.

    Pengelolaan pengguna adalah wewenang Super Admin. Tetapi mengunci
    halamannya rapat-rapat akan membuat Super Admin PERTAMA tidak mungkin
    dibuat: yang berhak membuatnya hanya bisa dibuat di halaman ini. Pintu
    yang sama juga satu-satunya jalan pulih bila satu-satunya akun Super
    Admin hilang atau terkunci.

    Pintunya menutup sendiri begitu ada satu Super Admin aktif, dan tidak
    bisa dibuka lagi oleh Admin — karena Admin tidak boleh menonaktifkan
    maupun menghapus akun Super Admin.
    """
    if akun.is_super:
        return akun
    if akun.is_admin and not await ada_super_aktif(db):
        return akun
    raise AksesDitolak("Pengelolaan pengguna hanya untuk Super Admin.")

"""Menautkan akun pos timbang ke akun bersama — per orang, bisa dibalik.

Tahap 2 rancang ulang (13 Sep 2026), butir 4: "akun timbangan disatukan ke
akun bersama tanpa memutus petugas yang sedang bertugas". Caranya bukan
memindahkan baris (riwayat timbang menunjuk `timbangan_akun.id` lewat 14
kolom foreign key) melainkan MENAUTKAN: `timbangan_akun.akun_id` diisi,
sandi lamanya dibiarkan. Sesudah itu orangnya masuk dengan sandi akun
bersama; token lamanya tetap diterima sampai ia masuk lagi.

Tiga langkah, dan hanya yang pertama yang dijalankan tanpa bendera:

  1. `rencana(db)`   — baca saja: untuk tiap akun pos timbang yang belum
                        tertaut, tentukan padanannya dan apa yang akan
                        dilakukan. Dicetak untuk ditinjau pemilik.
  2. `terapkan(db)`  — jalankan rencana itu. Akun bersama yang belum ada
                        DIBUAT dengan sandi hash yang sama (format scrypt
                        sama), jadi orangnya masuk dengan sandi yang ia
                        kenal. Tak ada `token_version` pos timbang yang
                        dinaikkan: yang bertugas tetap bertugas.
  3. `lepas(db)`     — mundur: kosongkan `akun_id`. Sandi lama masih ada,
                        jadi pintu lama langsung berlaku lagi. Akun bersama
                        yang sempat dibuat dibiarkan (tak berbahaya; bisa
                        dinonaktifkan di Pos Produksi).

Padanan dicari berurutan: (a) `user_id` sudah menunjuk orang yang punya akun
bersama; (b) nama pengguna yang sama di akun bersama; (c) orang di `users`
yang namanya sama persis (tanpa memandang huruf besar) dan belum punya akun
bersama → akun bersama dibuat untuknya; (d) tak ada padanan → orang baru
di `users` + akun bersama baru, perannya dipetakan dari peran pos timbang.
Bila (b) cocok tetapi (a) menunjuk orang lain, itu KONFLIK — tak disentuh,
disebut di rencana untuk diputuskan orang.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan.models import TimbanganAkun
from hmu_core import User
from hmu_identitas import peran as P
from hmu_identitas.model import AKTIF, Akun, mode_bawaan
from hmu_identitas.sandi import hash_sandi

TAUT, BUAT_AKUN, BUAT_ORANG, KONFLIK, SUDAH = "taut", "buat-akun", "buat-orang", "KONFLIK", "sudah"


@dataclass
class Langkah:
    profil_id: int
    username: str
    nama: str
    role_lama: str
    tindakan: str
    akun_id: int | None = None       # akun bersama yang akan ditaut (TAUT)
    user_id: int | None = None       # orang di users (BUAT_AKUN)
    keterangan: str = ""
    catatan: list[str] = field(default_factory=list)


async def rencana(db: AsyncSession) -> list[Langkah]:
    """Baca saja — tak mengubah apa pun."""
    hasil: list[Langkah] = []
    profil = (await db.execute(select(TimbanganAkun).order_by(TimbanganAkun.id))).scalars().all()
    for t in profil:
        if t.akun_id is not None:
            hasil.append(Langkah(t.id, t.username, t.nama, t.role, SUDAH, akun_id=t.akun_id,
                                 keterangan="sudah tertaut"))
            continue
        lewat_user = None
        if t.user_id:
            lewat_user = (await db.execute(select(Akun).where(Akun.user_id == t.user_id))).scalars().first()
        lewat_nama = (await db.execute(select(Akun).where(Akun.username == t.username))).scalars().first()
        if lewat_user is not None and lewat_nama is not None and lewat_user.id != lewat_nama.id:
            hasil.append(Langkah(t.id, t.username, t.nama, t.role, KONFLIK,
                                 keterangan=f"user_id menunjuk akun '{lewat_user.username}' (#{lewat_user.id}), "
                                            f"tetapi nama pengguna sama dengan akun #{lewat_nama.id} milik "
                                            f"{lewat_nama.nama} — putuskan dulu"))
            continue
        padanan = lewat_user or lewat_nama
        if padanan is not None:
            l = Langkah(t.id, t.username, t.nama, t.role, TAUT, akun_id=padanan.id,
                        keterangan=f"→ akun bersama #{padanan.id} '{padanan.username}' ({padanan.nama}, {padanan.peran})")
            l.catatan.append("sandi berikutnya = sandi Pos Produksi; token lama tetap berlaku")
            if P.ke_timbangan(padanan.peran) != t.role:
                l.catatan.append(f"peran pos timbang {t.role} → {P.ke_timbangan(padanan.peran)} (mengikuti users.role)")
            hasil.append(l)
            continue
        orang = None
        if t.user_id:
            orang = await db.get(User, t.user_id)
        if orang is None:
            kandidat = (await db.execute(
                select(User).where(func.lower(User.nama) == t.nama.strip().lower())
            )).scalars().all()
            kandidat = [u for u in kandidat
                        if (await db.execute(select(Akun.id).where(Akun.user_id == u.id))).scalar() is None]
            if len(kandidat) == 1:
                orang = kandidat[0]
            elif len(kandidat) > 1:
                hasil.append(Langkah(t.id, t.username, t.nama, t.role, KONFLIK,
                                     keterangan=f"{len(kandidat)} orang bernama '{t.nama}' di users tanpa akun — pilih dulu"))
                continue
        if orang is not None:
            l = Langkah(t.id, t.username, t.nama, t.role, BUAT_AKUN, user_id=orang.id,
                        keterangan=f"buat akun bersama '{t.username}' untuk users #{orang.id} ({orang.nama}, {orang.role})")
            l.catatan.append("sandi = sandi pos timbang yang sekarang (hash disalin)")
            if P.ke_timbangan(orang.role) != t.role:
                l.catatan.append(f"peran pos timbang {t.role} → {P.ke_timbangan(orang.role)} (mengikuti users.role)")
            hasil.append(l)
        else:
            l = Langkah(t.id, t.username, t.nama, t.role, BUAT_ORANG,
                        keterangan=f"buat orang '{t.nama}' ({P.dari_timbangan(t.role)}) + akun bersama '{t.username}'")
            l.catatan.append("sandi = sandi pos timbang yang sekarang (hash disalin)")
            hasil.append(l)
    return hasil


async def terapkan(db: AsyncSession, daftar: list[Langkah] | None = None) -> list[Langkah]:
    """Jalankan rencana. KONFLIK dan SUDAH dilewati. Mengembalikan yang dikerjakan."""
    daftar = daftar if daftar is not None else await rencana(db)
    dikerjakan: list[Langkah] = []
    for l in daftar:
        if l.tindakan in (KONFLIK, SUDAH):
            continue
        t = await db.get(TimbanganAkun, l.profil_id)
        if t is None or t.akun_id is not None:
            continue
        if l.tindakan == TAUT:
            akun = await db.get(Akun, l.akun_id)
        else:
            if l.tindakan == BUAT_ORANG:
                orang = User(nama=t.nama.strip(), role=P.dari_timbangan(t.role), status=AKTIF)
                db.add(orang)
                await db.flush()
                l.user_id = orang.id
            else:
                orang = await db.get(User, l.user_id)
            if not t.password_hash:
                l.catatan.append("tanpa sandi lama — dibuat dengan sandi acak yang HARUS diganti")
            akun = Akun(user_id=orang.id, username=t.username,
                        password_hash=t.password_hash or hash_sandi(secrets.token_urlsafe(12)),
                        status=AKTIF if t.status == AKTIF else "nonaktif",
                        mode_perangkat=mode_bawaan(orang.role),
                        harus_ganti_sandi=not t.password_hash)
            db.add(akun)
            await db.flush()
            l.akun_id = akun.id
        t.akun_id = akun.id
        t.user_id = akun.user_id
        t.nama = akun.nama
        t.role = P.ke_timbangan(akun.peran)
        # Sandi lama SENGAJA tidak dihapus di sini: itulah yang membuat
        # `lepas()` bisa mengembalikan pintu lama tanpa kehilangan apa pun.
        # Ia dikosongkan saat orangnya masuk pertama kali dengan akun bersama.
        dikerjakan.append(l)
    await db.commit()
    return dikerjakan


async def lepas(db: AsyncSession) -> int:
    """Mundur: lepaskan semua tautan. Mengembalikan jumlah baris."""
    profil = (await db.execute(select(TimbanganAkun).where(TimbanganAkun.akun_id.isnot(None)))).scalars().all()
    for t in profil:
        t.akun_id = None
    await db.commit()
    return len(profil)


def cetak(daftar: list[Langkah]) -> str:
    baris = [f"{'#':>4}  {'pengguna':<16}{'nama':<24}{'peran':<11}{'tindakan':<11}keterangan"]
    for l in daftar:
        baris.append(f"{l.profil_id:>4}  {l.username:<16}{l.nama[:23]:<24}{l.role_lama:<11}{l.tindakan:<11}{l.keterangan}")
        for c in l.catatan:
            baris.append(f"{'':>4}  {'':<16}{'':<24}{'':<11}{'':<11}· {c}")
    n = {k: sum(1 for l in daftar if l.tindakan == k) for k in (TAUT, BUAT_AKUN, BUAT_ORANG, KONFLIK, SUDAH)}
    baris.append(f"\ntaut {n[TAUT]} · buat akun {n[BUAT_AKUN]} · buat orang {n[BUAT_ORANG]} · "
                 f"KONFLIK {n[KONFLIK]} · sudah tertaut {n[SUDAH]}")
    return "\n".join(baris)

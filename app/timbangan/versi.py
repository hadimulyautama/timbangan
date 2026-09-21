"""Versi kode Pos Timbang yang SEDANG BERJALAN — supaya terbaca dari ponsel.

Padanan `app/web/versi.py` di repo produksi, lahir dari kejadian yang sama
(21 September 2026): pemilik melaporkan galat yang sudah diperbaiki, dan
butuh satu putaran QA penuh hanya untuk tahu bahwa yang berjalan di
ponselnya masih kode lama. Pos timbang punya rantai migrasinya sendiri
(`alembic_version_timbangan`), jadi pemeriksaannya pun sendiri.

Commit-nya dari `RAILWAY_GIT_COMMIT_SHA` (deploy yang dipicu GitHub), atau
berkas `KOMIT` yang ditulis Dockerfile dari variabel yang sama, atau — di
laptop — `git`. Tak ada variabel lain yang dibaca: nilainya ditampilkan di
layar, dan layar bukan tempat nilai variabel apa pun selain hash commit.
"""
from __future__ import annotations

import functools
import os
import pathlib
import subprocess

from app.timbangan import skema

AKAR = pathlib.Path(__file__).resolve().parents[2]
BERKAS_KOMIT = AKAR / "KOMIT"
PANJANG = 7

SELARAS = "selaras"
TERTINGGAL = "tertinggal"     # basis data di belakang kode: migrasi belum jalan
KODE_LAMA = "kode_lama"       # basis data di DEPAN kode: yang berjalan kode lama
TAK_TERBACA = "tak_terbaca"   # tabel versi tak ada / basis data tak terjangkau


def _bersih(sha: str | None) -> str | None:
    sha = (sha or "").strip()
    return sha[:PANJANG] if sha else None


def _dari_lingkungan() -> str | None:
    return _bersih(os.environ.get("RAILWAY_GIT_COMMIT_SHA"))


def _dari_berkas() -> str | None:
    try:
        return _bersih(BERKAS_KOMIT.read_text())
    except OSError:
        return None


def _dari_git() -> str | None:
    """Laptop saja: image tak membawa `.git`."""
    if not (AKAR / ".git").exists():
        return None
    try:
        hasil = subprocess.run(
            ["git", "rev-parse", f"--short={PANJANG}", "HEAD"],
            cwd=AKAR, capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _bersih(hasil.stdout) if hasil.returncode == 0 else None


@functools.lru_cache(maxsize=1)
def komit() -> str | None:
    """Hash commit pendek kode ini; None bila tak ada satu pun sumber."""
    return _dari_lingkungan() or _dari_berkas() or _dari_git()


def banding(revisi: str | None, head: str | None) -> str:
    if not revisi or not head:
        return TAK_TERBACA
    if revisi == head:
        return SELARAS
    return TERTINGGAL if revisi in skema.revisi_berkas() else KODE_LAMA


async def info() -> dict:
    """Bahan baris versi di Pengaturan. Tak pernah melempar."""
    from app.timbangan.web import VERSI

    keadaan = await skema.keadaan()
    return {
        "versi": VERSI,
        "komit": komit(),
        "revisi": keadaan["revisi"],
        "head": keadaan["head"],
        "keadaan": banding(keadaan["revisi"], keadaan["head"]),
    }

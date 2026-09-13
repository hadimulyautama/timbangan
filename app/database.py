"""Engine SQLAlchemy async, pabrik sesi, dan Base deklaratif.

Disalin dari repo penggilingan lalu dipangkas: yang tinggal hanya bagian yang
benar-benar dipakai modul ini. Helper backdate (`input_time`, `BackdateError`)
tidak ikut — pencatatan waktu di Timbangan punya aturannya sendiri di
`app/timbangan/db.py`, yang mengikuti jam timbang operator.

`SessionLocal` sengaja diambil LEWAT modul ini, bukan di-import objeknya
langsung, supaya pengujian bisa mengalihkan koneksi ke database uji.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Engine dibangun saat PERTAMA DIPAKAI, bukan saat modul diimpor.
#
# Mengimpor aplikasi tidak boleh menuntut database: pengujian memakai SQLite
# sementara lalu mengalihkan `SessionLocal`, dan perkakas seperti pembaca
# metadata Alembic hanya butuh definisi tabelnya. Membangunnya di tingkat
# modul membuat semua itu gagal hanya karena satu variabel lingkungan.
#
# `SessionLocal` tetap ATRIBUT SUNGGUHAN, bukan `__getattr__` modul, karena
# `monkeypatch.setattr` membaca nilai lamanya lebih dulu untuk dikembalikan
# saat uji selesai — pembacaan itu sendiri sudah cukup untuk memicu koneksi.
_engine = None
_pabrik = None


def _siapkan() -> None:
    global _engine, _pabrik
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL belum diset — tidak bisa menyambung ke database."
        )
    # ── Zona sesi basis data disetel EKSPLISIT ──
    #
    # Postgres di Railway berzona UTC, dan beberapa kueri memakai
    # `CURRENT_DATE` atau mengelompokkan tanggal di sisi SQL. Tanpa setelan
    # ini, "hari ini" menurut basis data berganti pukul 07:00 WIB — jadi truk
    # yang ditimbang pukul 05:30 masuk rekap hari sebelumnya. Temuan QA X-17.
    #
    # Per KONEKSI, bukan lewat variabel lingkungan kontainer: yang menentukan
    # adalah sesi Postgres-nya, dan kontainer yang zonanya benar pun tetap
    # membuka sesi berzona UTC.
    _engine = create_async_engine(
        settings.database_url, echo=False, pool_pre_ping=True,
        connect_args={"server_settings": {"timezone": settings.app_timezone}},
    )
    _pabrik = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )


def dapatkan_engine():
    """Engine async, dibangun saat pertama diminta."""
    if _engine is None:
        _siapkan()
    return _engine


class _PabrikSesi:
    """Pemanggilannya membuka sesi; keberadaannya tidak menyambung apa pun."""

    def __call__(self, *args, **kwargs) -> AsyncSession:
        if _pabrik is None:
            _siapkan()
        return _pabrik(*args, **kwargs)


SessionLocal = _PabrikSesi()


def now_local() -> datetime:
    """Waktu sekarang di zona waktu aplikasi (bawaan Asia/Jakarta)."""
    return datetime.now(ZoneInfo(settings.app_timezone))


# ── Base & TimestampMixin dari paket bersama `hmu_core` ──
#
# Sejak Tahap 2 rancang ulang (13 September 2026) pos timbang memakai
# identitas bersama: tabel `users` dan `produksi_akun` dipetakan model
# `hmu_core.User` dan `hmu_identitas.model.Akun`, dan foreign key
# `timbangan_akun.akun_id` menunjuk ke sana. Semua itu hanya bisa hidup di
# SATU metadata, jadi Base-nya harus satu — yang dulu di sini adalah salinan
# kata demi kata, kini diimpor. Isinya tak berubah.
from hmu_core import Base, TimestampMixin  # noqa: E402,F401


async def get_session() -> AsyncSession:
    """Dependency FastAPI: satu sesi per permintaan."""
    async with SessionLocal() as session:
        yield session

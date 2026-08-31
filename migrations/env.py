"""Alembic environment — async (asyncpg), URL & metadata dari aplikasi.

**Tabel versinya sendiri: `alembic_version_timbangan`.** Database ini dipakai
bersama sistem penggilingan, yang punya rangkaian migrasinya sendiri di
`alembic_version`. Dua rangkaian tidak bisa berbagi satu tabel versi — yang
satu akan mengira migrasi yang lain hilang, lalu menolak jalan.

`include_object` menutup sisi kedua dari pemisahan itu: autogenerate hanya
boleh melihat tabel milik modul ini. Tanpa itu, `alembic revision
--autogenerate` di repo ini akan menawarkan MENGHAPUS seluruh tabel
penggilingan, karena tabel-tabel itu memang tidak ada di metadata sini.
Tabel `suppliers` ikut dikecualikan meski dipetakan di `app/models.py`:
ia dibaca, bukan dimiliki.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database import Base
from app.models import Supplier  # noqa: F401  (daftarkan sasaran foreign key)
from app.timbangan import models  # noqa: F401  (daftarkan tabel modul)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

TABEL_VERSI = "alembic_version_timbangan"


def include_object(objek, nama, tipe, reflected, compare_to):
    if tipe == "table":
        return str(nama).startswith("timbangan_")
    return True


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=TABEL_VERSI,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        version_table=TABEL_VERSI,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

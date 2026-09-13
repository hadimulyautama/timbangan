"""Skenario identitas bersama yang sama, di Postgres sungguhan.

Berkas uji SQLite-nya dimuat lewat jalur (folder `tests/` bukan paket),
lalu fungsi-fungsi ujinya dijalankan di atas fixture `mesin`/`klien` Postgres
dari conftest di sini.
"""
from __future__ import annotations

import importlib.util
import pathlib

_b = pathlib.Path(__file__).resolve().parents[1] / "timbangan" / "test_identitas.py"
_spec = importlib.util.spec_from_file_location("uji_identitas_sqlite", _b)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)

test_akun_bersama_masuk_dan_profilnya_tersinkron = _m.test_akun_bersama_masuk_dan_profilnya_tersinkron
test_akun_lama_belum_tertaut_masih_masuk_dengan_sandinya = _m.test_akun_lama_belum_tertaut_masih_masuk_dengan_sandinya
test_petugas_bertugas_tak_terputus_saat_akunnya_ditautkan = _m.test_petugas_bertugas_tak_terputus_saat_akunnya_ditautkan
test_satu_saklar_nonaktif_memutus_token_baru_dan_lama = _m.test_satu_saklar_nonaktif_memutus_token_baru_dan_lama
test_versi_bersama_naik_memutus_sesi_di_sini = _m.test_versi_bersama_naik_memutus_sesi_di_sini
test_tambah_profil_untuk_akun_bersama_lewat_layar_pengguna = _m.test_tambah_profil_untuk_akun_bersama_lewat_layar_pengguna
test_super_admin_bersama_menutup_jaring_pengaman = _m.test_super_admin_bersama_menutup_jaring_pengaman

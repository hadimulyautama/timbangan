"""Konfigurasi modul Timbangan — dibaca dari environment.

Yang TIDAK ada di sini: ambang kontrol, tara, dan aturan komoditas. Semua itu
hidup di tabel `timbangan_jenis` (RANCANGAN §9.1 butir a) supaya menambah atau
merevisi komoditas cukup dengan mengubah satu baris data — tidak perlu deploy
ulang, dan tiap transaksi menyimpan salinan aturannya sendiri.

Di sini hanya hal yang memang milik lingkungan: kunci sesi, batas unggah,
identitas alat, dan identitas perusahaan yang tercetak di bukti timbang.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.timbangan import logic


def _f(nama: str, default: float) -> float:
    try:
        return float(os.getenv(nama, "") or default)
    except ValueError:
        return default


def _i(nama: str, default: int) -> int:
    try:
        return int(os.getenv(nama, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class TimbanganSettings:
    # ── Sesi ──
    # Kunci penandatangan cookie sesi. WAJIB diisi di produksi (Railway env).
    secret_key: str = os.getenv("TIMBANGAN_SECRET_KEY", "")
    # Sesi berlaku sampai logout — tiap petugas memakai perangkatnya sendiri.
    # Nilai ini hanya batas atas keamanan (hari), bukan pengusir harian.
    sesi_hari: int = _i("TIMBANGAN_SESI_HARI", 180)

    # ── Alat ──
    # Kapasitas jembatan timbang. Angka di atas ini ditolak sebagai mustahil.
    kapasitas_jembatan_kg: float = _f(
        "TIMBANGAN_KAPASITAS_KG", logic.KAPASITAS_JEMBATAN_KG
    )
    # Kelipatan pembacaan tera alat — dipakai untuk peringatan angka janggal.
    kelipatan_tera_kg: float = _f("TIMBANGAN_KELIPATAN_TERA_KG", logic.KELIPATAN_TERA_KG)
    # Kapasitas timbangan kecil untuk partai kecil (bukan jembatan truk).
    kapasitas_timbangan_kecil_kg: float = _f(
        "TIMBANGAN_KAPASITAS_KECIL_KG", logic.KAPASITAS_TIMBANGAN_KECIL_KG
    )

    # ── Batas operasional ──
    # Batas ukuran satu foto bukti (byte). Foto disimpan di DB agar tidak hilang
    # saat container Railway di-deploy ulang (filesystem-nya sementara).
    maks_foto_byte: int = _i("TIMBANGAN_MAKS_FOTO_MB", 4) * 1024 * 1024
    # Jam sejak selesai sampai transaksi terkunci otomatis bagi petugas.
    # Setelah terkunci, koreksi hanya oleh Admin dan tetap tercatat di audit.
    jam_kunci_otomatis: int = _i("TIMBANGAN_JAM_KUNCI", 24)
    # Tiket timbang pertama yang menganggur lebih lama dari ini ditandai untuk
    # ditutup paksa (truk tidak jadi bongkar, atau petugas lupa).
    jam_tiket_menganggur: int = _i("TIMBANGAN_JAM_TIKET_MENGANGGUR", 12)
    # Sejauh mana petugas boleh MEMUNDURKAN jam timbang yang ia ketik sendiri.
    # Isian jam memang ada supaya pencatatan yang terlambat tetap jujur, tetapi
    # tanpa batas ia juga memindahkan tiket ke periode yang sudah ditutup —
    # timbang kedua bertanggal Maret untuk tiket September, di luar jendela
    # tujuh hari yang dibaca produksi. Lewat batas ini: hanya Admin, dan
    # tercatat di audit. Temuan QA T-16.
    jam_mundur_maksimum: int = _i("TIMBANGAN_JAM_MUNDUR_MAKS", 48)

    # ── Printer struk di pos timbang ──
    # Alamat printer Epson ber-ePOS-Print di jaringan lokal gudang. Yang
    # memakainya BUKAN server ini melainkan browser petugas: server berjalan
    # di Railway dan tidak punya jalan ke jaringan gudang. Nilai di sini hanya
    # bawaan yang dikirim ke layar, dan tiap perangkat boleh menimpanya.
    #
    # Harus https:// — halaman aplikasi disajikan lewat HTTPS, dan browser
    # menolak permintaan http:// dari halaman HTTPS (mixed content).
    printer_url: str = os.getenv("TIMBANGAN_PRINTER_URL", "https://192.168.1.128")
    # Nama perangkat di printer. Bawaan pabrik Epson untuk kepala cetaknya
    # sendiri; berubah hanya bila ada perangkat lain digantung di ePOS-Device.
    printer_devid: str = os.getenv("TIMBANGAN_PRINTER_DEVID", "local_printer")

    # ── Identitas pada bukti timbang ──
    perusahaan_nama: str = os.getenv("TIMBANGAN_PERUSAHAAN", "PT Hadi Mulya Utama")
    perusahaan_alamat: str = os.getenv("TIMBANGAN_ALAMAT", "Masaran, Kab. Sragen")
    perusahaan_telepon: str = os.getenv("TIMBANGAN_TELEPON", "+62 851-7416-7950")

    # ── Akun admin awal — dibuat otomatis bila tabel akun masih kosong ──
    admin_username: str = os.getenv("TIMBANGAN_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("TIMBANGAN_ADMIN_PASSWORD", "")
    admin_nama: str = os.getenv("TIMBANGAN_ADMIN_NAMA", "Administrator")


tsettings = TimbanganSettings()

# Kapasitas alat diterapkan ke lapisan logic agar SATU sumber kebenaran.
logic.KAPASITAS_JEMBATAN_KG = tsettings.kapasitas_jembatan_kg
logic.KELIPATAN_TERA_KG = tsettings.kelipatan_tera_kg
logic.KAPASITAS_TIMBANGAN_KECIL_KG = tsettings.kapasitas_timbangan_kecil_kg

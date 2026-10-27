"""Model DB modul Timbangan (prefiks tabel `timbangan_`).

LINGKUP: murni timbangan. **Tidak ada kolom harga atau nilai uang di mana pun** —
operator pos timbang tidak boleh mengetahui harga. Larangan itu ditegakkan oleh
ketiadaan kolom, bukan oleh penyembunyian di tampilan.

Prinsip pemodelan (RANCANGAN §9.1):

  a. Aturan hidup di data      → menambah komoditas = satu baris `timbangan_jenis`
  b. Salinan aturan di transaksi → revisi SOP tidak mengubah riwayat
  c. Muatan selalu berupa baris  → masuk satu baris, keluar beberapa
  d. Tidak ada kolom harga/potongan
  e. Tara standar tidak ditimpa  → sampling baru = baris baru
  f. Angka timbangan mentah      → pembulatan tera sudah dikerjakan alat
  g. Nomor transaksi dibentuk di perangkat → syarat kerja tanpa jaringan

TIDAK membuat master tandingan: identitas mitra tetap di `suppliers`
(disinkronkan dari Kledo lewat `suppliers.kledo_contact_id`), identitas orang
tetap di `users`.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin
from hmu_core import Armada, Brand, PackageSize, PackagingMaterial, RiceQualityStandard  # noqa: F401

# Nama lama tetap tersedia untuk semua pemanggil Timbangan.
TimbanganKendaraan = Armada


class TimbanganSopir(Base):
    """Satu ejaan utama per nama sopir; tiket menyimpan nama saat dicatat.

    Kunci unik menahan duplikat saat dua petugas memasukkan nama serentak.
    Tidak ada batas unik pada tiket: satu sopir tentu dapat datang berkali-kali.
    """
    __tablename__ = "timbangan_sopir"
    __table_args__ = (UniqueConstraint("kunci_nama", name="uq_timbangan_sopir_kunci_nama"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    kunci_nama: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)

class TimbanganSopirAlias(Base):
    """Ejaan yang sudah dikonfirmasi pemilik menunjuk satu sopir utama."""
    __tablename__ = "timbangan_sopir_alias"

    kunci_nama: Mapped[str] = mapped_column(String(200), primary_key=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    sopir_id: Mapped[int] = mapped_column(ForeignKey("timbangan_sopir.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


# Numeric tanpa Decimal → aritmetika float konsisten di seluruh lapisan.
KG = Numeric(14, 3, asdecimal=False)
KG_KECIL = Numeric(9, 4, asdecimal=False)
PCT = Numeric(9, 4, asdecimal=False)

# ── Peran login ───────────────────────────────────────────────────────────
# Tiga peran. "Pengawas" dihapus 30 Agustus 2026 karena tidak lagi punya
# kemampuan apa pun yang tidak dimiliki petugas — peran yang tidak berarti
# apa-apa lebih buruk daripada tidak ada, ia terlihat seperti pengaman
# padahal bukan.
#
# Super Admin bukan "Admin yang lebih tinggi": satu-satunya bedanya adalah
# wewenang MENGHAPUS data. Dipisahkan justru supaya pekerjaan sehari-hari
# tidak dilakukan sambil memegang tombol yang tidak bisa dibatalkan.
ROLE_PETUGAS = "PETUGAS"
ROLE_ADMIN = "ADMIN"
ROLE_SUPERADMIN = "SUPERADMIN"
ROLES = (ROLE_PETUGAS, ROLE_ADMIN, ROLE_SUPERADMIN)
ROLE_LABEL = {
    ROLE_PETUGAS: "Petugas Timbang",
    ROLE_ADMIN: "Admin",
    ROLE_SUPERADMIN: "Super Admin",
}

# ── Siklus hidup transaksi ────────────────────────────────────────────────
TIKET_TERBUKA = "TERBUKA"          # timbang pertama sudah, kedua belum
TIKET_SELESAI = "SELESAI"
TIKET_DITUTUP_PAKSA = "DITUTUP_PAKSA"

TRX_AKTIF = "AKTIF"
TRX_VOID = "VOID"                  # tidak pernah dihapus permanen

CARA_DUA_KALI = "DUA_KALI"
CARA_SEKALI = "SEKALI"             # jasa timbang, tanpa timbang kosong
#: Partai kecil: petani/pedagang membawa sedikit, ditimbang satu per satu —
#: tetapi tetap SATU siklus dan SATU kode timbang. Nettonya jumlah seluruh
#: penimbangan; tak ada timbang kosong, tak ada tara karung.
CARA_PARTAI = "PARTAI"
CARA_LABEL = {
    CARA_DUA_KALI: "Dua kali (bermuatan & kosong)",
    CARA_SEKALI: "Sekali (jasa timbang)",
    CARA_PARTAI: "Partai kecil (timbang satu per satu)",
}

# ── Pemeriksaan (SOP butir 6) ─────────────────────────────────────────────
PEMERIKSAAN_DIBUKA = "DIBUKA"
PEMERIKSAAN_SELESAI = "SELESAI"

STATUS_SUPPLIER = ("AKTIF", "PANTAU", "INVESTIGASI", "NONAKTIF")

JENIS_FOTO = {
    "ACUAN": "Foto nota / surat jalan",
    "TIMBANG_1": "Foto display timbang pertama",
    "TIMBANG_2": "Foto display timbang kedua",
    "MUATAN": "Foto muatan",
    "LAIN": "Foto lain",
}


# ══════════════════════════════════════════════════════════════════════════
# Master aturan
# ══════════════════════════════════════════════════════════════════════════

class TimbanganJenis(Base, TimestampMixin):
    """Aturan per komoditas — cerminan `logic.AturanJenis` di database.

    Menambah komoditas berarti menambah SATU baris di sini; tidak ada kode yang
    perlu diubah. Nilai baris ini disalin ke tiap transaksi saat disimpan, jadi
    merevisi aturan tidak pernah menggeser status transaksi lama.
    """

    __tablename__ = "timbangan_jenis"

    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(80), nullable=False)
    urutan: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # MASUK / KELUAR / BEBAS / TRANSFER / RETUR_MASUK / RETUR_KELUAR
    arah: Mapped[str] = mapped_column(String(16), nullable=False)
    # ACUAN_NOTA / ACUAN_SURAT_JALAN / ACUAN_TIDAK_ADA
    acuan: Mapped[str] = mapped_column(String(24), nullable=False)
    # TARA_TETAP / TARA_SAMPLING / TARA_MANUAL
    sumber_tara: Mapped[str] = mapped_column(String(20), nullable=False)
    tara_tetap_kg: Mapped[float] = mapped_column(KG_KECIL, nullable=False, default=0)
    tara_bawaan_kg: Mapped[float] = mapped_column(KG_KECIL, nullable=False, default=0)

    # AMBANG_PER_TON / AMBANG_PER_KARUNG / AMBANG_TETAP / AMBANG_TIDAK_ADA
    ambang_jenis: Mapped[str] = mapped_column(String(24), nullable=False)
    ambang_nilai: Mapped[float] = mapped_column(KG_KECIL, nullable=False, default=0)
    # ARAH_SIMETRIS / ARAH_KURANG_SAJA / ARAH_TIDAK_BOLEH_KURANG
    ambang_arah: Mapped[str] = mapped_column(String(28), nullable=False)
    ambang_investigasi_nilai: Mapped[float | None] = mapped_column(KG_KECIL)

    # Hasil kontrol rahasia (gabah & pengiriman) atau boleh dilihat
    # pengirim (beras PK).
    rahasia: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cetak_bukti: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    masa_berlaku_tara_hari: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90
    )

    #: Komoditas ini boleh masuk sebagai barang JASA? Lihat
    #: `logic.AturanJenis.boleh_jasa` — aturannya di DATA supaya komoditas
    #: berikutnya dibuka dengan centang, bukan dengan rilis.
    boleh_jasa: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="aktif")
    catatan: Mapped[str | None] = mapped_column(Text)


class TimbanganConfig(Base, TimestampMixin):
    """Setelan operasional yang boleh diubah Admin tanpa deploy ulang.

    Hanya memuat kunci yang terdaftar di `app.timbangan.setelan.DAFTAR`; kunci
    lain diabaikan. Baris yang tidak ada berarti "pakai nilai dari environment",
    jadi menghapus satu baris mengembalikan setelan ke bawaannya.

    Yang SENGAJA tidak boleh masuk sini: ambang kontrol, tara, dan aturan
    komoditas. Semua itu milik `timbangan_jenis`, karena merevisinya berarti
    merevisi cara perusahaan menilai kejujuran timbangan.
    """

    __tablename__ = "timbangan_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    kunci: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    nilai: Mapped[str] = mapped_column(String(120), nullable=False)
    diubah_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))


# ══════════════════════════════════════════════════════════════════════════
# Master pendukung
# ══════════════════════════════════════════════════════════════════════════

class TimbanganAkun(Base, TimestampMixin):
    """Akun pos timbang — dan, sejak identitas bersama, PROFIL pos timbang.

    Dua rupa hidup berdampingan di satu tabel (Tahap 2 rancang ulang, 13 Sep
    2026), supaya penyatuan akun bisa per orang dan bisa dibalik:

      · **Tertaut** (`akun_id` terisi): kredensial, peran, status, dan nama
        milik akun bersama (`produksi_akun` + `users`). Kolom `role`, `nama`,
        `status` di sini hanya CERMIN yang disinkronkan tiap kali masuk —
        dipertahankan karena kueri dan catatan lama membacanya.
        `password_hash` boleh kosong.
      · **Lama** (`akun_id` kosong): seperti sebelumnya — sandi dan peran
        sendiri. Masih bisa masuk, supaya tak ada hari tanpa sistem yang
        jalan; ditautkan lewat `scripts/identitas_tautkan.py`.

    Foreign key dari catatan timbang (`petugas_id`, `dibuat_oleh_id`, …)
    tetap menunjuk ke SINI, bukan ke akun bersama: riwayat tak ditulis ulang.
    """

    __tablename__ = "timbangan_akun"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_PETUGAS)
    #: Akun bersama (`produksi_akun.id`). Terisi = tertaut.
    akun_id: Mapped[int | None] = mapped_column(
        ForeignKey("produksi_akun.id"), unique=True
    )

    # ── Versi sesi ──
    #
    # Token sesi berlaku 180 hari dan tak tercatat di mana pun, jadi ia tak
    # bisa dicabut oleh apa pun: sesudah petugas mengganti sandinya lalu
    # menekan Keluar, cookie lama di perangkat lain tetap diterima. Angka ini
    # ikut di dalam token; menaikkannya menghentikan semua token lama
    # seketika. Temuan QA T-19.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    #: Kosong untuk profil tertaut — sandinya di akun bersama.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="aktif")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    # Kode perangkat yang dipegang orang ini — dipakai membentuk nomor
    # transaksi di perangkat (MSK-20260904-P1-007) agar tidak bentrok.
    perangkat_kode: Mapped[str | None] = mapped_column(String(8))
    terakhir_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    akun = relationship("Akun", lazy="joined")

    @property
    def tertaut(self) -> bool:
        return self.akun_id is not None

    @property
    def role_label(self) -> str:
        return ROLE_LABEL.get(self.role, self.role)

    @property
    def is_admin(self) -> bool:
        """Admin DAN Super Admin — semua wewenang Admin dimiliki keduanya."""
        return self.role in (ROLE_ADMIN, ROLE_SUPERADMIN)

    @property
    def is_super(self) -> bool:
        """Hanya Super Admin. Bedanya satu: boleh menghapus data."""
        return self.role == ROLE_SUPERADMIN

class TimbanganSupplierProfil(Base, TimestampMixin):
    """Atribut monitoring supplier (1:1 dengan `suppliers`).

    Sengaja terpisah dari `suppliers` agar sinkronisasi Kledo nanti bebas
    menimpa data identitas tanpa menyentuh catatan & status monitoring kita.
    """

    __tablename__ = "timbangan_supplier_profil"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), unique=True, nullable=False
    )
    wilayah: Mapped[str | None] = mapped_column(String(100))
    # AKTIF / PANTAU / INVESTIGASI / NONAKTIF
    status_monitoring: Mapped[str] = mapped_column(
        String(20), nullable=False, default="AKTIF"
    )
    catatan: Mapped[str | None] = mapped_column(Text)


class TimbanganTaraStandar(Base, TimestampMixin):
    """Hasil sampling tara karung per pihak × komoditas.

    Tidak pernah ditimpa: sampling ulang menulis baris baru dan menandai yang
    lama DIGANTI. Dengan begitu transaksi lama selalu bisa dijelaskan dengan
    angka tara yang benar-benar berlaku saat itu.
    """

    __tablename__ = "timbangan_tara_standar"
    __table_args__ = (
        Index(
            "ix_timbangan_tara_standar_berlaku",
            "supplier_id", "jenis_kode", "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    jenis_kode: Mapped[str] = mapped_column(String(30), nullable=False)

    jumlah_sampel: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_berat_kg: Mapped[float] = mapped_column(KG_KECIL, nullable=False, default=0)
    tara_per_karung_kg: Mapped[float] = mapped_column(KG_KECIL, nullable=False)
    jenis_karung: Mapped[str | None] = mapped_column(String(60))

    berlaku_mulai: Mapped[date] = mapped_column(Date, nullable=False)
    berlaku_sampai: Mapped[date | None] = mapped_column(Date)
    # BERLAKU / DIGANTI / KEDALUWARSA
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="BERLAKU")

    alasan: Mapped[str | None] = mapped_column(Text)
    dibuat_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    disetujui_oleh_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_akun.id")
    )
    disetujui_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ══════════════════════════════════════════════════════════════════════════
# Transaksi
# ══════════════════════════════════════════════════════════════════════════

class TimbanganTransaksi(Base, TimestampMixin):
    """Satu kedatangan armada = satu transaksi timbang.

    Angka timbangan disimpan APA ADANYA. Kolom hasil adalah SNAPSHOT hitungan
    saat disimpan, dan `aturan_snapshot` menyimpan aturan yang dipakai — supaya
    laporan lama tidak berubah bila ambang direvisi kemudian.

    Dua kali timbang bisa dilakukan orang yang berbeda; keduanya dicatat.
    Petugas timbang yang tertera pada bukti adalah petugas timbang KEDUA.
    """

    __tablename__ = "timbangan_transaksi"
    __table_args__ = (
        Index("ix_timbangan_transaksi_tanggal_supplier", "tanggal", "supplier_id"),
        Index("ix_timbangan_transaksi_tiket", "status_tiket", "tanggal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Dibentuk di perangkat: <awalan>-YYYYMMDD-<perangkat>-<urutan>, dengan
    # awalan menurut arah barang — lihat `service.AWALAN_KODE`. Tiket yang
    # dibuat sebelum 4 September 2026 berawalan TRX- dan dibiarkan apa adanya.
    kode: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False
    )
    # ── Kunci kiriman: identitas yang SEBENARNYA dari sebuah penimbangan ──
    #
    # Dibuat perangkat saat formulir dibuka, sekali, dan tak pernah berubah
    # sesudahnya. Nomor tiket TIDAK bisa dipakai untuk ini: sampai 11
    # September 2026 nomor itu juga dibentuk saat formulir dibuka, dari
    # "jumlah baris hari ini + 1", sehingga dua petugas yang membuka layar
    # pada detik yang sama memegang angka yang sama — lalu penyimpanannya
    # memperlakukan nomor yang sudah ada sebagai kirim ulang dan menulis ulang
    # seluruh tiket. Truk yang pertama hilang tanpa satu pun pesan.
    #
    # Dengan kunci ini, kirim ulang dari antrean luring tetap dikenali
    # (kunci sama = kiriman yang sama), sementara dua penimbangan yang
    # berbeda tak mungkin bertabrakan — masing-masing membawa kuncinya
    # sendiri.
    #
    # Boleh kosong: tiket yang dibuat sebelum kolom ini ada tak punya kunci,
    # dan tak boleh diisi asal karena kunci karangan bisa bertabrakan dengan
    # kunci sungguhan milik perangkat.
    kunci_kiriman: Mapped[str | None] = mapped_column(
        String(36), unique=True, index=True
    )
    # Mengikuti tanggal timbang KEDUA (transaksi bisa melewati tengah malam).
    tanggal: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # MASUK / KELUAR / BEBAS / TRANSFER / RETUR_MASUK / RETUR_KELUAR
    arah: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    jenis_kode: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    cara_timbang: Mapped[str] = mapped_column(
        String(12), nullable=False, default=CARA_DUA_KALI
    )
    # Salinan aturan yang dipakai (JSON) — butir b.
    aturan_snapshot: Mapped[str | None] = mapped_column(Text)
    # Cuplikan muatan aktual PadiFlow saat selesai: kiriman, perintah,
    # pelanggan dan ID item. Bukan salinan harga atau hasil timbang per pihak.
    # NULL menjaga tiket lama apa adanya, tanpa mengarang alokasi pelanggan.
    pengiriman_snapshot: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    # ID master dan nama saat dipilih; bukan relasi ke transaksi/stok PadiFlow.
    lintasan_transfer: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))

    #: ⚠⚠ TIKET INI MEMBAWA BARANG TITIPAN, bukan barang yang dibeli — dan ini
    #: SATU-SATUNYA tempat faktanya hidup. Migrasi 0041 (2 Oktober 2026),
    #: sesudah cacat lapangan: sampai migrasi itu, "ini jasa?" DITURUNKAN dari
    #: `pelanggan_id IS NOT NULL` (lihat `timbang_link.adalah_jasa` di repo
    #: produksi) — dan itu SALAH untuk pelanggan BARU yang diketik bebas di
    #: pintu ketik-bebas (cermin Kledo disegarkan mingguan, jadi pelanggan
    #: baru memang bisa belum ada): `_pasang_pihak(..., pihak_id=None,
    #: jasa=True)` mengosongkan KEDUA kolom FK di bawah, dan baris tiket
    #: "jasa-pelanggan-baru" jadi IDENTIK bentuknya dengan
    #: "pembelian-pemasok-baru". Produksi lalu membuat PEMASOK PALSU dari nama
    #: pelanggan — persis yang dilarang keras spek.
    #:
    #: Kolom ini DIISI SEKALI, saat petugas menekan "Barang masuk jasa" —
    #: fakta yang ia tahu pasti pada detik itu, lepas dari apakah
    #: pelanggannya sudah terdaftar. `supplier_id`/`pelanggan_id` TETAP ada
    #: di bawah (turunan — mana pelanggannya, kalau sudah diketahui), tetapi
    #: bukan lagi penentu "jasa atau bukan".
    jasa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                       server_default=text("false"))
    #: Lawan transaksi pada arah MASUK.
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    #: Lawan transaksi pada arah KELUAR. Dua kolom, bukan satu, karena
    #: keduanya menunjuk tabel yang berbeda — dan satu kontak Kledo boleh
    #: berperan sebagai vendor sekaligus pelanggan. Yang menentukan adalah
    #: arah transaksi ini, bukan sifat orangnya.
    pelanggan_id: Mapped[int | None] = mapped_column(ForeignKey("pelanggan.id"))
    #: Pesanan JASA (toll milling) yang tiket MASUK ini masuki — NULL untuk
    #: barang yang dibeli, yaitu hampir semuanya.
    #:
    #: ⚠ Penunjuk ke pesanan yang SUDAH berjalan, bukan tempat melahirkannya.
    #: Pak Budi yang menjasakan 24 ton dengan truk 12 ton datang DUA KALI;
    #: tiket kedua menunjuk pesanan yang sama, dan karena itu satu pekerjaan
    #: tetap satu nota dan satu rendemen. Baris `jasa`-nya sendiri dibuat
    #: PRODUKSI saat operator menerima tiketnya — tiket di sini bisa
    #: dibatalkan atau direvisi, dan tiket batal yang sudah melahirkan pesanan
    #: akan meninggalkan pesanan yatim di sana.
    #:
    #: ⚠ TANPA ForeignKey DI TINGKAT ORM, dan itu disengaja. Tabel `jasa`
    #: dimiliki repo penggilingan (migrasi 0064 di sana), tidak ada di metadata
    #: modul ini — dan uji modul ini membangun skemanya dari metadata, jadi FK
    #: ke tabel yang tak ada di situ akan menggagalkan `create_all` di seluruh
    #: suite. FK-nya berdiri di tingkat BASIS DATA, dipasang migrasi 0064
    #: produksi. Pola dan alasan yang sama sudah dipakai arah sebaliknya:
    #: `purchase_batches.timbangan_transaksi_id` di sana pun kolom Integer
    #: biasa di ORM.
    jasa_id: Mapped[int | None] = mapped_column(Integer)
    # Untuk jasa timbang: pihak tidak selalu terdaftar sebagai supplier.
    pihak_nama: Mapped[str | None] = mapped_column(String(120))
    kendaraan_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_kendaraan.id")
    )
    nomor_polisi: Mapped[str | None] = mapped_column(String(20), index=True)
    nama_sopir: Mapped[str | None] = mapped_column(String(100))

    # ── Timbang pertama ──
    timbang1_kg: Mapped[float] = mapped_column(KG, nullable=False)
    timbang1_waktu: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timbang1_waktu_sistem: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    timbang1_petugas_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_akun.id")
    )

    # ── Timbang kedua (kosong pada tiket yang masih terbuka) ──
    timbang2_kg: Mapped[float | None] = mapped_column(KG)
    timbang2_waktu: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timbang2_waktu_sistem: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    timbang2_petugas_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_akun.id")
    )

    # Diturunkan dari kedua angka di atas menurut arah, disimpan eksplisit
    # supaya laporan tidak perlu menebak mana yang bermuatan.
    berat_bermuatan_kg: Mapped[float | None] = mapped_column(KG)
    berat_kosong_kg: Mapped[float | None] = mapped_column(KG)
    tara_lain_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)

    # ── Snapshot hasil hitung ──
    netto_timbangan_kg: Mapped[float | None] = mapped_column(KG)
    jumlah_karung: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tara_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)
    berat_barang_kg: Mapped[float | None] = mapped_column(KG)
    berat_acuan_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)
    selisih_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)
    selisih_persen: Mapped[float] = mapped_column(PCT, nullable=False, default=0)
    batas_bawah_kg: Mapped[float | None] = mapped_column(KG)
    batas_atas_kg: Mapped[float | None] = mapped_column(KG)
    # NORMAL / PERLU_PEMERIKSAAN / INVESTIGASI / KURANG / KELEBIHAN / TANPA_KONTROL
    status_kontrol: Mapped[str | None] = mapped_column(String(24), index=True)
    keterangan: Mapped[str | None] = mapped_column(Text)

    # ── Siklus hidup ──
    status_tiket: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TIKET_TERBUKA, index=True
    )
    status_transaksi: Mapped[str] = mapped_column(
        String(10), nullable=False, default=TRX_AKTIF, index=True
    )
    tutup_paksa_alasan: Mapped[str | None] = mapped_column(Text)
    terkunci: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dikunci_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jumlah_revisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    void_alasan: Mapped[str | None] = mapped_column(Text)
    void_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    void_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catatan: Mapped[str | None] = mapped_column(Text)

    # ── Jejak perangkat & sinkronisasi ──
    perangkat_kode: Mapped[str | None] = mapped_column(String(8))
    dibuat_offline: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    dikirim_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dibuat_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    diubah_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))

    # ── Jembatan integrasi ke modul produksi (kosong sampai diaktifkan) ──
    # Gabah menaut memakai BERAT NOTA; PK memakai BERAT PK BERSIH.
    purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_batches.id")
    )
    pk_purchase_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("pk_purchase_batches.id")
    )

    kendaraan: Mapped["TimbanganKendaraan | None"] = relationship(lazy="selectin")
    muatan: Mapped[list["TimbanganMuatan"]] = relationship(
        back_populates="transaksi", lazy="selectin",
        cascade="all, delete-orphan", order_by="TimbanganMuatan.urutan",
    )
    foto: Mapped[list["TimbanganFoto"]] = relationship(
        back_populates="transaksi", lazy="selectin", cascade="all, delete-orphan"
    )
    penimbangan: Mapped[list["TimbanganPenimbangan"]] = relationship(
        back_populates="transaksi", lazy="selectin",
        cascade="all, delete-orphan", order_by="TimbanganPenimbangan.urutan",
    )

    @property
    def aktif(self) -> bool:
        return self.status_transaksi == TRX_AKTIF

    @property
    def selesai(self) -> bool:
        return self.status_tiket in (TIKET_SELESAI, TIKET_DITUTUP_PAKSA)

    @property
    def partai(self) -> bool:
        """Transaksi partai kecil — nettonya jumlah beberapa penimbangan."""
        return self.cara_timbang == CARA_PARTAI

    @property
    def total_penimbangan_kg(self) -> float:
        return sum(float(p.berat_kg or 0) for p in self.penimbangan)

    # `petugas_bukti_id` DIBUANG 30 September 2026. Ia menjawab "siapa yang
    # tertera di bukti timbang" dengan "pelaku timbang terakhir", dan pemilik
    # memutuskan jawabannya bukan itu: yang tertera adalah akun yang MENCETAK
    # (blok itu ruang tanda tangan, dan yang menandatangani adalah yang
    # menyerahkan kertasnya). Dibuang, bukan dibiarkan menganggur — properti
    # yang namanya menjanjikan satu aturan yang sudah tidak berlaku akan
    # dipakai lagi oleh pembaca berikutnya yang percaya namanya.

class TimbanganMuatan(Base):
    """Baris muatan: satu untuk barang masuk, beberapa untuk pengiriman.

    Satu bentuk data untuk kedua arah — bukan dua skema berbeda.
    """

    __tablename__ = "timbangan_muatan"
    __table_args__ = (
        # Kedua tabel ini SELALU ditanya "semua baris milik tiket nomor
        # sekian", dan tak satu pun punya indeks untuk itu. Temuan QA T-22.
        Index("ix_timbangan_muatan_transaksi", "transaksi_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id", ondelete="CASCADE"), nullable=False
    )
    urutan: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    jenis_kode: Mapped[str] = mapped_column(String(30), nullable=False)

    # Detail produk/kemasan memakai master bersama yang sama dengan Stok
    # Produk. NULL mempertahankan arti tiket lama dan barang curah.
    kualitas_id: Mapped[int | None] = mapped_column(
        ForeignKey("rice_quality_standards.id")
    )
    merek_produk_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    packaging_material_id: Mapped[int | None] = mapped_column(
        ForeignKey("packaging_materials.id")
    )
    package_size_id: Mapped[int | None] = mapped_column(
        ForeignKey("package_sizes.id")
    )

    # Nomor nota boleh kosong — supplier sering memakai nota tulis tangan.
    nomor_acuan: Mapped[str | None] = mapped_column(String(50), index=True)
    jumlah_karung: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tara_per_karung_kg: Mapped[float] = mapped_column(
        KG_KECIL, nullable=False, default=0
    )
    berat_acuan_kg: Mapped[float] = mapped_column(KG, nullable=False, default=0)
    # Baris tara standar yang dipakai, bila ada — agar bisa ditelusuri.
    tara_standar_id: Mapped[int | None] = mapped_column(
        ForeignKey("timbangan_tara_standar.id")
    )
    catatan: Mapped[str | None] = mapped_column(Text)

    transaksi: Mapped[TimbanganTransaksi] = relationship(back_populates="muatan")

    @property
    def tara_kg(self) -> float:
        return self.jumlah_karung * self.tara_per_karung_kg


class TimbanganPenimbangan(Base):
    """Satu kali naik timbangan pada transaksi PARTAI KECIL.

    Ada karena petani dan pedagang kecil menjual sedikit-sedikit: barangnya
    ditimbang satu per satu, tetapi seluruhnya tetap satu siklus dan satu kode
    timbang — satu nota, satu pihak, satu jenis.

    Angkanya NETTO apa adanya, tanpa tara dan tanpa pembulatan: bila alat
    membaca 2 kg, yang tersimpan 2 kg. Kelipatan 10 kg yang berlaku di jembatan
    truk tidak berlaku di sini karena alatnya memang berbeda.

    `TimbanganTransaksi.timbang1_kg` menyimpan JUMLAH seluruh baris ini, supaya
    seluruh laporan, bukti cetak, dan jembatan ke modul produksi tetap membaca
    satu angka seperti transaksi lain — tidak ada yang perlu tahu bentuk khusus
    ini kecuali layar yang mencatatnya.
    """

    __tablename__ = "timbangan_penimbangan"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    urutan: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    berat_kg: Mapped[float] = mapped_column(KG, nullable=False)
    waktu: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waktu_sistem: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    petugas_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    catatan: Mapped[str | None] = mapped_column(String(120))

    # ── Penanda kiriman, supaya karung yang sama tak tercatat dua kali ──
    #
    # Penambahan partai dulu tak punya penanda apa pun, jadi kiriman ULANG —
    # ketukan dobel, atau antrean luring yang mengirim lagi saat sinyal
    # kembali — tak bisa dibedakan dari karung berikutnya yang kebetulan sama
    # beratnya. "+70 kg" jadi 250 kg, bukan 180. Temuan QA T-10.
    #
    # Boleh kosong: baris yang dibuat sebelum kolom ini ada memang tak punya.
    #
    # 64, bukan 36 (R-T-01, insiden 15 September 2026): kuncinya uuid4 dari
    # borang (36) DITAMBAH '#' dan indeks baris dalam kiriman. Dengan 36,
    # Postgres menolak tiap simpan partai — dan SQLite di suite uji tak
    # pernah menolaknya, karena SQLite tak menegakkan panjang VARCHAR.
    # Jangan menyelesaikannya dengan memotong kuncinya: kunci yang dipotong
    # berhenti unik antar baris satu kiriman, dan T-10 hidup lagi.
    kunci_baris: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    transaksi: Mapped["TimbanganTransaksi"] = relationship(back_populates="penimbangan")


class TimbanganPemeriksaan(Base, TimestampMixin):
    """Lembar pemeriksaan SOP butir 6 — enam langkah, dicatat per langkah.

    Transaksi yang perlu diperiksa boleh diselesaikan dengan catatan resolusi;
    yang penting jejaknya ada, bukan bahwa semuanya berakhir bersih.
    """

    __tablename__ = "timbangan_pemeriksaan"
    __table_args__ = (
        # Dinamai apa adanya seperti di basis data.
        Index("ix_timbangan_pemeriksaan_transaksi", "transaksi_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id"), nullable=False
    )

    langkah_ulang_timbang: Mapped[str | None] = mapped_column(Text)
    langkah_hitung_karung: Mapped[str | None] = mapped_column(Text)
    langkah_periksa_tara: Mapped[str | None] = mapped_column(Text)
    langkah_periksa_dokumen: Mapped[str | None] = mapped_column(Text)
    langkah_periksa_muatan: Mapped[str | None] = mapped_column(Text)
    langkah_lapor: Mapped[str | None] = mapped_column(Text)

    dilaporkan_ke: Mapped[str | None] = mapped_column(String(120))
    dilaporkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # SELISIH_WAJAR / SALAH_CATAT / SUSUT_PERJALANAN / TARA_TIDAK_SESUAI /
    # DOKUMEN_TIDAK_SESUAI / PERLU_TINDAK_LANJUT / LAIN
    kategori_hasil: Mapped[str | None] = mapped_column(String(30), index=True)
    catatan_resolusi: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PEMERIKSAAN_DIBUKA, index=True
    )
    dibuka_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    ditutup_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    ditutup_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TimbanganCetak(Base):
    """Riwayat cetak bukti timbang. Cetak ulang wajib beralasan."""

    __tablename__ = "timbangan_cetak"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id"), nullable=False
    )
    urutan: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 80MM / NCR — supaya bila kelak ada sengketa, tercatat lembar bentuk apa
    # yang benar-benar diterima pengirim.
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="80MM")
    ulang: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Nomor revisi tiket SAAT kertas ini keluar. Cetak ulang sesudah koreksi
    #: memuat angka yang berbeda dari cetakan sebelumnya; tanpa kolom ini,
    #: dua lembar untuk satu truk tak bisa dibedakan lagi di kemudian hari.
    revisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alasan: Mapped[str | None] = mapped_column(Text)
    oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    waktu: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Dinamai apa adanya seperti di basis data.
        Index("ix_timbangan_cetak_transaksi", "transaksi_id"),
        UniqueConstraint("transaksi_id", "urutan", name="uq_timbangan_cetak_urutan"),
    )


class TimbanganFoto(Base):
    """Foto bukti. Disimpan sebagai BLOB di Postgres — filesystem Railway
    bersifat sementara, bukti tidak boleh hilang saat deploy ulang."""

    __tablename__ = "timbangan_foto"
    __table_args__ = (
        # Kedua tabel ini SELALU ditanya "semua baris milik tiket nomor
        # sekian", dan tak satu pun punya indeks untuk itu. Temuan QA T-22.
        Index("ix_timbangan_foto_transaksi", "transaksi_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(
        ForeignKey("timbangan_transaksi.id", ondelete="CASCADE"), nullable=False
    )
    # ACUAN / TIMBANG_1 / TIMBANG_2 / MUATAN / LAIN
    jenis: Mapped[str] = mapped_column(String(20), nullable=False, default="LAIN")
    nama_file: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False, default="image/jpeg")
    ukuran_byte: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # ── Isi fotonya TIDAK ikut termuat kecuali diminta ──
    #
    # `TimbanganTransaksi.foto` bersifat `selectin`, jadi setiap daftar tiket
    # menarik SELURUH BLOB fotonya — berpuluh megabyte untuk halaman yang
    # cuma menampilkan nomor polisi dan berat. `deferred` membuat kolom ini
    # baru dibaca saat benar-benar disentuh, yaitu ketika seseorang membuka
    # fotonya. Temuan QA T-22.
    konten: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    diunggah_oleh_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    transaksi: Mapped[TimbanganTransaksi] = relationship(back_populates="foto")


# ══════════════════════════════════════════════════════════════════════════
# Monitoring & audit
# ══════════════════════════════════════════════════════════════════════════

class TimbanganSkorSupplier(Base):
    """Cache skor monitoring pihak (dihitung ulang berkala/on-demand)."""

    __tablename__ = "timbangan_skor_supplier"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False
    )
    # 'TERKINI' atau 'YYYY-MM'
    periode: Mapped[str] = mapped_column(String(10), nullable=False, default="TERKINI")
    skor_total: Mapped[float] = mapped_column(PCT, nullable=False, default=0)
    kategori: Mapped[str] = mapped_column(String(2), nullable=False, default="C")
    jumlah_transaksi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    komponen_json: Mapped[str | None] = mapped_column(Text)
    pola_json: Mapped[str | None] = mapped_column(Text)
    dihitung_pada: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Dinamai apa adanya seperti di basis data.
        Index("ix_timbangan_skor_supplier_supplier", "supplier_id"),
        UniqueConstraint(
            "supplier_id", "periode", name="uq_timbangan_skor_supplier_periode"
        ),
    )


class TimbanganAudit(Base):
    """Jejak audit modul: siapa, kapan, aksi apa, nilai sebelum & sesudah.

    Hanya bertambah. Koreksi menulis baris baru, tidak pernah menimpa.
    """

    __tablename__ = "timbangan_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    waktu: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    akun_id: Mapped[int | None] = mapped_column(ForeignKey("timbangan_akun.id"))
    akun_nama: Mapped[str | None] = mapped_column(String(100))
    # LOGIN / LOGOUT / SIMPAN_TIMBANG_1 / SIMPAN_TIMBANG_2 / KOREKSI /
    # VOID / TUTUP_PAKSA / CETAK / PEMERIKSAAN / TARA_STANDAR / ...
    aksi: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entitas: Mapped[str | None] = mapped_column(String(40))
    entitas_id: Mapped[str | None] = mapped_column(String(40))
    ringkasan: Mapped[str | None] = mapped_column(Text)
    nilai_sebelum: Mapped[str | None] = mapped_column(Text)
    nilai_sesudah: Mapped[str | None] = mapped_column(Text)
    perangkat_kode: Mapped[str | None] = mapped_column(String(8))
    ip: Mapped[str | None] = mapped_column(String(45))


class TimbanganNomor(Base):
    """Penghitung nomor tiket — satu baris per awalan, tanggal, dan perangkat.

    Nomor dulu dihitung dengan `SELECT count(*) … + 1` saat formulir dibuka.
    Dua hal salah sekaligus di situ: ia dihitung terlalu awal (nomor yang
    belum jadi milik siapa pun), dan ia dihitung dari jumlah BARIS — sehingga
    tiket yang dibatalkan membuat nomor tertinggi diterbitkan ulang.

    Baris di sini hanya bertambah, tak pernah berkurang. Nomor yang sudah
    diterbitkan tak akan diterbitkan lagi meski tiketnya kemudian dibatalkan:
    nomor yang muncul dua kali di buku dan di struk lebih membingungkan
    daripada nomor yang melompat.

    Diambil dengan satu perintah `INSERT … ON CONFLICT DO UPDATE … RETURNING`,
    jadi dua penyimpanan yang berbarengan tak mungkin mendapat angka yang
    sama — bahkan bila keduanya datang dari dua proses yang berbeda.
    """

    __tablename__ = "timbangan_nomor"

    awalan: Mapped[str] = mapped_column(String(8), primary_key=True)
    tanggal: Mapped[date] = mapped_column(Date, primary_key=True)
    perangkat: Mapped[str] = mapped_column(String(8), primary_key=True)
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TimbanganKiriman(Base):
    """Tanda terima kiriman formulir; ditulis satu transaksi dengan timbangnya.

    Tidak menyimpan salinan isian. Sidik isi mencegah satu kunci dipakai
    untuk dua pekerjaan; jawaban tetap dapat dibaca ulang sesudah balasan
    HTTP hilang, tanpa mengulang audit, bobot, atau integrasi.
    """
    __tablename__ = "timbangan_kiriman"
    kunci: Mapped[str] = mapped_column(String(36), primary_key=True)
    akun_id: Mapped[int] = mapped_column(ForeignKey("timbangan_akun.id"), nullable=False)
    jalur: Mapped[str] = mapped_column(String(255), nullable=False)
    sidik: Mapped[str] = mapped_column(String(64), nullable=False)
    jawaban: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TimbanganPekerjaanCetak(Base):
    """Konteks pengiriman tetap; bukan catatan bahwa kertas sudah keluar."""
    __tablename__ = 'timbangan_pekerjaan_cetak'
    kunci: Mapped[str] = mapped_column(String(64), primary_key=True)
    transaksi_id: Mapped[int] = mapped_column(ForeignKey('timbangan_transaksi.id'), index=True)
    oleh_id: Mapped[int] = mapped_column(ForeignKey('timbangan_akun.id'))
    nama_pencetak: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(10))
    keluaran: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default='siap')
    sidik: Mapped[str] = mapped_column(String(64))
    versi_tiket: Mapped[str] = mapped_column(String(100))
    revisi: Mapped[int] = mapped_column(Integer)
    urutan: Mapped[int] = mapped_column(Integer)
    alasan: Mapped[str | None] = mapped_column(Text)
    konten: Mapped[bytes] = mapped_column(LargeBinary)
    metode: Mapped[str | None] = mapped_column(String(30))
    cetak_id: Mapped[int | None] = mapped_column(ForeignKey('timbangan_cetak.id'))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""Barang masuk JASA: pemiliknya PELANGGAN, walaupun arahnya MASUK.

Satu kalimat yang menjelaskan seluruh berkas ini: jasa bukan arah baru dan
bukan jenis baru — cara menimbang, tara, dan ambangnya sama persis dengan gabah
yang dibeli; yang beda cuma pemiliknya.

Dari situ lahir satu-satunya hal yang bisa rusak diam-diam di sini: pemetaan
arah → kolom pihak. Tiket MASUK biasanya mengisi `supplier_id`; tiket jasa
harus mengisi `pelanggan_id`. Satu cabang yang terlewat akan menulis PEMILIK
BARANG ke kolom pemasok — dan tak ada yang akan melihatnya sampai laporan
pembelian memuat nama pelanggan sebagai pemasok, berbulan-bulan kemudian.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Pelanggan
from app.timbangan import logic, service
from app.timbangan.models import CARA_DUA_KALI, TimbanganJenis, TimbanganTransaksi
from app.timbangan.service import InputMuatan, InputTimbang

pytestmark = pytest.mark.usefixtures("jenis_tersemai")


@pytest.fixture
async def pelanggan(db):
    p = Pelanggan(nama_pelanggan="Pak Budi")
    db.add(p)
    await db.flush()
    return p


def tiket_jasa(*, pelanggan_id: int | None, berat: float = 12_000.0,
               jasa_id: int | None = None, jenis: str = "GABAH_KERING",
               pihak_nama: str | None = None) -> InputTimbang:
    return InputTimbang(
        arah=logic.MASUK,
        jenis_kode=jenis,
        berat_kg=berat,
        cara_timbang=CARA_DUA_KALI,
        jasa=True,
        pelanggan_id=pelanggan_id,
        jasa_id=jasa_id,
        pihak_nama=pihak_nama,
        nomor_polisi="AD 1234 XY",
        nama_sopir="Sopir Uji",
        muatan=[InputMuatan(jenis_kode=jenis)],
    )


# ════════════════ 1 · PEMILIKNYA PELANGGAN, BUKAN PEMASOK ════════════════

async def test_tiket_jasa_mengisi_pelanggan_bukan_supplier(db, petugas, pelanggan):
    """Inti seluruh pekerjaan ini, dan satu-satunya yang rusak tanpa bersuara."""
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=tiket_jasa(pelanggan_id=pelanggan.id))
    assert trx.pelanggan_id == pelanggan.id
    assert trx.supplier_id is None, "pemilik barang tertulis sebagai pemasok"
    assert trx.arah == logic.MASUK, "jasa bukan arah baru"
    assert trx.jenis_kode == "GABAH_KERING", "jasa bukan jenis baru"
    assert trx.jasa is True


async def test_tiket_biasa_tetap_mengisi_supplier(db, petugas, supplier):
    """Perilaku lama tidak bergeser — penjaga baru tak boleh menyentuhnya.

    Diuji bersebelahan dengan yang di atas, sengaja: keduanya menempuh fungsi
    yang SAMA, dan yang membedakan hanya satu bendera. Uji yang hanya memeriksa
    cabang baru akan lulus pada hari cabang itu mengambil alih keduanya.
    """
    data = tiket_jasa(pelanggan_id=None)
    data.jasa = False
    data.supplier_id = supplier.id
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert trx.supplier_id == supplier.id
    assert trx.pelanggan_id is None
    assert trx.jasa_id is None
    assert trx.jasa is False


async def test_pemilik_boleh_diketik_bebas(db, petugas):
    """Cermin pelanggan disegarkan dari Kledo MINGGUAN.

    Pelanggan yang baru dibuat hari ini memang bisa belum ada di daftar — dan
    tanpa pintu ketik-bebas, truknya tak bisa ditimbang sampai sinkronisasi
    berikutnya. Itu bukan kelonggaran; itu syarat supaya pos tetap bisa bekerja.

    ⚠⚠ DAN `trx.jasa` WAJIB TETAP TRUE DI SINI — cacat lapangan 2 Oktober 2026.
    Uji ini sudah ADA sebelum cacatnya ditemukan dan sudah membuktikan
    `(supplier_id, pelanggan_id) == (None, None)` sebagai perilaku yang BENAR
    untuk pintu ketik-bebas. Yang luput: DUA kolom NULL itu berarti baris
    tiketnya, dilihat dari repo `produksi` (basis data yang sama), IDENTIK
    bentuknya dengan pembelian biasa yang pemasoknya diketik bebas. Sampai
    migrasi 0041 menambah kolom `jasa`, produksi membaca `pelanggan_id IS NOT
    NULL` sebagai satu-satunya penanda — dan pelanggan baru ketik-bebas gagal
    terdeteksi, lalu dicatat sebagai PEMASOK PALSU bernama pelanggan itu
    sendiri. Pelajarannya: menguji bahwa sebuah pintu BEKERJA tidak sama
    dengan menguji bahwa jejak yang ditinggalkannya BISA DIBACA BENAR oleh
    pembaca lain.
    """
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=tiket_jasa(pelanggan_id=None, pihak_nama="Bu Sri (baru)"))
    assert trx.pihak_nama == "Bu Sri (baru)"
    assert (trx.supplier_id, trx.pelanggan_id) == (None, None)
    assert trx.jasa is True, (
        "pelanggan baru ketik-bebas kehilangan penanda jasa — produksi akan "
        "membacanya sebagai pembelian biasa dan membuat pemasok palsu")


async def test_pemilik_wajib_ada(db, petugas):
    """Tanpa pemilik, barang titipan tak bisa dikembalikan kepada siapa pun."""
    with pytest.raises(service.LayananError) as e:
        await service.simpan_timbang_pertama(
            db, akun=petugas, data=tiket_jasa(pelanggan_id=None))
    # Sebutannya "Pemilik barang", bukan "Pemasok": petugas yang dikirim
    # mencari nama di daftar yang salah akan mengetikkan nama bebas, dan
    # tiketnya kehilangan tautan ke master pelanggan.
    assert "Pemilik barang" in e.value.args[0], e.value.args[0]


# ════════════════ 2 · ATURANNYA DI DATA, BUKAN DI KODE ════════════════

async def test_hanya_komoditas_yang_dibuka_boleh_dijasakan(db, petugas, pelanggan):
    """Komoditas yang TIDAK dibuka ditolak — dan penolakannya menyebut yang bisa.

    ⚠ Uji ini semula memakai BERAS_PK sebagai contoh "belum dibuka", dan itu
    sudah TIDAK BENAR: pemilik membuka ketiga komoditasnya (gabah basah, gabah
    kering, beras PK) pada 1 Oktober 2026, sesudah kedua jalur yang
    menghalanginya dibangun di produksi. Yang berubah ATURANNYA, bukan ujinya
    yang perlu dilonggarkan — jadi contohnya diganti komoditas yang memang
    masih tertutup, dan mekanismenya tetap dijaga sekeras semula.

    `BROKEN_MASUK` dipakai karena jasa sosoh broken & menir adalah MILESTONE
    TERSENDIRI: rumus rendemen penyosohan berpenyebut PK, dan satu proses sosoh
    broken yang lolos membuat sebaran rendemen tak bisa dipakai menilai apa pun
    lagi — untuk SEMUA proses.
    """
    with pytest.raises(service.LayananError) as e:
        await service.simpan_timbang_pertama(
            db, akun=petugas,
            data=tiket_jasa(pelanggan_id=pelanggan.id, jenis="BROKEN_MASUK"))
    pesan = e.value.args[0]
    assert "belum dibuka untuk jasa" in pesan, pesan
    # Menyebut APA yang bisa, bukan cuma apa yang tidak bisa.
    assert "Gabah Kering" in pesan, pesan


@pytest.mark.parametrize("jenis", ["GABAH_BASAH", "GABAH_KERING", "BERAS_PK"])
async def test_ketiga_komoditas_dibuka_untuk_jasa(db, petugas, pelanggan, jenis):
    """⭐ KEPUTUSAN PEMILIK NOMOR 1: *"Jasa dari gabah basah, gabah kering, dan
    beras PK."* Ketiganya, bukan salah satu.

    Diuji satu per satu lewat jalur simpan yang sungguhan — bukan dengan membaca
    `JENIS_AWAL`. Daftar bibit bisa benar sementara penjaganya menolak, dan yang
    menanggung selisihnya petugas di pos dengan truk yang sudah di jembatan.
    """
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=tiket_jasa(pelanggan_id=pelanggan.id, jenis=jenis))
    assert trx.pelanggan_id == pelanggan.id
    assert trx.supplier_id is None
    assert trx.jenis_kode == jenis


async def test_membuka_komoditas_lain_cukup_lewat_master(db, petugas, pelanggan):
    """⭐ Centang kolomnya, dan jalurnya terbuka — tanpa rilis.

    Inilah sebabnya `boleh_jasa` sebuah KOLOM dan bukan `if` di kode. Uji ini
    yang menahannya tetap begitu: begitu seseorang memindahkan aturannya ke
    kode, uji ini gagal.
    """
    baris = (await db.execute(select(TimbanganJenis).where(
        TimbanganJenis.kode == "BROKEN_MASUK"))).scalars().one()
    baris.boleh_jasa = True
    await db.flush()

    trx = await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=tiket_jasa(pelanggan_id=pelanggan.id, jenis="BROKEN_MASUK"))
    assert trx.pelanggan_id == pelanggan.id


async def test_daftar_komoditas_jasa_dibaca_dari_master(db, jenis_tersemai):
    """Beranda menggambar kartunya dari master — bukan dari daftar di kode."""
    daftar = await service.daftar_jenis_jasa(db)
    # Ketiganya, terurut mengikuti `urutan` di master — bukan urutan abjad.
    assert [j.kode for j in daftar] == ["GABAH_BASAH", "GABAH_KERING", "BERAS_PK"]

    # Dicabut di master → kartunya hilang sendiri dari beranda.
    for kode in ("GABAH_BASAH", "GABAH_KERING", "BERAS_PK"):
        baris = (await db.execute(select(TimbanganJenis).where(
            TimbanganJenis.kode == kode))).scalars().one()
        baris.boleh_jasa = False
    await db.flush()
    assert await service.daftar_jenis_jasa(db) == []


# ════════════════ 3 · SATU PESANAN, BEBERAPA TRUK ════════════════

async def test_penunjuk_pesanan_hanya_hidup_pada_tiket_jasa(db, petugas, supplier):
    """Tiket yang bukan jasa TIDAK menyimpan penunjuk pesanan.

    Dikosongkan terang-terangan, bukan dibiarkan apa adanya: kiriman ULANG
    boleh mengubah tiket, dan tiket yang pernah salah ditandai jasa tak boleh
    menyimpan penunjuk pesanan diam-diam — produksi akan memasukkan barang
    yang dibeli ke pesanan orang.
    """
    data = tiket_jasa(pelanggan_id=None, jasa_id=99)
    data.jasa = False
    data.supplier_id = supplier.id
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert trx.jasa_id is None


async def test_pesanan_yang_bukan_milik_pelanggan_ditolak(db, petugas, pelanggan):
    """Salah pesanan = barang diserahkan ke orang yang salah.

    Tabel `jasa` milik repo penggilingan dan tak ada di metadata modul ini,
    jadi di lingkungan uji ini daftar pesanan berjalan selalu KOSONG — dan
    karena itu penunjuk apa pun bukan milik siapa pun. Yang diuji di sini
    justru itu: penunjuk yang tak bisa dibuktikan sah DITOLAK, bukan diterima
    dengan harapan produksi akan memeriksanya nanti.
    """
    with pytest.raises(service.LayananError) as e:
        await service.simpan_timbang_pertama(
            db, akun=petugas,
            data=tiket_jasa(pelanggan_id=pelanggan.id, jasa_id=12345))
    assert "bukan milik pelanggan ini" in e.value.args[0], e.value.args[0]


async def test_tanpa_penunjuk_berarti_pesanan_baru(db, petugas, pelanggan):
    """Bawaannya pesanan BARU, dan yang melahirkannya PRODUKSI.

    Pos timbang menulis tiketnya saja. Tiket bisa dibatalkan atau direvisi, dan
    tiket batal yang sudah melahirkan pesanan akan meninggalkan pesanan yatim
    di sisi produksi — pesanan yang menuntut barang yang tak pernah ada.
    """
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=tiket_jasa(pelanggan_id=pelanggan.id))
    assert trx.jasa_id is None
    assert trx.pelanggan_id == pelanggan.id


async def test_daftar_pesanan_tak_meledak_tanpa_tabel_jasa(db, pelanggan):
    """Tanpa tabel `jasa`, borangnya tetap bisa dipakai.

    Pemasangan tanpa sistem penggilingan, atau produksi yang belum bermigrasi.
    Yang hilang cuma penawaran "tambahkan ke pesanan"; layar galat di pos
    sementara truknya di jembatan jauh lebih buruk.
    """
    assert await service.pesanan_jasa_berjalan(db, pelanggan.id) == []
    assert await service.pesanan_jasa_semua_berjalan(db) == []


# ════════════════ 4 · ATURAN TIMBANGNYA TAK BERUBAH ════════════════

async def test_aturan_timbang_jasa_sama_dengan_gabah_dibeli(db, petugas,
                                                            pelanggan, supplier):
    """Cuplikan aturan yang tersimpan di tiket jasa SAMA PERSIS.

    Kalau suatu hari jasa diberi tara atau ambangnya sendiri, dua tiket untuk
    muatan yang fisiknya sama akan dinilai dengan dua kaidah — dan selisihnya
    akan dicari di timbangan, bukan di kode.
    """
    t_jasa = await service.simpan_timbang_pertama(
        db, akun=petugas, data=tiket_jasa(pelanggan_id=pelanggan.id))
    data = tiket_jasa(pelanggan_id=None)
    data.jasa = False
    data.supplier_id = supplier.id
    data.nomor_polisi = "AD 5678 ZZ"
    t_beli = await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    import json
    a_jasa = json.loads(t_jasa.aturan_snapshot)
    a_beli = json.loads(t_beli.aturan_snapshot)
    for kunci in ("sumber_tara", "tara_tetap_kg", "ambang_jenis",
                  "ambang_nilai", "ambang_arah", "acuan"):
        assert a_jasa[kunci] == a_beli[kunci], kunci


async def test_tiket_jasa_tetap_dua_kali_timbang(db, petugas, pelanggan):
    """Tiketnya TERBUKA setelah timbang pertama — netto dari dua angka.

    Bobot barangnya yang jadi dasar yang ditunjukkan ke pemiliknya, dan satu
    kali timbang tak menghasilkan netto sama sekali.
    """
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=tiket_jasa(pelanggan_id=pelanggan.id))
    assert not trx.selesai
    assert trx.timbang1_kg == 12_000


async def test_pemilik_tak_pernah_bocor_ke_kolom_pemasok(db, petugas, pelanggan):
    """Penjaga menyeluruh: TAK SATU PUN tiket jasa mengisi `supplier_id`.

    Dibaca dari tabelnya, bukan dari nilai balik fungsinya — yang dijaga adalah
    apa yang TERSIMPAN.
    """
    for i in range(3):
        d = tiket_jasa(pelanggan_id=pelanggan.id, berat=10_000 + i)
        d.nomor_polisi = f"AD {1000 + i} AA"
        await service.simpan_timbang_pertama(db, akun=petugas, data=d)
    await db.flush()
    baris = (await db.execute(select(TimbanganTransaksi))).scalars().all()
    assert len(baris) == 3
    assert {b.supplier_id for b in baris} == {None}
    assert {b.pelanggan_id for b in baris} == {pelanggan.id}


# ═════ 7 · TANDA `jasa` — tersimpan, bukan diturunkan (migrasi 0041) ═════
#
# Cacat lapangan 2 Oktober 2026. Bagian ini diperiksa TERPISAH dari bagian 1
# karena pertanyaannya beda: bagian 1 bertanya "kolom pihaknya benar?",
# bagian ini bertanya "TANDA JASA-nya sendiri selamat sampai basis data?" —
# dan keduanya bisa benar salah satu tanpa yang lain.

async def test_tanda_jasa_pemasok_ketik_bebas_tetap_false(db, petugas):
    """Sisi SEBALIKNYA dari `test_pemilik_boleh_diketik_bebas`: pembelian
    biasa yang pemasoknya diketik bebas tak boleh ikut tertandai jasa hanya
    karena `pihak_nama` terisi — satu-satunya pembeda memang `data.jasa`,
    bukan ada-tidaknya nama bebas."""
    data = tiket_jasa(pelanggan_id=None, pihak_nama="CV Makmur (baru)")
    data.jasa = False
    data.supplier_id = None
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert trx.pihak_nama == "CV Makmur (baru)"
    assert trx.jasa is False


async def test_tanda_jasa_bertahan_pada_kiriman_ulang(db, petugas, pelanggan):
    """Kiriman ulang (antrean luring) memakai `kunci` yang sama — baris yang
    SAMA diperbarui, bukan baris baru. Tandanya wajib tetap benar sesudahnya,
    sebab jalur simpan kedua kalinya menjalankan kode yang sama persis."""
    data = tiket_jasa(pelanggan_id=pelanggan.id)
    data.kunci = "kunci-kirim-ulang-1"
    trx1 = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx2 = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert trx1.id == trx2.id, "kiriman ulang seharusnya memperbarui baris yang sama"
    assert trx2.jasa is True

"""Nama sopir boleh baru, tetapi beda huruf/spasi tidak membuat orang baru."""
from unicodedata import normalize
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.timbangan.models import TimbanganSopir, TimbanganSopirAlias


class NamaSopirTidakSah(ValueError):
    pass


def nama_pengganti(nama: str | None) -> bool:
    """Kenali penanda tanpa identitas, termasuk beda tanda baca dan Unicode.

    Cocokkan seluruh nama, bukan potongan: nama seperti Arif dan Didik tetap
    apa adanya, tanpa menebak bahwa ejaan yang mirip adalah orang yang sama.
    Kosong tetap ditangani aturan cara timbang (partai boleh tanpa sopir).
    """
    if not nama or not nama.strip():
        return False
    bersih, _ = normalisasi_nama(nama)
    kata = re.findall(r"[^\W_]+", bersih.casefold())
    if kata and kata[0] in {"pak", "bapak", "mas", "bu", "ibu"}:
        kata = kata[1:]
    kunci = "".join(kata)
    penanda = {
        "lain", "lainlain", "lainnya", "lainlainnya", "dll",
        "tanpanama", "tidakdiketahui", "belumdiketahui", "belumdiisi",
        "tidakada", "unknown", "noname", "none", "null", "na",
        "sopir", "supir", "driver",
    }
    return (not any(c.isalpha() for c in kunci)
            or re.sub(r"\d+$", "", kunci) in penanda)


def normalisasi_nama(nama: str) -> tuple[str, str]:
    bersih = " ".join(normalize("NFKC", nama).split())
    return bersih, bersih.casefold()


async def daftar_pilihan(db) -> list[dict]:
    """Nama utama beserta alias untuk pencarian lokal, tanpa membuat entri."""
    utama = (await db.scalars(select(TimbanganSopir).order_by(TimbanganSopir.nama))).all()
    aliases = (await db.scalars(select(TimbanganSopirAlias))).all()
    per_sopir = {}
    for a in aliases:
        per_sopir.setdefault(a.sopir_id, []).append(a.nama)
    return sorted(
        [{"nama": s.nama, "alias": per_sopir.get(s.id, [])}
         for s in utama if not nama_pengganti(s.nama)],
        key=lambda s: normalisasi_nama(s["nama"])[1],
    )


async def nama_utama(db, nama: str | None) -> str | None:
    if not nama or not nama.strip():
        return nama
    if nama_pengganti(nama):
        raise NamaSopirTidakSah(
            "Isi nama sopir sebenarnya. Nama pengganti seperti LAIN-LAIN, "
            "tanda -, atau tidak diketahui tidak boleh dipakai."
        )
    bersih, kunci = normalisasi_nama(nama)
    # Hanya alias yang sudah dikonfirmasi, tanpa menebak kemiripan nama.
    utama = await db.scalar(
        select(TimbanganSopir).join(
            TimbanganSopirAlias, TimbanganSopirAlias.sopir_id == TimbanganSopir.id
        ).where(TimbanganSopirAlias.kunci_nama == kunci)
    )
    if utama is not None:
        return utama.nama
    q = select(TimbanganSopir).where(TimbanganSopir.kunci_nama == kunci)
    ada = (await db.execute(q)).scalar_one_or_none()
    if ada is not None:
        return ada.nama
    baru = TimbanganSopir(nama=bersih, kunci_nama=kunci)
    try:
        async with db.begin_nested():
            db.add(baru)
            await db.flush()
    except IntegrityError:
        # Constraint unik yang memutus perlombaan, bukan SELECT di depan.
        ada = (await db.execute(q)).scalar_one_or_none()
        if ada is None:
            raise
        return ada.nama
    return baru.nama

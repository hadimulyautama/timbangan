"""Transport formulir yang boleh diantrekan; aturan tetap milik rute/layanan.

Kunci unik diklaim DI DALAM transaksi DB yang menulis timbang. Kiriman
bersamaan menunggu constraint PK, lalu membaca jawaban yang sama. Gagal
validasi me-rollback seluruh kiriman, termasuk beberapa baris partai.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps
from hashlib import sha256
from inspect import signature
import json
import logging
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.timbangan.models import TimbanganKiriman
from app.config import settings

log = logging.getLogger("timbangan.kiriman")
HEADER = "x-timbangan-kiriman"


def aktif(request):
    return getattr(request.state, "kiriman", None) is not None


def waktu(request):
    return getattr(request.state, "waktu_kiriman", None)


def _hasil(response, kunci, *, tersimpan=False):
    tujuan = response.headers.get("location", "")
    q = parse_qs(urlsplit(tujuan).query)
    pesan = (q.get("err") or q.get("ok") or ["Kiriman belum dikonfirmasi."])[0]
    return {"kunci": kunci, "tersimpan": tersimpan or bool(q.get("ok")),
            "peringatan": bool(q.get("err")), "pesan": pesan, "tujuan": tujuan}


async def sebelum_integrasi(request, db, tujuan):
    """Produksi harus membaca timbang yang sudah COMMIT.

    Tanda terima awal mengatakan verifikasi belum dikonfirmasi. Bila proses
    mati setelah commit, replay hanya membaca tanda terima ini: tidak
    memanggil mutasi Produksi untuk kedua kalinya. Detail tetap memberi akses
    pemeriksaan/verifikasi lama di Produksi.
    """
    if not aktif(request):
        return
    item = request.state.kiriman
    item.jawaban = json.dumps({
        "kunci": item.kunci, "tersimpan": True, "peringatan": True,
        "pesan": "Timbangan tersimpan; verifikasi Produksi belum dikonfirmasi. Periksa detail tiket.",
        "tujuan": tujuan,
    })
    await db.commit()
    request.state.kiriman_disahkan = True


def terima_kiriman(fungsi):
    @wraps(fungsi)
    async def bungkus(*args, **kw):
        request, db, akun = kw["request"], kw["db"], kw["akun"]
        kunci = request.headers.get(HEADER)
        if not kunci:
            return await fungsi(*args, **kw)
        try:
            if str(UUID(kunci)) != kunci:
                raise ValueError()
        except ValueError:
            return JSONResponse({"tersimpan": False, "pesan": "Kunci kiriman tidak sah."}, status_code=422)
        if request.headers.get("x-timbangan-akun") != str(akun.id):
            return JSONResponse({"tersimpan": False, "pesan": "Akun kiriman berbeda. Masuk kembali dengan akun pembuatnya."}, status_code=403)
        form = await request.form()
        if form.get("kunci") != kunci:
            return JSONResponse({"tersimpan": False, "pesan": "Kunci formulir dan kiriman berbeda."}, status_code=409)
        cap = request.headers.get("x-timbangan-waktu", "")
        try:
            stamp = datetime.fromisoformat(cap.replace("Z", "+00:00")) if cap else None
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError()
        except ValueError:
            return JSONResponse({"tersimpan": False, "pesan": "Waktu kiriman tidak sah."}, status_code=422)
        request.state.waktu_kiriman = stamp.astimezone(ZoneInfo(settings.app_timezone)) if stamp else None
        isi = json.dumps([sorted(form.multi_items(), key=lambda p: p[0]), cap], ensure_ascii=False)
        sidik = sha256(isi.encode()).hexdigest()
        jalur = request.url.path
        item = await db.get(TimbanganKiriman, kunci)
        if item is None:
            # ON CONFLICT menunggu transaksi pemegang kunci. Tidak memakai
            # savepoint sebagai penulisan pertama: SQLite dapat mengesahkannya
            # sendiri sehingga rollback validasi tidak ikut membuang reservasi.
            if db.bind.dialect.name == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            else:
                from sqlalchemy.dialects.postgresql import insert
            await db.execute(insert(TimbanganKiriman).values(
                kunci=kunci, akun_id=akun.id, jalur=jalur, sidik=sidik,
            ).on_conflict_do_nothing(index_elements=["kunci"]))
            item = await db.get(TimbanganKiriman, kunci)
        if item.akun_id != akun.id:
            return JSONResponse({"tersimpan": False, "pesan": "Kunci ini milik akun lain."}, status_code=403)
        if item.jalur != jalur or item.sidik != sidik:
            return JSONResponse({"tersimpan": False, "pesan": "Isi berubah untuk kunci yang sudah dipakai. Periksa hasil sebelumnya; jangan buat kiriman pengganti."}, status_code=409)
        if item.jawaban:
            return JSONResponse(json.loads(item.jawaban))
        request.state.kiriman = item
        request.state.kiriman_disahkan = False
        try:
            response = await fungsi(*args, **kw)
            hasil = _hasil(response, kunci, tersimpan=request.state.kiriman_disahkan)
            if not hasil["tersimpan"]:
                await db.rollback()
                return JSONResponse(hasil, status_code=422)
            item.jawaban = json.dumps(hasil, ensure_ascii=False)
            await db.commit()
            return JSONResponse(hasil)
        except Exception as exc:
            await db.rollback()
            # Timbang pengiriman mungkin sudah sah; hilangnya hasil integrasi
            # tidak boleh memaksa pengiriman timbang/mutasi berikutnya.
            if request.state.kiriman_disahkan:
                receipt = await db.get(TimbanganKiriman, kunci)
                log.exception("Hasil integrasi kiriman belum dikonfirmasi")
                return JSONResponse(json.loads(receipt.jawaban))
            from app.timbangan import service, logic
            if isinstance(exc, (service.LayananError, logic.ValidasiError)):
                return JSONResponse({"kunci": kunci, "tersimpan": False, "pesan": str(exc)}, status_code=422)
            if isinstance(exc, (ValueError, TypeError)):
                return JSONResponse({"kunci": kunci, "tersimpan": False, "pesan": "Isian belum sah. Periksa kembali angka dan pilihan formulir."}, status_code=422)
            if isinstance(exc, DBAPIError):
                log.exception("Kiriman belum tersimpan karena basis data menolak")
                return JSONResponse({"kunci": kunci, "tersimpan": False, "pesan": "Server belum mengonfirmasi penyimpanan. Isian tetap di perangkat."}, status_code=503)
            raise
    # FastAPI perlu anotasi asli, bukan nama tertunda di globals pembungkus.
    bungkus.__signature__ = signature(fungsi, eval_str=True)
    return bungkus

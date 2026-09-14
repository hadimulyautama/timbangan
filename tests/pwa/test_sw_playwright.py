"""Service worker pos timbang di Chromium sungguhan (Tahap A rasa native).

Yang dijaga: nama cache mengikuti VERSI server (bukan angka tulisan tangan),
jaringan putus → /luring, dan versi baru ditawarkan lewat pil — tanpa memuat
ulang sendiri. Server = proses uvicorn; "offline" = prosesnya dimatikan.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
if not os.environ.get("UJI_PG_URL", "").strip():
    pytest.skip("UJI_PG_URL kosong — uji Playwright pos timbang butuh Postgres", allow_module_level=True)

AKAR = Path(__file__).resolve().parents[2]
PREFIX = "/timbangan"


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self):
        self.port = _port()
        self.alamat = f"http://127.0.0.1:{self.port}"
        self.proses = None

    def nyalakan(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(AKAR), "DATABASE_URL": os.environ["UJI_PG_URL"]}
        self.proses = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.pwa.aplikasi_uji:app",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=AKAR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(150):
            try:
                urllib.request.urlopen(self.alamat + PREFIX + "/masuk", timeout=0.5)
                return
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        raise RuntimeError("server uji tak kunjung hidup")

    def matikan(self) -> None:
        if self.proses:
            # Sambungan SSE yang masih terbuka menahan uvicorn berhenti dengan
            # sopan; sesudah lima detik prosesnya dibunuh — di uji ini yang
            # penting servernya MATI, bukan matinya rapi.
            self.proses.terminate()
            try:
                self.proses.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proses.kill()
                self.proses.wait(timeout=5)
            self.proses = None

    def versi_server(self, versi: str) -> None:
        req = urllib.request.Request(self.alamat + "/uji/versi", method="POST",
                                     data=json.dumps({"versi": versi}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2)


@pytest.fixture
def server():
    s = Server()
    s.nyalakan()
    try:
        yield s
    finally:
        s.matikan()


@pytest.fixture
def page():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        # "kurangi gerakan": transisi lintas dokumen tak selesai di peramban tanpa
        # layar dan lapisannya menelan ketukan pada pil.
        ctx = b.new_context(viewport={"width": 390, "height": 800}, reduced_motion="reduce")
        yield ctx.new_page()
        ctx.close()
        b.close()


def _tunggu(page, js: str, batas: float = 15.0):
    akhir = time.time() + batas
    while time.time() < akhir:
        v = page.evaluate(js)
        if v:
            return v
        time.sleep(0.25)
    raise AssertionError(f"tak kunjung benar: {js}")


def _masuk(page, alamat: str) -> None:
    page.goto(alamat + PREFIX + "/masuk")
    page.fill("[name=username]", "wahid")
    page.fill("[name=sandi]", "rahasia123")
    page.fill("[name=perangkat]", "P0") if page.locator("[name=perangkat]").count() else None
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    assert "/masuk" not in page.url


def test_cache_bernama_versi_server_dan_luring_saat_putus(server, page):
    from app.timbangan.web import VERSI

    _masuk(page, server.alamat)
    _tunggu(page, "navigator.serviceWorker.getRegistration().then(r => !!(r && r.active))")
    url = page.evaluate("navigator.serviceWorker.getRegistration().then(r => r.active.scriptURL)")
    assert url.endswith(f"{PREFIX}/sw.js?v={VERSI}")
    assert _tunggu(page, "caches.keys().then(k => k.length ? k : null)") == [f"timbangan-v{VERSI}"]
    _tunggu(page, f"caches.match('{PREFIX}/luring').then(r => !!r)")

    server.matikan()
    page.goto(server.alamat + PREFIX + "/daftar")
    assert "Tanpa jaringan" in page.content()


def test_versi_baru_ditawarkan_lewat_pil_tanpa_muat_ulang(server, page):
    _masuk(page, server.alamat)
    page.evaluate("window.__tanda = 7")
    server.versi_server("9999")
    pil = page.locator(".pil-versi")
    pil.wait_for(state="visible", timeout=20000)   # denyut penanda di beranda
    assert "Versi baru" in pil.inner_text()
    assert page.evaluate("window.__tanda") == 7
    # Ketukan sungguhan pada koordinat pil (bukan pemeriksaan sasaran milik
    # Playwright, yang di peramban tanpa layar tersesat oleh lapisan
    # ::view-transition). Kalau pilnya tertutup, reload tak terjadi dan
    # `__tanda` tetap 7.
    kotak = pil.bounding_box()
    with page.expect_navigation():
        page.mouse.click(kotak["x"] + kotak["width"] / 2, kotak["y"] + kotak["height"] / 2)
    assert page.evaluate("window.__tanda") is None


def test_luring_menampilkan_acuan_dengan_cap_waktu(server, page):
    """Daftar acuan pos timbang (pemasok, jenis, kendaraan) tetap terbaca saat
    putus, di bawah baris cap waktu selebar layar."""
    _masuk(page, server.alamat)
    _tunggu(page, "!!localStorage.getItem('timbangan-acuan')")
    _tunggu(page, f"caches.match('{PREFIX}/luring').then(r => !!r)")
    server.matikan()
    page.goto(server.alamat + PREFIX + "/daftar")
    bar = page.locator(".putus")
    bar.wait_for(state="visible", timeout=5000)
    assert "Data pukul" in bar.inner_text() and "sedang offline" in bar.inner_text()
    assert bar.evaluate("e => e.getBoundingClientRect().width") >= page.evaluate("window.innerWidth") - 2
    assert "Gabah" in page.content()   # jenis dari benih pastikan_jenis


# ─────────────── Tahap C: dorongan server, pil "perubahan baru" ───────────────

def test_dorongan_memunculkan_pil_tanpa_mengganti_layar(server, page):
    """Sesi B (petugas lain) menyimpan tiket → beranda sesi A menerima
    dorongan dalam hitungan detik; layar TIDAK berganti sendiri, pil menunggu
    diketuk; ketukan memuat ulang dan tiketnya muncul."""
    import subprocess

    _masuk(page, server.alamat)
    _tunggu(page, "window.timbangan && window.timbangan.jalur && window.timbangan.jalur() === 'sse'")
    lama = page.evaluate("document.querySelector('.bingkai').innerHTML")

    # Sesi B lewat layanan, di proses lain — bukan lewat peramban A.
    kode = subprocess.run(
        [sys.executable, "-c", (
            "import asyncio, os\n"
            "from uuid import uuid4\n"
            "from sqlalchemy import select\n"
            "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n"
            "from app.timbangan import logic, service\n"
            "from app.timbangan.models import TimbanganAkun\n"
            "async def m():\n"
            "    m = create_async_engine(os.environ['UJI_PG_URL']); S = async_sessionmaker(m, expire_on_commit=False)\n"
            "    async with S() as db:\n"
            "        akun = (await db.execute(select(TimbanganAkun).where(TimbanganAkun.username == 'wahid'))).scalar_one()\n"
            "        jenis = next(j for j in await service.daftar_jenis(db) if j.arah == logic.MASUK)\n"
            "        trx = await service.simpan_timbang_pertama(db, akun=akun, data=service.InputTimbang(\n"
            "            kunci=str(uuid4()), arah=jenis.arah, jenis_kode=jenis.kode, berat_kg=12000,\n"
            "            pihak_nama='Pak Dorong', nomor_polisi='B 2 UJ', nama_sopir='Sopir'))\n"
            "        print(trx.kode)\n"
            "    await m.dispose()\n"
            "asyncio.run(m())\n")],
        cwd=AKAR, env={**os.environ, "PYTHONPATH": str(AKAR)}, capture_output=True, text=True, timeout=60)
    assert kode.returncode == 0, kode.stderr[-800:]
    kode_tiket = kode.stdout.strip().splitlines()[-1]

    pil = page.locator("[data-pil]")
    pil.wait_for(state="visible", timeout=5000)
    assert "perubahan baru" in pil.inner_text()
    assert page.evaluate("document.querySelector('.bingkai').innerHTML") == lama, "layar berganti sendiri"
    assert kode_tiket not in page.content()

    kotak = pil.bounding_box()
    with page.expect_navigation():
        page.mouse.click(kotak["x"] + kotak["width"] / 2, kotak["y"] + kotak["height"] / 2)
    page.wait_for_load_state("networkidle")
    isi = page.evaluate("document.querySelector('.bingkai').innerHTML")
    assert isi != lama, "sesudah diketuk layar tak berubah"
    assert kode_tiket in isi or "B 2 UJ" in isi or "Pak Dorong" in isi, "tiket sesi B tak muncul"

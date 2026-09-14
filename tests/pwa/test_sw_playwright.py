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
            self.proses.terminate()
            self.proses.wait(timeout=10)
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
        ctx = b.new_context(viewport={"width": 390, "height": 800})
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
    with page.expect_navigation():
        pil.click()
    assert page.evaluate("window.__tanda") is None

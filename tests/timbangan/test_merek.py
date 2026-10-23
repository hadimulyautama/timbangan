"""Cegah identitas produk lain masuk kembali ke TeraFlow."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2] / 'app/timbangan'


def test_tidak_ada_merek_lama_di_tampilan_dan_metadata():
    files = list((ROOT/'templates').glob('*.html'))
    files += list((ROOT/'static').glob('*.js'))
    files += [ROOT/'static/manifest.json']
    for path in files:
        # Kelas internal komponen bersama bukan teks atau identitas produk.
        text = path.read_text().replace('class="padiflow-ui ', 'class="')
        assert not re.search(r'padi\s*flow', text, re.I), path.name


def test_aset_merek_lama_tidak_diterbitkan():
    assert not list((ROOT/'static').rglob('*padiflow*'))
    assert (ROOT/'static/teraflow-logo.png').is_file()


def test_nama_teraflow_di_halaman_masuk_dan_identitas_pwa():
    assert '>TeraFlow</h1>' in (ROOT/'templates/masuk.html').read_text()
    assert 'content="TeraFlow"' in (ROOT/'templates/base.html').read_text()

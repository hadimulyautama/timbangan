"""Timbangan dan Operasional mengimpor kelas armada yang sama."""
from app.timbangan.models import TimbanganKendaraan
from hmu_core import Armada


def test_nama_lama_timbangan_hanya_alias_model_bersama():
    assert TimbanganKendaraan is Armada

"""Integration with Bambu Studio's command line (skipped when Bambu Studio is not installed)."""
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from cad import Part
from cad.threemf import export_3mf

BAMBU = Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")
if not BAMBU.exists() and shutil.which("bambu-studio"):
    BAMBU = Path(shutil.which("bambu-studio"))
pytestmark = pytest.mark.skipif(not BAMBU.exists(), reason="Bambu Studio not installed")


def _coaster():
    c = Part("coaster", material="PLA"); c.cylinder(90, 5); c.cylinder(80, 2, at=(0, 0, 3), op="cut")
    i = Part("insert", material="TPU"); i.cylinder(80, 2, at=(0, 0, 3))
    return {"coaster": c, "insert": i}


def _bambu_parts(tmp_path, src: Path) -> str:
    out = tmp_path / ("bambu_" + src.name)
    p = subprocess.run([str(BAMBU), "--outputdir", str(tmp_path), "--export-3mf", out.name, str(src)],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout[-2000:]
    with zipfile.ZipFile(out) as z:
        return z.read("Metadata/model_settings.config").decode()


def test_bambu_assigns_filaments_from_objects_mode(tmp_path):
    src = tmp_path / "objects.3mf"
    export_3mf(_coaster(), src, mode="objects")
    cfg = _bambu_parts(tmp_path, src)
    # two objects: coaster on filament 1, insert on filament 2 (from the colour group)
    blocks = cfg.split("<object ")[1:]
    got = {b.split('key="name" value="')[1].split('"')[0]: b.split('key="extruder" value="')[1].split('"')[0] for b in blocks}
    assert got == {"coaster": "1", "insert": "2"}


def test_bambu_loads_multimaterial_as_one_object_with_part_filaments(tmp_path):
    src = tmp_path / "mm.3mf"
    export_3mf(_coaster(), src, mode="multimaterial", title="coaster")
    cfg = _bambu_parts(tmp_path, src)
    assert cfg.count("<object ") == 1 and cfg.count("<part ") == 2
    parts = cfg.split("<part ")[1:]
    got = {b.split('key="name" value="')[1].split('"')[0]: b.split('key="extruder" value="')[1].split('"')[0] for b in parts}
    assert got == {"coaster": "1", "insert": "2"}

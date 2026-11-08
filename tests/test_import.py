"""Importing STEP / IGES / STL / BREP files: names, colours, units, placement, project integration."""
import json
import shutil
from pathlib import Path

import pytest

from cad import CadError, Part
from cad.cli import main

FIX = Path(__file__).parent / "fixtures"
STEP = FIX / "servo_inch.step"   # inch units; bodies housing (10 mm cube) and shaft (5 x 20 mm cylinder at x = 30)
STL = FIX / "bracket.stl"        # L-bracket, 3330 mm3


def test_step_names_colours_and_inch_conversion():
    p = Part.from_file(str(STEP), reference=True)
    assert p.solid_count == 2 and p.reference
    assert p.volume == pytest.approx(1000 + 3.14159265 * 2.5 ** 2 * 20, rel=1e-6)
    assert p.bbox.max[2] == pytest.approx(20)  # 20 mm, not 20 inches or 20/25.4
    assert {"import1.housing", "import1.shaft"} <= set(p.references())
    h = Part.from_file(str(STEP), solid="housing")
    assert h.volume == pytest.approx(1000) and h.color == "#1a1a1a"


def test_select_align_and_at():
    h = Part.from_file(str(STEP), solid="shaft", align=("center", "center", "min"), at=(0, 0, 5))
    lo, hi = h.bbox.min, h.bbox.max
    assert lo[0] == pytest.approx(-2.5) and hi[1] == pytest.approx(2.5) and lo[2] == pytest.approx(5)
    with pytest.raises(CadError) as e:
        Part.from_file(str(STEP), solid="motor")
    assert e.value.code == "NOT_FOUND" and "housing" in e.value.details["bodies"]


def test_stl_becomes_an_editable_solid():
    b = Part.from_file(str(STL))
    assert b.is_valid() and b.solid_count == 1 and b.volume == pytest.approx(3330, rel=1e-6)
    assert len(b.faces()) == 8  # coplanar triangles merged into real faces
    b.hole(5, at=(0, 2))
    assert len(b.find_holes()) == 1 and b.is_valid()
    s = Part.from_file(str(STL), scale=25.4)
    assert s.volume == pytest.approx(3330 * 25.4 ** 3, rel=1e-6)


def test_import_as_cutter_and_errors(tmp_path):
    p = Part("plate"); p.box(60, 40, 6)
    p.import_file(str(STEP), solid="housing", op="cut", at=(0, 0, 1))
    assert p.volume == pytest.approx(60 * 40 * 6 - 500)
    with pytest.raises(CadError) as e:
        Part.from_file(str(STL), max_triangles=10)
    assert "triangles" in e.value.message
    with pytest.raises(CadError) as e:
        Part.from_file(str(tmp_path / "nope.step"))
    assert e.value.code == "NOT_FOUND"
    (tmp_path / "x.obj").write_text("")
    with pytest.raises(CadError):
        Part.from_file(str(tmp_path / "x.obj"))


def test_cli_info():
    code, out, _ = main(["info", str(STEP), "--json"], FIX)
    r = json.loads(out)["result"]
    assert code == 0 and r["units_in_file"] == "inch" and [b["name"] for b in r["bodies"]] == ["housing", "shaft"]
    assert r["bodies"][0]["size"] == pytest.approx([10, 10, 10])


MODEL = '''
from cad import Part

def build():
    servo = Part.from_file("vendor/servo.step", reference=True, align=("center", "center", "min"), at=(0, 0, 3))
    plate = Part("plate"); plate.box(50, 30, 3)
    return [plate, servo]
'''


def test_project_rebuilds_when_imported_file_changes(tmp_path):
    (tmp_path / "vendor").mkdir()
    shutil.copy(STEP, tmp_path / "vendor" / "servo.step")
    main(["init"], tmp_path)
    (tmp_path / "model.py").write_text(MODEL)
    code, out, err = main(["build", "--json"], tmp_path)
    assert code == 0, err
    assert json.loads(main(["build", "--json"], tmp_path)[1])["result"]["cached"]
    with open(tmp_path / "vendor" / "servo.step", "a") as f:
        f.write("\n")
    r = json.loads(main(["build", "--json"], tmp_path)[1])["result"]
    assert not r["cached"] and r["revision"] == 2
    code, out, _ = main(["clearance", "--json"], tmp_path)
    assert code == 0


def test_large_sources_are_stored_once(tmp_path):
    from cad.project import Store

    big = tmp_path / "big.stl"
    big.write_bytes(b"x" * 300_000)
    st = Store(tmp_path)
    _, files = st.source_hash()
    for rev in ("a", "b"):
        st.snapshot_file(big, tmp_path / rev / "big.stl", files["big.stl"])
    assert (tmp_path / "a" / "big.stl").stat().st_ino == (tmp_path / "b" / "big.stl").stat().st_ino

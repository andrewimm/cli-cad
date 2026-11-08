import json

import pytest

from cad import CadError, Part
from cad.analysis import clearance_matrix
from cad.cli import main
from cad.engine import Engine


def test_wall_thickness_finds_ligament():
    p = Part("p")
    p.box(40, 20, 10)
    p.hole(4, at=(17, 0))              # leaves 20 - 19 = 1 mm to the +X face
    rep = p.wall_thickness()
    assert rep["min"] == pytest.approx(1.0, abs=1e-3)
    assert rep["thinnest"][0]["at"][0] == pytest.approx(19.0, abs=1e-3) or rep["thinnest"][0]["at"][0] == pytest.approx(20.0, abs=1e-3)
    with pytest.raises(CadError) as e:
        p.assert_min_thickness(2)
    assert e.value.code == "VALIDATION_FAILED" and e.value.details["thinnest"]
    q = Part("q")
    q.box(40, 20, 10)
    q.assert_min_thickness(9.9)


def test_clearance_matrix_and_reference_face_gaps():
    servo = Part("servo", reference=True)
    servo.box(20, 10, 20, at=(0, 0, 5), name="body")
    b = Part("bracket")
    b.box(30, 10, 5)                                           # supports the bottom face
    b.box(2, 10, 20, at=(-11.5, 0, 5), align=("center", "center", "min"))   # wall 0.5 mm from -X face
    cm = clearance_matrix({"servo": servo, "bracket": b}, 0.5)
    (pair,) = cm["pairs"]
    assert pair["state"] == "touching" and cm["violations"]
    gaps = {f["faces"][0]: f["gap"] for f in pair["reference_faces"]}
    assert gaps["body.bottom"] == pytest.approx(0, abs=1e-4)
    assert gaps["body.left"] == pytest.approx(0.5, abs=1e-4)
    assert gaps["body.right"] is None and gaps["body.top"] is None


def _project(tmp_path, src):
    (tmp_path / "cad.toml").write_text('[project]\nname = "t"\nentry = "model.py"\n')
    (tmp_path / "model.py").write_text(src)
    return tmp_path


LEG = '''
from cad import Parameter, Part
a = Parameter("angle", 0, min=0, max=90)
def build():
    ref = Part("envelope", reference=True)
    ref.box(5, 5, 5, at=(0, 0, 40))
    base = Part("base"); base.box(50, 20, 5)
    base.box(4, 20, 12, at=(-20, 0, 5), align=("center", "center", "min"))   # a post the arm reaches only near 90
    arm = Part("arm"); arm.box(4, 4, 30, at=(0, 0, 8))
    arm.rotate(-a, axis="y", center=(0, 0, 8))
    return {"envelope": ref, "base": base, "arm": arm}
'''


def test_cli_clearance_sweep_export(tmp_path):
    proj = _project(tmp_path, LEG)
    e = Engine()
    assert main(["build"], proj, e)[0] == 0
    code, out, err = main(["clearance", "--min", "0.5", "--json"], proj, e)
    r = json.loads(out)
    assert code == 0 and r["ok"] and r["result"]["references"] == ["envelope"]
    # at 90 degrees the arm lies flat across the post
    code, out, err = main(["sweep", "angle", "0:90:45", "--min", "0.5", "--render", "front", "--size", "160x120", "--json"], proj, e)
    r = json.loads(out)
    assert code == 4 and r["error"]["code"] == "VALIDATION_FAILED"
    vals = {row["value"]: bool(row.get("violations")) for row in r["result"]["results"]}
    assert vals == {0: False, 45: False, 90: True}
    assert all(row["images"] for row in r["result"]["results"])
    assert json.loads(main(["status", "--json"], proj, e)[1])["result"]["head"] == 1, "sweep restores the active revision"
    code, out, err = main(["export", "--format", "step", "--json"], proj, e)
    r = json.loads(out)["result"]
    assert {f["part"] for f in r["files"]} == {"base", "arm"} and r["skipped_reference_parts"] == ["envelope"]
    code, out, err = main(["measure", "arm", "--thickness", "--json"], proj, e)
    assert json.loads(out)["result"]["wall_thickness"]["min"] == pytest.approx(4, abs=1e-3)


def test_sweep_values_parsing():
    from cad.cli import _sweep_values

    assert _sweep_values("0:90:15") == [0, 15, 30, 45, 60, 75, 90]
    assert _sweep_values("0,2.5,10") == [0, 2.5, 10]


def test_allow_contact_and_measure_all_parts(tmp_path):
    proj = _project(tmp_path, LEG)
    e = Engine()
    main(["build"], proj, e)
    code, out, _ = main(["clearance", "--min", "5", "--json"], proj, e)
    assert code == 4
    two = '''
from cad import Part
def build():
    a = Part("a"); a.box(10, 10, 10)
    b = Part("b"); b.box(10, 10, 10, at=(0, 0, 10))
    return {"a": a, "b": b}
'''
    p2 = _project(tmp_path / "p2", two) if (tmp_path / "p2").mkdir() is None else None
    main(["build"], p2, e)
    assert main(["clearance", "--min", "0.5"], p2, e)[0] == 4
    assert main(["clearance", "--min", "0.5", "--allow-contact"], p2, e)[0] == 0
    code, out, _ = main(["measure", "--volume", "--json"], p2, e)
    r = json.loads(out)["result"]
    assert code == 0 and set(r["parts"]) == {"a", "b"} and r["parts"]["a"]["volume"] == pytest.approx(1000)


def test_hole_direction_away_from_part_is_explained():
    p = Part("b")
    p.box(30, 5, 40, at=(0, -0.5, -10), align=("center", "max", "min"))
    with pytest.raises(CadError) as e:
        p.hole(6.2, at=(0, 0, 0), direction="+y")
    assert e.value.code == "HOLE_MISSED" and "'-y'" in e.value.hint
    p.hole(6.2, at=(0, 0, 0), direction="-y")
    assert len(p.find_holes()) == 1

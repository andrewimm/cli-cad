"""The richer eval checks must reject realistic wrong answers, not just accept the reference."""
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

from cadeval.geom_checks import stl_report  # noqa: E402
from cadeval.grade import grade  # noqa: E402
from cadeval.tasks import SOLUTION_DIR, load_tasks  # noqa: E402


def task(tid):
    return load_tasks(ids=[tid])[0]


def failed(g):
    return {c["type"] + (":" + c["part"] if c.get("part") else "") for c in g["checks"] if not c["ok"]}


def script(tmp_path, text, name="model.py"):
    p = tmp_path / name
    p.write_text(text)
    return p


def mutated_dir(tmp_path, tid, old, new, extra=None):
    d = tmp_path / tid
    shutil.copytree(SOLUTION_DIR / tid, d)
    m = d / "model.py"
    src = m.read_text()
    assert old in src, old
    m.write_text(src.replace(old, new))
    for k, v in (extra or {}).items():
        if v is None:
            (d / k).unlink()
        else:
            (d / k).write_text(v)
    return d


def test_hardcoded_pattern_fails_param_rebuild(tmp_path):
    src = (SOLUTION_DIR / "param_hole_pattern.py").read_text()
    s = script(tmp_path, src.replace("center=(W / 2, H / 2)", "center=(50, 35)"))
    g = grade(task("param_hole_pattern"), s)
    assert g["checks"][3]["ok"], "default geometry is still right"
    assert failed(g) == {"param_rebuild"}


def test_round_nut_pockets_rejected(tmp_path):
    src = (SOLUTION_DIR / "split_shaft_clamp.py").read_text()
    s = script(tmp_path, src.replace("Profile.regular_polygon(6, across_flats=5.7, center=(0, y))", "Profile.circle(6.6, center=(0, y))"))
    assert "points_inside:clamp_bottom" in failed(grade(task("split_shaft_clamp"), s))


def test_overlapping_clamp_halves_rejected(tmp_path):
    src = (SOLUTION_DIR / "split_shaft_clamp.py").read_text()
    s = script(tmp_path, src.replace('bottom = half("clamp_bottom", -12)', 'bottom = half("clamp_bottom", -11.5)'))
    assert "interference" in failed(grade(task("split_shaft_clamp"), s))


def test_servo_side_clearance_and_access(tmp_path):
    t = task("servo_envelope_bracket")
    # walls flush against the servo sides: violates the 0.5 mm clearance
    d = mutated_dir(tmp_path / "a", "servo_envelope_bracket", "sx * 25.0", "sx * 24.5")
    assert "keepout" in failed(grade(t, d))
    # mounting holes moved under the servo: screw heads blocked by the servo envelope
    d = mutated_dir(tmp_path / "b", "servo_envelope_bracket", "for x in (-33, 33) for y in (-14, 14)", "for x in (-12, 12) for y in (-5, 5)")
    assert "holes:bracket" in failed(grade(t, d))
    # clamp without a shaft clearance hole obstructs the shaft
    d = mutated_dir(tmp_path / "c", "servo_envelope_bracket", '    c.hole(9, at=(10, 0), name="shaft_clearance")\n', "")
    assert "keepout" in failed(grade(t, d))
    # no PRINT.md
    d = mutated_dir(tmp_path / "d", "servo_envelope_bracket", "x", "x", {"PRINT.md": None})
    assert failed(grade(t, d)) == {"file"}


def test_thin_walls_rejected(tmp_path):
    d = mutated_dir(tmp_path, "servo_envelope_bracket", "b.box(9, 20, 40", "b.box(1.5, 20, 40")
    d2 = d / "model.py"
    d2.write_text(d2.read_text().replace("sx * 25.0", "sx * 21.25").replace("(-25, 0, 50), (25, 0, 50)", "(-35, 0, 10), (35, 0, 10)"))
    assert "min_thickness" in failed(grade(task("servo_envelope_bracket"), d))


def test_robot_leg_collision_sweep_and_thickness(tmp_path):
    t = task("robot_leg")
    # lower link in the same Y slot as the upper link: collides at the knee
    d = mutated_dir(tmp_path / "a", "robot_leg", 'link("lower_link", 110, 5.5)', 'link("lower_link", 110, 0.0)')
    assert "param_sweep" in failed(grade(t, d))
    # slim links leave < 4 mm around the pivot holes
    d = mutated_dir(tmp_path / "b", "robot_leg", "W = 16.0", "W = 11.0")
    f = failed(grade(t, d))
    assert "min_thickness:upper_link" in f and "min_thickness:lower_link" in f
    # wrong rotation sense: foot swings toward -X
    d = mutated_dir(tmp_path / "c", "robot_leg", "lower.rotate(-knee", "lower.rotate(knee")
    assert "param_rebuild" in failed(grade(t, d))
    # no renders at all
    assert "rendered_configurations" in failed(grade(t, SOLUTION_DIR / "robot_leg"))


def test_stl_report_detects_holes_in_mesh(tmp_path):
    from cad import Part

    p = Part("p")
    p.box(10, 10, 10)
    path = tmp_path / "p.stl"
    p.export(str(path))
    good = stl_report(path)
    assert good["boundary_edges"] == 0 and good["non_manifold_edges"] == 0 and good["signed_volume"] == pytest.approx(1000, rel=1e-3)
    data = bytearray(path.read_bytes())
    n = int.from_bytes(data[80:84], "little")
    data[80:84] = (n - 1).to_bytes(4, "little")
    del data[84 + 50 * (n - 1):]
    path.write_bytes(bytes(data))
    bad = stl_report(path)
    assert bad["boundary_edges"] == 3


def test_onboarding_checks_reject_wrong_answers(tmp_path):
    from cad.cli import main
    from cad.engine import Engine

    t = task("onboarding_plate")

    def project(d, body, export=True):
        d.mkdir()
        (d / "cad.toml").write_text('[project]\nname = "p"\nentry = "model.py"\n')
        (d / "model.py").write_text("from cad import Part\np = Part('plate')\n" + body)
        if export:
            e = Engine()
            assert main(["build"], d, e)[0] == 0
            assert main(["export", "--format", "stl"], d, e)[0] == 0
        return d

    good = project(tmp_path / "good", "p.box(60, 40, 4)\np.hole_pattern(4, spacing=(48, 28))\n")
    assert grade(t, good)["passed"]
    three = project(tmp_path / "three", "p.box(40, 60, 3)\np.holes(4, [(-14, -24), (14, -24), (0, 24)])\n")
    assert failed(grade(t, three)) == {"plate"}
    wrong = project(tmp_path / "wrong", "p.box(60, 50, 4)\np.hole_pattern(4, spacing=(48, 28))\n")
    assert "plate" in failed(grade(t, wrong))
    no_stl = project(tmp_path / "nostl", "p.box(60, 40, 4)\np.hole_pattern(4, spacing=(48, 28))\n", export=False)
    assert failed(grade(t, no_stl)) == {"stl_artifact"}
    # an STL exported from an earlier model state does not count
    stale = project(tmp_path / "stale", "p.box(60, 40, 4)\np.hole_pattern(4, spacing=(48, 28))\n")
    (stale / "model.py").write_text("from cad import Part\np = Part('plate')\np.box(60, 40, 6)\np.hole_pattern(4, spacing=(48, 28))\n")
    assert failed(grade(t, stale)) == {"stl_artifact"}

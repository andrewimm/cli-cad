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


def test_threemf_artifact_check(tmp_path):
    pytest.importorskip("lib3mf")
    from cad.cli import main
    from cad.engine import Engine

    t = task("multimaterial_coaster")
    src = (SOLUTION_DIR / "multimaterial_coaster" / "model.py").read_text()

    def project(name, text, fmt_args):
        d = tmp_path / name
        d.mkdir()
        (d / "cad.toml").write_text('[project]\nname = "c"\nentry = "model.py"\n')
        (d / "model.py").write_text(text)
        e = Engine()
        assert main(["build"], d, e)[0] == 0
        if fmt_args:
            assert main(["export", *fmt_args], d, e)[0] == 0
        return d

    # separate objects are laid out side by side (the insert's footprint is inside the coaster's), so the
    # insert no longer sits in its recess: not "printed in one go"
    assert failed(grade(t, project("objects", src, ["--format", "3mf"]))) == {"threemf_artifact"}
    assert grade(t, project("mm", src, ["--format", "3mf", "--3mf-mode", "multimaterial"]))["passed"]
    swapped = src.replace('material="PLA"', 'material="X"').replace('material="TPU"', 'material="PLA"').replace('material="X"', 'material="TPU"')
    assert failed(grade(t, project("swapped", swapped, ["--format", "3mf"]))) == {"threemf_artifact"}
    assert failed(grade(t, project("none", src, ["--format", "stl"]))) == {"threemf_artifact"}


def test_nameplate_text_check_rejects_wrong_text_placement(tmp_path):
    t = task("engraved_nameplate")
    src = (SOLUTION_DIR / "engraved_nameplate.py").read_text()
    assert grade(t, script(tmp_path, src, "ok.py"))["passed"]
    assert "python" in failed(grade(t, script(tmp_path, src.replace("at=(0, 4)", "at=(0, -4)"), "moved.py")))
    assert "python" in failed(grade(t, script(tmp_path, src.replace("depth=0.8", "depth=0.3"), "shallow.py")))
    swapped = src.replace('p.engrave("SN 0042"', 'p.emboss("SN 0042"').replace("depth=0.8", "height=0.8")
    assert failed(grade(t, script(tmp_path, swapped, "swapped.py")))  # raised instead of engraved


SERVO_SETUP = ROOT / "evals" / "setups" / "vendor_servo_mount"


def _servo_ws(tmp_path, name, old=None, new=None):
    d = tmp_path / name
    shutil.copytree(SERVO_SETUP, d)
    src = (SOLUTION_DIR / "vendor_servo_mount" / "model.py").read_text()
    if old:
        assert old in src
        src = src.replace(old, new)
    (d / "model.py").write_text(src)
    return d / "model.py"


def test_vendor_servo_mount_checks_reject_guessed_geometry(tmp_path):
    t = task("vendor_servo_mount")
    g = grade(t, _servo_ws(tmp_path, "ok"))
    assert failed(g) == {"sliced", "file"}  # geometry right; not sliced, no PRINT.md
    # holes placed symmetrically (a guess) instead of where the file puts them
    g = grade(t, _servo_ws(tmp_path, "guess", "[(-19.8, 0), (8.0, 0)]", "[(-13.9, 0), (13.9, 0)]"))
    assert "holes:mount" in failed(g)
    # plate 0.5 mm below the ears
    g = grade(t, _servo_ws(tmp_path, "low", "at=(-5.9, 0, -6.5))\n    mount.box(22.8", "at=(-5.9, 0, -7.0))\n    mount.box(22.8"))
    assert "python" in failed(g)
    # cutout with no clearance
    g = grade(t, _servo_ws(tmp_path, "tight", "mount.box(22.8 + 1, 12.2 + 1", "mount.box(22.8, 12.2"))
    assert "python" in failed(g)


def _clamp(tmp_path, name, old=None, new=None):
    d = tmp_path / name
    d.mkdir()
    src = (SOLUTION_DIR / "printed_pipe_clamp" / "model.py").read_text()
    if old:
        assert old in src, old
        src = src.replace(old, new)
    (d / "model.py").write_text(src)
    return d / "model.py"


def test_printed_pipe_clamp_checks_reject_wrong_fasteners(tmp_path):
    t = task("printed_pipe_clamp")
    assert failed(grade(t, _clamp(tmp_path, "ok"))) == {"sliced", "file"}
    for name, old, new in (
        ("round_nut", 'kind="nut")', 'kind="counterbore")'),                # round recess instead of a hex pocket
        ("m3_nut", 'bot.screw_hole("M4"', 'bot.screw_hole("M3"'),             # M3 nut pocket and hole
        ("no_cbore", 'kind="counterbore")\n    top', 'kind="clearance")\n    top'),
        ("no_chamfer", "    bot.bottom_chamfer(0.5)\n", ""),
    ):
        assert "python" in failed(grade(t, _clamp(tmp_path, name, old, new))), name


def test_lamp_arm_checks_catch_wrong_joint_directions(tmp_path):
    t = task("lamp_arm")
    src = (SOLUTION_DIR / "lamp_arm.py").read_text()
    assert grade(t, script(tmp_path, src, "ok.py"))["passed"]
    wrong_elbow = src.replace(', angle="elbow", direction="-y")', ', angle="elbow")')
    assert "param_rebuild" in failed(grade(t, script(tmp_path, wrong_elbow, "elbow.py")))
    wrong_yaw = src.replace('axis=((0, 0, 0), (0, 0, 1)), angle="yaw"', 'axis=((0, 0, 0), (0, 0, -1)), angle="yaw"')
    assert "param_rebuild" in failed(grade(t, script(tmp_path, wrong_yaw, "yaw.py")))


def test_towel_hook_checks_reject_sharp_elbow_and_wrong_rod(tmp_path):
    t = task("towel_hook")
    src = (SOLUTION_DIR / "towel_hook.py").read_text()
    assert grade(t, script(tmp_path, src, "ok.py"))["passed"]
    sharp = src.replace("radius=12)", "radius=0)")                       # mitred / sharp elbow
    assert "points_outside" in failed(grade(t, script(tmp_path, sharp, "sharp.py")))
    square = src.replace("Profile.circle(8)", "Profile.rect(8, 8)")      # square bar instead of round rod
    assert "python" in failed(grade(t, script(tmp_path, square, "square.py")))


@pytest.mark.skipif(bool(__import__("cad.fea", fromlist=["missing"]).missing()), reason="optional FEA packages not installed")
def test_strengthen_arm_checks_reject_weak_heavy_sharp_and_moved(tmp_path):
    t = task("strengthen_arm")

    def msgs(g):
        return " | ".join(c.get("message", "") for c in g["checks"] if not c["ok"])

    assert grade(t, mutated_dir(tmp_path / "ok", "strengthen_arm", "width", "width"))["passed"]
    sharp = grade(t, mutated_dir(tmp_path / "sharp", "strengthen_arm", 'arm.fillet(arm.edges().concave(), 3, name="root")', "pass"))
    assert "sharp inside edge" in msgs(sharp)                                     # strong but un-rounded corners
    weak = grade(t, mutated_dir(tmp_path / "weak", "strengthen_arm", 'Parameter("arm.width", 14.0)', 'Parameter("arm.width", 10.0)'))
    assert "pushrod: safety factor" in msgs(weak)                                 # rounded but too narrow
    heavy = grade(t, mutated_dir(tmp_path / "heavy", "strengthen_arm", 'Parameter("arm.thickness", 6.0)',
                                 'Parameter("arm.thickness", 8.0)'))
    assert "mass" in msgs(heavy)                                                  # strong by brute force
    moved = grade(t, mutated_dir(tmp_path / "moved", "strengthen_arm", 'Parameter("arm.length", 90)', 'Parameter("arm.length", 80)'))
    assert "holes" in failed(moved)                                               # shortened the arm: pin moved

"""Assemblies and joints: chains compose, axes from geometry, limits, warnings, engine integration."""
import json
import math

import pytest

from cad import Assembly, CadError, Parameter, Part, Profile
from cad.cli import main
from cad.runner import run_script

LEG = '''
from cad import Assembly, Parameter, Part, Profile

Parameter("hip_angle", 0, min=-30, max=60, unit="deg")
Parameter("knee_angle", 0, min=0, max=90, unit="deg")


def link(name, length, y0):
    prof = Profile.rect(16, length, center=(0, -length / 2)) + Profile.circle(16) + Profile.circle(16, center=(0, -length))
    p = Part(name)
    p.extrude(prof, -5, plane="XZ", offset=-y0)
    p.hole(6.2, at=(0, 0), direction="+y", name="top")
    p.hole(6.2, at=(0, -length), direction="+y", name="bottom")
    return p


def build():
    base = Part("base"); base.box(30, 5, 40, at=(0, -0.5, -10), align=("center", "max", "min"))
    base.hole(6.2, at=(0, 0), direction="+y", name="hip")
    upper = link("upper", 85, 0.0)
    lower = link("lower", 110, 5.5); lower.translate((0, 0, -85))
    asm = Assembly("leg")
    asm.add(base, upper, lower)
    asm.revolute("hip", base, upper, axis=base.faces("hip.wall"), angle="hip_angle")
    asm.revolute("knee", upper, lower, axis=upper.faces("bottom.wall"), angle="knee_angle")
    return asm
'''


def _foot(parts):
    """Centre of the lower link's bottom hole."""
    from cad import _occ
    f = parts["lower"].faces("bottom.wall").shapes[0]
    return _occ.cylinder_info(f)["axis_point"]


def test_chain_composes(tmp_path):
    (tmp_path / "leg.py").write_text(LEG)
    o = run_script(tmp_path / "leg.py", {"hip_angle": 30, "knee_angle": 45})
    x, _, z = _foot(o.parts)
    # foot = hip rotation(30) of [knee at (0, -85) + rotation(30 + 45) of (0, -110)], about +Y (+Z turns toward +X)
    a, b = math.radians(30), math.radians(75)
    want_x = -85 * math.sin(a) - 110 * math.sin(b)
    want_z = -85 * math.cos(a) - 110 * math.cos(b)
    assert x == pytest.approx(want_x, abs=1e-6) and z == pytest.approx(want_z, abs=1e-6)
    knee = next(j for j in o.joints if j["name"] == "knee")
    assert knee["axis_origin"] == pytest.approx([-85 * math.sin(a), 0, -85 * math.cos(a)], abs=1e-5)
    assert knee["moves"] == ["lower"] and "-X" in knee["positive_motion"]
    assert o.parts["base"].bbox.min[2] == pytest.approx(-10)          # ground part untouched
    assert {"bottom.wall", "top.wall"} <= set(o.parts["lower"].references())  # names survive the move


def test_slider_cylindrical_fixed_and_explicit_axis():
    rail = Part("rail"); rail.box(100, 10, 5, name="body")
    carriage = Part("carriage"); carriage.box(20, 14, 8, at=(0, 0, 5))
    knob = Part("knob"); knob.cylinder(6, 10, at=(0, 0, 13))
    asm = Assembly("slide")
    asm.add(rail, carriage, knob)
    asm.slider("x", rail, carriage, axis=((0, 0, 0), (1, 0, 0)), distance=25, limits=(-40, 40))
    asm.fixed("knob_mount", carriage, knob)
    parts = asm.solve()
    assert parts["carriage"].bbox.min[0] == pytest.approx(15) and parts["knob"].bbox.min[0] == pytest.approx(22)
    asm.joints[0].value = 50
    with pytest.raises(CadError) as e:
        asm.solve()
    assert e.value.code == "JOINT_LIMIT"
    pin = Part("pin"); pin.cylinder(6, 30)
    block = Part("block"); block.box(20, 20, 10); block.hole(6.2, at=(0, 0))
    a2 = Assembly(); a2.add(block, pin)
    a2.cylindrical("pin", block, pin, axis=block.faces("hole1.wall"), angle=90, distance=5)
    assert a2.solve()["pin"].bbox.min[2] == pytest.approx(5)


def test_errors_and_axis_warning():
    a, b, c = Part("a"), Part("b"), Part("c")
    for p in (a, b, c):
        p.box(10, 10, 10)
    asm = Assembly(); asm.add(a, b, c)
    asm.revolute("j1", a, b, axis=((0, 0, 0), (0, 0, 1)))
    with pytest.raises(CadError):
        asm.revolute("j2", c, b, axis=((0, 0, 0), (0, 0, 1)))          # second parent
    with pytest.raises(CadError):
        asm.revolute("j3", b, a, axis=((0, 0, 0), (0, 0, 1)))          # ground as child
    with pytest.raises(CadError):
        asm.revolute("j4", a, c, axis=((0, 0, 0), (0, 0, 1)), angle="no_such_param")
    rec = asm.describe()[0]
    assert rec["warnings"][0]["code"] == "JOINT_AXIS_OFF_GEOMETRY"


def test_cli_joints_set_and_sweep(tmp_path):
    main(["init"], tmp_path)
    (tmp_path / "model.py").write_text(LEG)
    assert main(["build"], tmp_path)[0] == 0
    r = json.loads(main(["joints", "--json"], tmp_path)[1])["result"]
    assert [j["name"] for j in r["joints"]] == ["hip", "knee"] and r["joints"][1]["limits"] == [0, 90]
    code, out, err = main(["set", "knee", "45", "--json"], tmp_path)
    assert code == 0 and json.loads(out)["result"]["overlay"] == {"knee_angle": 45}
    r = json.loads(main(["sweep", "knee", "0:90:45", "--min", "0.3", "--json"], tmp_path)[1])["result"]
    assert r["parameter"] == "knee_angle" and r["ok"] and len(r["results"]) == 3


def test_render_joint_overlay(tmp_path):
    main(["init"], tmp_path)
    (tmp_path / "model.py").write_text(LEG)
    main(["build"], tmp_path)
    plain = json.loads(main(["render", "--views", "front", "--json"], tmp_path)[1])["result"]["images"][0]["path"]
    over = json.loads(main(["render", "--views", "front", "--joints", "--json"], tmp_path)[1])["result"]["images"][0]["path"]
    from PIL import Image
    import numpy as np
    a, b = np.asarray(Image.open(plain)), np.asarray(Image.open(over))
    orange = (b[..., 0] > 200) & (b[..., 1] > 90) & (b[..., 1] < 150) & (b[..., 2] < 60)
    assert orange.sum() > 200 and (a != b).any()

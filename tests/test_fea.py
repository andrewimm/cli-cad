"""Stress analysis against textbook solutions, plus the agent-facing report and errors."""

import math

import numpy as np
import pytest

from cad import CadError, Material, Part, Study, fea
from cad.params import Parameter, parameter_overrides

pytestmark = pytest.mark.skipif(bool(fea.missing()), reason="optional FEA packages not installed")

STEEL_ISH = Material("test", density=1.0, youngs_modulus=10000, poisson_ratio=0.3, yield_strength=100)


def run(part, build, quality="normal"):
    s = Study("t", part)
    build(s)
    return fea.analyse(part, s.resolve(part.name), quality)[0]


def near(arrays, point, radius):
    return np.linalg.norm(arrays["vertices"] - np.asarray(point), axis=1) < radius


def test_cantilever_matches_beam_theory():
    p = Part("beam", material=STEEL_ISH)
    p.box(100, 10, 10, name="b")  # x -50..50
    sol = run(p, lambda s: (s.fixed("b.left"), s.force("b.right", 10, "-z")))
    r, a = sol.report, sol.arrays
    I = 10 * 10 ** 3 / 12
    E = 10000
    G = E / (2 * 1.3)
    tip = 10 * 100 ** 3 / (3 * E * I) + 10 * 100 / (5 / 6 * 100 * G)  # bending + shear
    load = next(ld for ld in r["loads"] if ld["type"] == "force")
    assert load["moves_mm"] == pytest.approx(tip, rel=0.03)  # along the load
    # bending stress at mid-span, top fibre: M c / I with M = 10 N * 50 mm
    v = a["vertices"]
    top = (np.abs(v[:, 0]) < 25) & (v[:, 2] > 10 - 1e-6) & (np.abs(v[:, 1]) < 4)  # away from the clamp and the load
    theory = 10 * (50 - v[top, 0]) * 5 / I  # M(x) c / I
    assert np.median(a["von_mises"][top] / theory) == pytest.approx(1, rel=0.04)
    fixed = next(ld for ld in r["loads"] if ld["type"] == "fixed")
    assert fixed["reaction_N"] == pytest.approx([0, 0, 10], abs=1e-6)  # equilibrium
    assert r["ok"] and r["safety_factor"] == pytest.approx(100 / r["max_von_mises_MPa"], rel=1e-3)


def test_plate_with_hole_concentration():
    """Heywood: Kt(net) = 2 + (1 - d/W)^3 for a hole in a strip under tension."""
    W, d, t, L = 60.0, 12.0, 3.0, 160.0
    p = Part("plate", material=STEEL_ISH)
    p.box(L, W, t, name="b")
    p.hole(d, at=(0, 0), name="h")
    F = 600.0
    sol = run(p, lambda s: (s.fixed("b.left"), s.force("b.right", F, "+x")))
    net = F / ((W - d) * t)
    kt = 2 + (1 - d / W) ** 3
    edge = near(sol.arrays, (0, d / 2, t / 2), 1.5) | near(sol.arrays, (0, -d / 2, t / 2), 1.5)
    assert sol.arrays["von_mises"][edge].max() == pytest.approx(kt * net, rel=0.08)
    h = sol.report["hotspots"][0]
    assert "h.wall" in [n for f in h["faces"] for n in f["names"]]
    assert abs(h["at"][0]) < 2 and abs(abs(h["at"][1]) - d / 2) < 1


def test_shaft_torsion():
    D, L, T = 10.0, 60.0, 1.0  # N*m
    p = Part("shaft", material=STEEL_ISH)
    p.cylinder(D, L, name="c")  # z 0..60
    sol = run(p, lambda s: (s.fixed("c.bottom"), s.torque("c.top", T, axis="z")))
    tau = 16 * T * 1000 / (math.pi * D ** 3)
    a = sol.arrays
    r = np.linalg.norm(a["vertices"][:, :2], axis=1)
    mid = (np.abs(a["vertices"][:, 2] - L / 2) < 6) & (r > D / 2 - 0.05)
    assert np.median(a["von_mises"][mid]) == pytest.approx(math.sqrt(3) * tau, rel=0.05)
    # twist at 3/4 of the length (away from the ends): theta = T x / (G J)
    G = 10000 / 2.6
    J = math.pi * D ** 4 / 32
    z = 0.75 * L
    ring = (np.abs(a["vertices"][:, 2] - z) < 2) & (r > D / 2 - 0.05)
    v, u = a["vertices"][ring], a["displacement"][ring]
    tangential = (v[:, 0] * u[:, 1] - v[:, 1] * u[:, 0]) / (np.linalg.norm(v[:, :2], axis=1) ** 2)
    assert np.mean(tangential) == pytest.approx(T * 1000 * z / (G * J), rel=0.05)
    fixed = next(ld for ld in sol.report["loads"] if ld["type"] == "fixed")
    assert fixed["reaction_N"] == pytest.approx([0, 0, 0], abs=0.05)  # a pure twist: no net force


def test_thick_tube_internal_pressure():
    """Lame: hoop stress at the bore = p (ro^2 + ri^2) / (ro^2 - ri^2)."""
    ri, ro, p_ = 10.0, 20.0, 5.0
    tube = Part("tube", material=STEEL_ISH)
    tube.cylinder(2 * ro, 120, name="c")
    tube.hole(2 * ri, at=(0, 0), name="bore")
    sol = run(tube, lambda s: (s.fixed("c.bottom"), s.pressure("bore.wall", p_)))
    hoop = p_ * (ro ** 2 + ri ** 2) / (ro ** 2 - ri ** 2)
    vm = math.sqrt(hoop ** 2 + p_ ** 2 + hoop * p_)  # sigma_r = -p, sigma_z = 0 (open ends)
    a = sol.arrays
    r = np.linalg.norm(a["vertices"][:, :2], axis=1)
    bore_mid = (np.abs(a["vertices"][:, 2] - 60) < 10) & (r < ri + 0.05)
    assert np.median(a["von_mises"][bore_mid]) == pytest.approx(vm, rel=0.06)


def test_bearing_and_gravity_balance_and_layers():
    arm = Part("arm", material="PLA")
    arm.box(60, 10, 6, name="b")
    arm.hole(5, at=(-25, 0), name="pivot")
    arm.hole(4, at=(25, 0), name="pin")
    sol = run(arm, lambda s: (s.fixed("pivot.wall"), s.bearing("pin.wall", 20, "-y"), s.gravity(10)))
    r = sol.report
    weight = arm.volume * 1.24e-3 * 9.81e-3 * 10
    fixed = next(ld for ld in r["loads"] if ld["type"] == "fixed")
    assert fixed["reaction_N"] == pytest.approx([0, 20, weight], rel=0.01, abs=0.1)  # within 0.5 % of the load
    b = next(ld for ld in r["loads"] if ld["type"] == "bearing")
    assert b["moves_mm"] < 0 or b["moves_mm"] > 0  # reported
    assert r["strength"]["build_direction"] == [0, 0, 1]
    assert r["material"]["layer_strength_MPa"] == 25
    assert any("100 % infill" in a for a in r["assumptions"])


def test_bearing_along_axis_is_rejected():
    arm = Part("arm", material="PLA")
    arm.box(60, 10, 6, name="b")
    arm.hole(4, at=(25, 0), name="pin")
    with pytest.raises(CadError) as e:
        run(arm, lambda s: (s.fixed("b.left"), s.bearing("pin.wall", 20, "-z")), quality="draft")
    assert "axis" in e.value.message


def test_underconstrained_names_free_motions():
    p = Part("block", material="PLA")
    p.box(20, 20, 10, name="b")
    with pytest.raises(CadError) as e:
        run(p, lambda s: (s.fixed("b.bottom", directions="z"), s.force("b.top", 5, "-z")), quality="draft")
    assert e.value.code == fea.UNDERCONSTRAINED
    assert set(e.value.details["free_motions"]) == {"slide along x", "slide along y", "turn about z"}
    with pytest.raises(CadError) as e:
        run(p, lambda s: s.force("b.top", 5, "-z"), quality="draft")
    assert e.value.code == fea.UNDERCONSTRAINED


def test_hotspot_names_the_fillet_and_parameter():
    with parameter_overrides({}) as ctx:
        r_fillet = Parameter("root_r", 1.0)
        thick = Parameter("thick", 4.0)
        p = Part("bracket", material="PETG")
        p.box(10, 12, 30, at=(0, 0, 0), name="post")
        p.box(50, 12, thick, at=(25, 0, 20), name="arm")
        p.fillet(p.edges().concave(), r_fillet, name="root")
        s = Study("load", p, target=3)
        s.fixed("post.bottom")
        s.force("arm.right", 4, "-z")
    assert ctx.studies == [s]
    spec = s.resolve("bracket")
    sol = fea.analyse(p, spec)[0]
    from cad.engine import _link_parameters

    _link_parameters(sol.report, p, {"root_r": {"value": 1.0}, "thick": {"value": 4.0}})
    h = sol.report["hotspots"][0]
    assert "root" in h["features"]
    assert {"parameter": "root_r", "value": 1.0, "feature": "root", "setting": "radius"} in h["parameters"]
    assert any("enlarge fillet 'root'" in t for t in h["suggestions"])


def test_missing_packages_message(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "gmsh" else real(name, *a))
    assert fea.missing() == ["gmsh"]
    with pytest.raises(CadError) as e:
        fea.require()
    assert e.value.code == fea.FEA_UNAVAILABLE
    assert "gmsh" in e.value.hint and "install" in e.value.hint and "GPL" in e.value.hint


def test_study_errors():
    p = Part("x", material="PLA")
    p.box(10, 10, 10, name="b")
    with pytest.raises(CadError):
        Study("bad name", p)
    s = Study("ok", p)
    with pytest.raises(CadError):
        s.fixed("b.nope")
    with pytest.raises(CadError):
        s.fixed("b.bottom", directions="w")
    s.force("b.top", 1, "-z")
    p.fillet(p.edges(), 1)  # replaces b.top: the study re-resolves the name
    spec = s.resolve("x")
    assert spec["loads"][0]["face_indices"]


# --------------------------------------------------------------------------- CLI / engine


def _cli(args, cwd, engine=None):
    import json

    from cad.cli import main

    code, out, err = main(args + ["--json"], cwd, engine)
    return code, json.loads(out)


@pytest.fixture
def servo_arm(tmp_path):
    from cad.cli import main

    code, _, err = main(["examples", "copy", "servo_arm", "arm"], tmp_path)
    assert code == 0, err
    return tmp_path / "arm"


def test_cli_fea_report_render_and_cache(servo_arm):
    from PIL import Image

    from cad.engine import Engine

    e = Engine()
    assert _cli(["build"], servo_arm, e)[0] == 0
    c, r = _cli(["fea", "--list"], servo_arm, e)
    assert c == 0 and [s["name"] for s in r["result"]["studies"]] == ["payload", "pushrod"]
    c, r = _cli(["fea", "pushrod", "-q", "draft"], servo_arm, e)
    st = r["result"]["studies"][0]
    assert st["study"] == "pushrod" and not st["cached"]
    assert c == (0 if st["ok"] else 4)
    h = st["hotspots"][0]
    assert "root" in h["features"]
    assert {"parameter": "arm.root_fillet", "value": 2.0, "feature": "root", "setting": "radius"} in h["parameters"]
    c, r = _cli(["fea", "pushrod", "-q", "draft"], servo_arm, e)
    assert r["result"]["studies"][0]["cached"]
    c, r = _cli(["render", "--fea", "pushrod", "--quality", "draft", "--views", "top", "--deformed", "--no-sheet"], servo_arm, e)
    assert c == 0
    img = r["result"]["images"][0]
    assert img["path"].endswith("arm_top_fea_pushrod_stress_deformed.png")
    px = np.asarray(Image.open(img["path"]).convert("RGB")).astype(int)
    reds = int(((px[..., 0] > 180) & (px[..., 1] < 90) & (px[..., 2] < 70)).sum())
    assert reds > 50  # the hot spot is drawn in the warm end of the colour scale
    import json

    meta = json.loads(open(img["metadata"]).read())
    assert meta["fea"]["study"] == "pushrod" and meta["fea"]["hotspots"][0]["id"] == 1


def test_cli_sweep_with_fea(servo_arm):
    from cad.engine import Engine

    e = Engine()
    _cli(["build"], servo_arm, e)
    c, r = _cli(["sweep", "arm.width", "8,16", "--fea", "pushrod"], servo_arm, e)
    assert c == 0
    rows = r["result"]["results"]
    assert rows[0]["fea"]["safety_factor"] < rows[1]["fea"]["safety_factor"]  # wider is stronger
    assert rows[0]["fea"]["mass_g"] < rows[1]["fea"]["mass_g"]
    assert r["result"]["fea"]["lightest_passing"]["value"] == 16
    assert r["result"]["head"] == 1


def test_cli_fea_sharp_corner_and_errors(tmp_path):
    from cad.engine import Engine

    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "cad.toml").write_text('[project]\nname = "p"\nentry = "model.py"\n')
    (proj / "model.py").write_text(
        "from cad import Part, Study\n"
        "p = Part('L', material='PETG')\n"
        "p.box(10, 12, 40, name='post')\n"
        "p.box(50, 12, 5, at=(25, 0, 20), name='arm')\n"
        "s = Study('load', p)\n"
        "s.fixed('post.bottom')\n"
        "s.force('arm.right', 10, '-z')\n")
    e = Engine()
    assert _cli(["build"], proj, e)[0] == 0
    c, r = _cli(["fea", "-q", "draft"], proj, e)
    st = r["result"]["studies"][0]
    codes = [w["code"] for w in st["warnings"]]
    assert "STRESS_SINGULARITY" in codes
    w = next(w for w in st["warnings"] if w["code"] == "STRESS_SINGULARITY")
    assert "L.fillet(L.edges().concave().nearest((5, 0, 2" in w["hint"]
    assert st["away_from_supports_and_sharp_edges"]["max_von_mises_MPa"] < st["max_von_mises_MPa"]
    c, r = _cli(["fea", "nope"], proj, e)
    assert c == 5 and r["error"]["code"] == "NOT_FOUND"


def test_cli_fea_missing_packages(servo_arm, monkeypatch):
    import importlib.util

    from cad.engine import Engine

    e = Engine()
    _cli(["build"], servo_arm, e)
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name in ("gmsh", "pyamg") else real(name, *a))
    c, r = _cli(["fea"], servo_arm, e)
    assert c != 0 and r["error"]["code"] == "FEA_UNAVAILABLE"
    assert r["error"]["details"]["missing"] == ["gmsh", "pyamg"]
    assert "gmsh pyamg" in r["error"]["hint"]
    c, r = _cli(["capabilities"], servo_arm)
    assert r["result"]["stress_analysis"]["available"] is False

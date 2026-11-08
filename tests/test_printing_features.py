"""3D-printing features: screw holes (fastener table), bottom chamfer, snap hooks, threads."""
import pytest

from cad import CadError, Part, Profile
from cad.fasteners import TABLE


def plate(t=8):
    p = Part("plate", material="PETG"); p.box(60, 30, t, name="body"); return p


@pytest.mark.parametrize("kind", ["clearance", "counterbore", "countersunk", "tap", "insert", "nut"])
def test_screw_hole_kinds_use_table_dimensions(kind):
    p = plate()
    f = p.screw_hole("M3", at=(0, 0), kind=kind)
    m = f.feature.metrics["fastener"]
    assert p.is_valid() and p.solid_count == 1 and not f.warnings
    holes = p.find_holes()
    want = {"clearance": 3.4, "counterbore": 3.4, "countersunk": 3.4, "tap": 2.5, "insert": 4.0, "nut": 3.4}[kind]
    assert m["hole_diameter"] == want and any(abs(h["diameter"] - want) < 1e-6 for h in holes)
    if kind == "counterbore":
        assert m["counterbore"] == {"diameter": 6.5, "depth": 3.2} and m["material_grip"] == pytest.approx(4.8)
    if kind == "insert":
        assert m["depth"] == pytest.approx(6.2) and p.volume < 60 * 30 * 8
    if kind == "nut":
        assert m["nut_pocket"]["across_flats"] == pytest.approx(5.8) and m["screw_length"] == 8
        assert "screw_hole1.nut" in p.references()


def test_screw_hole_batch_errors_and_warnings():
    p = plate()
    p.screw_hole("M4", at=[(-20, 0), (20, 0)], kind="countersunk")
    assert len(p.find_holes()) == 2
    with pytest.raises(CadError):
        p.screw_hole("M7", at=(0, 0))
    with pytest.raises(CadError):
        p.screw_hole("M3", at=(0, 0), kind="rivet")
    thin = plate(6)
    f = thin.screw_hole("M3", at=(0, 0), kind="insert")
    assert [w.code for w in f.warnings] == ["INSERT_TOO_DEEP"]
    assert set(TABLE) >= {"M2", "M3", "M4", "M5", "M6", "M8"}


def test_bottom_chamfer_outline_and_holes():
    p = plate(5); p.fillet(p.edges().vertical(), 3); p.hole(6, at=(0, 0))
    v0 = p.volume
    f = p.bottom_chamfer(0.5)
    assert p.is_valid() and f.feature.selections[0]["count"] == 9  # 4 lines, 4 corner arcs, 1 hole
    assert v0 - p.volume > 0
    q = plate(5); q.hole(6, at=(0, 0)); q.bottom_chamfer(0.4, holes=False)
    assert q.find_holes()[0]["diameter"] == pytest.approx(6.0)
    r = Part("upside"); r.sphere(20)
    with pytest.raises(CadError):
        r.bottom_chamfer(0.4)


def test_snap_hook_geometry_strain_and_warnings():
    lid = Part("lid", material="PETG"); lid.box(40, 30, 2, name="plate")
    f = lid.snap_hook(on=lid.faces("plate.front"), length=8, thickness=1.4, width=6, catch=0.8, hook="+z")
    s = f.feature.metrics["snap"]
    assert lid.is_valid() and lid.solid_count == 1
    assert s["strain"] == pytest.approx(1.5 * 1.4 * 0.8 / 64) and s["ok"] and not f.warnings
    assert {"snap_hook1.catch", "snap_hook1.lead_in"} <= set(lid.references())
    # the catch face is the flat that holds: perpendicular to the beam, 8 mm out from the root face
    catch = lid.faces("snap_hook1.catch").shapes
    from cad import _occ
    assert len(catch) == 1 and _occ.face_centroid(catch[0])[1] == pytest.approx(-15 - 8, abs=1e-6)
    stiff = Part("s", material="PLA"); stiff.box(40, 30, 2, name="plate")
    g = stiff.snap_hook(on=stiff.faces("plate.top"), length=5, thickness=2, width=5, catch=1.2)
    assert {w.code for w in g.warnings} == {"SNAP_STRAIN_HIGH"}
    assert g.feature.metrics["snap"]["allowable_strain_pct"] == 1.0  # PLA 2 %, halved: printed upright
    assert g.feature.metrics["snap"]["min_length_for_material"] > 5
    ok = Part("o", material="PETG"); ok.box(40, 30, 2, name="plate")
    k = ok.snap_hook(on=ok.faces("plate.top"), length=12, thickness=1.2, width=5, catch=0.8)
    assert [w.code for w in k.warnings] == ["SNAP_LAYER_ORIENTATION"]


def test_external_and_internal_threads_mesh():
    bolt = Part("bolt"); bolt.cylinder(14, 6); t = bolt.thread("M8", length=16, at=(0, 0, 6))
    assert bolt.is_valid() and bolt.solid_count == 1 and not t.warnings
    assert bolt.bbox.max[2] == pytest.approx(22) and bolt.bbox.max[0] == pytest.approx(7)
    nut = Part("nut"); nut.extrude(Profile.regular_polygon(6, across_flats=13), 6.5, offset=10)
    h = nut.threaded_hole("M8", at=(0, 0), clearance=0.2)
    assert nut.is_valid() and nut.solid_count == 1 and h.feature.metrics["thread"]["bore_d"] == pytest.approx(6.6469 + 0.4, abs=1e-3)
    # somewhere within one pitch the nut sits with play (radial clearance 0.2 -> ~0.1 on the 30-degree flanks),
    # half a pitch on it collides
    P = 1.25
    gaps = []
    for k in range(16):
        n2 = nut.copy("n"); n2.translate((0, 0, k * P / 16))
        gaps.append(bolt.distance_to(n2))
    best = max(range(16), key=lambda k: gaps[k])
    assert 0.06 < gaps[best] < 0.11
    n3 = nut.copy("n3"); n3.translate((0, 0, best * P / 16 + P / 2))
    assert bolt.interference(n3) > 1.0


def test_thread_warnings_and_parsing():
    from cad.threads import parse

    assert parse("M8") == (8.0, 1.25) and parse("M8x1") == (8.0, 1.0) and parse("M40x3") == (40.0, 3.0)
    with pytest.raises(CadError):
        parse("M7")
    p = Part("p"); p.box(20, 20, 10)
    w = p.threaded_hole("M4", at=(0, 0, 5), direction="+x")
    assert {x.code for x in w.warnings} == {"THREAD_TOO_FINE", "THREAD_ORIENTATION"}


@pytest.mark.parametrize("size", ["M3", "M12", "M40x3"])
def test_threads_are_valid_across_sizes(size):
    """Regression: axial clearance made fine-pitch grooves wider than the pitch (invalid M4 holes)."""
    from cad import _occ
    from cad.part import _fuse_all
    from cad.threads import bolt_tools, hole_tools, parse

    d, p = parse(size)
    bore, grooves, _ = hole_tools(d, p, -1, 4 * p, 0.25)
    core, teeth = bolt_tools(d, p, 4 * p)
    assert _occ.is_valid(_fuse_all([bore] + grooves)) and _occ.is_valid(_fuse_all([core] + teeth))


def test_print_on_orients_exports_and_persists(tmp_path):
    import json

    from cad.cli import main
    from cad.threemf import orient_for_print

    lid = Part("lid"); lid.box(40, 30, 2, at=(0, 0, 25), name="plate"); lid.box(5, 5, 10, at=(0, 0, 15))
    lid.print_on(lid.faces("plate.top"))
    a = lid.as_printed()
    assert a.bbox.min[2] == pytest.approx(0) and a.bbox.max[2] == pytest.approx(12)
    # the plate (largest section) is now on the bed: area at z = 1 is the full 40 x 30
    from cad.analysis import cross_section
    assert cross_section(a.shape, "z", 1.0)["area"] == pytest.approx(1200)
    assert lid.bbox.min[2] == pytest.approx(15)  # the model itself keeps its pose
    other = Part("other"); other.box(10, 10, 10); other.print_on("+x")
    with pytest.raises(CadError):
        orient_for_print({"lid": lid, "other": other}, "multimaterial")
    main(["init"], tmp_path)
    (tmp_path / "model.py").write_text(
        "from cad import Part\n\ndef build():\n    p = Part('lid'); p.box(40, 30, 2, at=(0, 0, 25), name='plate'); p.box(5, 5, 10, at=(0, 0, 15))\n"
        "    p.print_on(p.faces('plate.top'))\n    return p\n")
    assert main(["build"], tmp_path)[0] == 0
    r = json.loads(main(["export", "--format", "stl,step", "--json"], tmp_path)[1])["result"]
    stl = next(f for f in r["files"] if f["format"] == "stl")
    assert stl.get("oriented_for_print")
    from cad.importer import describe
    assert describe(stl["path"])["bbox_min"][2] == pytest.approx(0, abs=1e-3)
    assert describe(next(f["path"] for f in r["files"] if f["format"] == "step"))["bbox_min"][2] == pytest.approx(15, abs=1e-3)


def test_bottom_chamfer_follows_print_on():
    from cad.analysis import cross_section

    top = Part("top"); top.box(50, 20, 15, at=(0, 0, 15), name="block")
    top.print_on(top.faces("block.top"))
    top.bottom_chamfer(0.5)
    assert cross_section(top.shape, "z", 29.95)["regions"][0]["size"][0] == pytest.approx(49.1, abs=0.01)
    assert cross_section(top.shape, "z", 15.05)["regions"][0]["size"][0] == pytest.approx(50)

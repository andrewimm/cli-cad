import math

import pytest

from cad import CadError, Part, Plane, Profile, approx


def test_box_alignment_and_named_faces():
    p = Part("b")
    p.box(60, 40, 4, name="base")
    bb = p.bbox
    assert bb.min == pytest.approx((-30, -20, 0))
    assert bb.size == pytest.approx((60, 40, 4))
    assert approx(p.volume, 60 * 40 * 4)
    assert set(p.references()) == {f"base.{n}" for n in ("top", "bottom", "front", "back", "left", "right")}
    top = p.faces("base.top").one()
    assert top.info()[0]["normal"] == [0, 0, 1]


def test_align_variants():
    p = Part("b")
    p.box(10, 10, 10, at=(0, 0, 0), align="min")
    assert p.bbox.min == pytest.approx((0, 0, 0))
    q = Part("c")
    q.box(10, 10, 10, align=("max", "center", "center"))
    assert q.bbox.max[0] == pytest.approx(0) and q.bbox.center[2] == pytest.approx(0)


def test_hole_pattern_positions_and_reference_tracking():
    p = Part("plate")
    p.box(60, 40, 4, name="base")
    h = p.hole_pattern(3.2, spacing=(48, 28), count=(2, 2))
    holes = p.find_holes()
    assert len(holes) == 4
    assert sorted((x["position"][0], x["position"][1]) for x in holes) == [(-24, -14), (-24, 14), (24, -14), (24, 14)]
    assert all(approx(x["diameter"], 3.2) and approx(x["depth"], 4, 1e-6) for x in holes)
    # base.top survives the cut (modified, not deleted)
    assert len(p.faces("base.top")) == 1
    assert len(h.faces("wall")) == 4
    assert approx(p.volume, 60 * 40 * 4 - 4 * math.pi * 1.6 ** 2 * 4, 1e-6)


def test_blind_hole_counterbore_countersink():
    p = Part("p")
    p.box(30, 30, 10)
    p.hole(4, at=(0, 0), depth=6, counterbore=(8, 2), name="cb")
    p.hole(3, at=(10, 10), countersink=(6, 90), name="cs")
    names = p.references()
    assert "cb.floor" in names and "cb.counterbore" in names and "cs.countersink" in names
    hs = {round(h["diameter"], 3): h for h in p.find_holes()}
    assert hs[4.0]["depth"] == pytest.approx(4)  # 6 mm drill depth minus the 2 mm counterbore
    assert hs[8.0]["depth"] == pytest.approx(2)
    p.assert_valid()


def test_side_hole_2d_position():
    p = Part("p")
    p.box(40, 10, 20)
    p.hole(5, at=(0, 10), direction="+y")
    (h,) = p.find_holes()
    assert h["axis"] == [0, 1, 0]
    assert h["position"][0] == pytest.approx(0) and h["position"][2] == pytest.approx(10)
    assert h["depth"] == pytest.approx(10)


def test_cut_no_effect_warning():
    p = Part("p")
    p.box(10, 10, 10)
    f = p.hole(2, at=(100, 100))
    assert [w.code for w in f.warnings] == ["CUT_NO_EFFECT"]


def test_disconnected_add_warning_and_assert_valid():
    p = Part("p")
    p.box(10, 10, 10)
    f = p.box(5, 5, 5, at=(50, 0, 0))
    assert any(w.code == "DISCONNECTED_BODIES" for w in f.warnings)
    with pytest.raises(CadError) as e:
        p.assert_valid()
    assert e.value.code == "VALIDATION_FAILED"


def test_fillet_vertical_edges(bracket):
    v0 = bracket.volume
    bracket.fillet(bracket.edges().vertical().convex().min("y"), radius=3)
    assert bracket.volume < v0
    assert "fillet1.faces" in bracket.references()
    bracket.assert_valid()


def test_fillet_too_large_is_structured(bracket):
    with pytest.raises(CadError) as e:
        bracket.fillet(bracket.edges().vertical().convex(), radius=50)
    assert e.value.code == "FILLET_FAILED"
    assert e.value.feature == "fillet1"
    assert e.value.hint
    # failed feature recorded, geometry unchanged
    assert bracket.features[-1].status == "failed"
    bracket.assert_valid()


def test_concave_selection(bracket):
    conc = bracket.edges().concave()
    assert len(conc) == 1
    assert conc.info()[0]["midpoint"] == pytest.approx([0, 16, 4])
    bracket.fillet(conc, 2)
    assert len(bracket.edges().concave()) == 0


def test_shell_open_top():
    p = Part("box")
    p.box(40, 30, 20, name="body")
    p.shell(2, open_faces=p.faces("body.top"))
    assert approx(p.volume, 40 * 30 * 20 - 36 * 26 * 18, 1e-3)
    assert "shell1.inner" in p.references()
    p.assert_valid()


def test_extrude_profiles_and_planes():
    p = Part("p")
    p.extrude(Profile.rounded_rect(40, 20, 5) - Profile.circle(8), 10)
    assert p.bbox.size == pytest.approx((40, 20, 10))
    q = Part("q")
    q.extrude(Profile.rect(10, 20), 5, plane="XZ")  # normal -Y
    assert q.bbox.min[1] == pytest.approx(-5) and q.bbox.max[1] == pytest.approx(0)
    assert q.bbox.size[2] == pytest.approx(20)
    r = Part("r")
    r.extrude(Profile.rect(10, 10), 6, plane="YZ", symmetric=True)
    assert r.bbox.min[0] == pytest.approx(-3)


def test_revolve_cylinder():
    p = Part("p")
    p.revolve(Profile.rect_corners((0, 0), (5, 10)))
    assert approx(p.volume, math.pi * 25 * 10, 1e-6)
    assert p.bbox.size == pytest.approx((10, 10, 10))


def test_reference_lost_reports_feature():
    p = Part("p")
    p.box(10, 10, 10, name="a")
    p.box(20, 20, 5, at=(0, 0, 8), op="cut", name="trim")  # removes the top face of a
    with pytest.raises(CadError) as e:
        p.faces("a.top")
    assert e.value.code == "REFERENCE_LOST"
    assert e.value.details["lost_in"] == "trim"


def test_unknown_reference_suggests():
    p = Part("p")
    p.box(10, 10, 10, name="base")
    with pytest.raises(CadError) as e:
        p.faces("base.tpo")
    assert e.value.code == "UNKNOWN_REFERENCE"
    assert "base.top" in e.value.hint


def test_ambiguous_selection():
    p = Part("p")
    p.box(10, 10, 10)
    with pytest.raises(CadError) as e:
        p.faces().planar().one()
    assert e.value.code == "AMBIGUOUS_SELECTION"
    assert len(e.value.details["candidates"]) == 6


def test_stale_selection_rejected():
    p = Part("p")
    p.box(10, 10, 10)
    old = p.edges().vertical()
    p.hole(2, at=(0, 0))
    p.fillet(old, 1)  # vertical edges were untouched by the hole: still valid
    with pytest.raises(CadError) as e:
        p.fillet(old, 0.5)  # those edges no longer exist after the fillet
    assert "stale" in e.value.message


def test_tag_survives_later_features():
    p = Part("p")
    p.box(30, 30, 5)
    p.tag("mount", p.faces().facing("-z"))
    p.hole_pattern(3, spacing=(20, 20))
    p.fillet(p.edges().vertical().convex(), 2)
    f = p.faces("mount").one()
    assert f.info()[0]["normal"] == [0, 0, -1]


def test_feature_graph_dependencies():
    p = Part("p")
    p.box(30, 30, 5, name="base")
    p.hole(3, at=(0, 0), name="h")
    p.fillet(p.edges().of(p.faces("base.top")).convex(), 0.5, name="edge_round")
    g = {f["id"]: f for f in p.feature_graph()["features"]}
    assert g["h"]["depends_on"] == ["base"]
    assert "base" in g["edge_round"]["depends_on"]
    assert g["edge_round"]["selections"][0]["selection"].startswith("edges().of(")


def test_transforms_and_mirror():
    p = Part("p")
    p.box(10, 10, 10, align="min")
    p.translate((5, 0, 0))
    assert p.bbox.min[0] == pytest.approx(5)
    p.mirror("YZ")
    assert p.bbox.min[0] == pytest.approx(-15) and p.solid_count == 2
    p.rotate(90, axis="z")
    assert p.bbox.size[1] == pytest.approx(30)


def test_union_cut_parts_and_distance():
    a = Part("a")
    a.box(10, 10, 10)
    b = Part("b")
    b.box(10, 10, 10, at=(20, 0, 0))
    assert a.distance_to(b) == pytest.approx(10)
    assert a.interference(b) == 0
    c = Part("c")
    c.box(10, 10, 10, at=(5, 0, 0))
    assert a.interference(c) == pytest.approx(500)
    a.cut(c)
    assert a.volume == pytest.approx(500)


def test_invalid_arguments():
    p = Part("p")
    with pytest.raises(CadError) as e:
        p.box(-1, 10, 10)
    assert e.value.code == "INVALID_ARGUMENT"
    with pytest.raises(CadError) as e:
        p.hole(3, at=(0, 0))
    assert e.value.code == "NO_BODY"
    with pytest.raises(CadError):
        Profile.rounded_rect(10, 10, 6)


def test_export_step_stl_roundtrip(tmp_path):
    from cad.export import read_brep
    from cad import _occ

    p = Part("p")
    p.box(10, 20, 30)
    p.hole(4, at=(0, 0))
    for ext in ("step", "stl", "brep"):
        path = p.export(str(tmp_path / f"p.{ext}"))
        assert (tmp_path / f"p.{ext}").stat().st_size > 100, path
    s = read_brep(tmp_path / "p.brep")
    assert _occ.volume(s) == pytest.approx(p.volume)
    from OCP.STEPControl import STEPControl_Reader

    r = STEPControl_Reader()
    r.ReadFile(str(tmp_path / "p.step"))
    r.TransferRoots()
    assert _occ.volume(r.OneShape()) == pytest.approx(p.volume, rel=1e-6)


def test_rehydrate_preserves_references(tmp_path):
    from cad.export import read_brep
    from cad.tessellate import brep_bytes

    p = Part("p")
    p.box(30, 30, 5, name="base")
    p.hole_pattern(3, spacing=(20, 20))
    (tmp_path / "p.brep").write_bytes(brep_bytes(p.shape))
    q = Part._rehydrate("p", read_brep(tmp_path / "p.brep"), refs=p._persisted_refs())
    assert q.references() == p.references()
    assert q.faces("base.top").info() == p.faces("base.top").info()


def test_extrude_through_cut():
    p = Part("p")
    p.box(50, 30, 3)
    p.extrude(Profile.rect(23.4, 12.8), 1, op="cut", through=True)
    assert p.volume == pytest.approx(50 * 30 * 3 - 23.4 * 12.8 * 3)


def test_profile_offset():
    r = Profile.rect(20, 10) - Profile.circle(4)
    assert r.offset(-1).area == pytest.approx(18 * 8 - math.pi * 9, rel=1e-6)
    assert Profile.rect(10, 10).offset(1).area == pytest.approx(144 - 4 + math.pi, rel=1e-6)


def test_selection_distance():
    a = Part("a"); a.box(10, 10, 10)
    b = Part("b"); b.box(10, 10, 10, at=(20, 0, 0))
    assert a.faces().facing("+x").distance_to(b) == pytest.approx(10)
    assert a.faces().facing("-x").distance_to(b.faces().facing("-x")) == pytest.approx(20)


def test_angled_hole_vector_direction():
    s, c = math.sin(math.radians(30)), math.cos(math.radians(30))
    m = Part("m"); m.box(40, 30, 25)
    m.hole(6, at=(-10 + 15 / c * s, 0, 25), direction=(-s, 0, -c), depth=15 / c)
    (h,) = m.find_holes()
    assert h["axis"] == pytest.approx([s, 0, c], abs=1e-6)


def test_2d_hole_starts_at_material_surface():
    # plate with a taller knuckle elsewhere: countersinks must land on the plate top (Z=2), not the bbox top (Z=6)
    h = Part("leaf")
    h.box(40, 30, 2)
    h.cylinder(6, 40, at=(-20, 15, 3), axis="x")
    f = h.holes(3.5, [(-12, -3), (0, -3)], countersink=(7, 90))
    assert not f.warnings
    assert "holes1.countersink" in h.references()
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_OUT

    # the countersink opening at the plate top is empty (radius ~3.4 at Z=1.95)
    assert BRepClass3d_SolidClassifier(h.shape, gp_Pnt(3.0, -3, 1.95), 1e-6).State() == TopAbs_OUT


def test_recess_no_effect_warning():
    p = Part("p")
    p.box(20, 20, 4)
    f = p.hole(3, at=(0, 0, 10), counterbore=(6, 2))  # 3D start 6 mm above the part
    assert any(w.code == "RECESS_NO_EFFECT" for w in f.warnings)


def test_regular_polygon_across_flats():
    hexa = Profile.regular_polygon(6, across_flats=8)
    p = Part("h"); p.extrude(hexa, 5)
    assert p.bbox.depth == pytest.approx(8) and p.bbox.width == pytest.approx(8 / math.cos(math.pi / 6))

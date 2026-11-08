"""Lofts, sweeps (paths) and drafts: exact volumes where they have closed forms, failure modes."""
import math

import pytest

from cad import CadError, Part, Path, Profile
from cad.analysis import cross_section


def test_ruled_loft_is_a_frustum():
    p = Part("frustum")
    p.loft([(Profile.rect(40, 40), 0), (Profile.rect(20, 20), 30)], ruled=True)
    # prismatoid: h/3 (A1 + A2 + sqrt(A1 A2))
    assert p.volume == pytest.approx(30 / 3 * (1600 + 400 + 800), rel=1e-6)
    assert {"loft1.start", "loft1.end", "loft1.side"} <= set(p.references())
    assert cross_section(p.shape, "z", 15)["regions"][0]["size"][0] == pytest.approx(30, abs=1e-6)


def test_loft_rect_to_circle_and_holes_and_planes():
    p = Part("duct"); p.loft([(Profile.rect(40, 20), 0), (Profile.circle(15), 30)])
    assert p.is_valid() and p.bbox.max[2] == pytest.approx(30)
    h = Part("hollow"); h.loft([(Profile.circle(30) - Profile.circle(20), 0), (Profile.circle(20) - Profile.circle(12), 25)], ruled=True)
    outer = math.pi * 25 / 3 * (15 ** 2 + 10 ** 2 + 15 * 10)
    inner = math.pi * 25 / 3 * (10 ** 2 + 6 ** 2 + 10 * 6)
    assert h.volume == pytest.approx(outer - inner, rel=1e-5)
    side = Part("side"); side.loft([(Profile.rect(10, 10), "YZ"), (Profile.circle(6), as_yz(40))])
    assert side.bbox.max[0] == pytest.approx(40)
    with pytest.raises(CadError):
        Part("x").loft([(Profile.rect(10, 10), 0)])
    with pytest.raises(CadError) as e:
        Part("x").loft([(Profile.circle(20) - Profile.circle(5), 0), (Profile.circle(20), 10)])
    assert e.value.code == "LOFT_FAILED"


def as_yz(x):
    from cad.profile import as_plane
    return as_plane("YZ").offset(x)


def test_sweep_tube_and_spring_volumes():
    t = Part("tube")
    f = t.sweep(Profile.circle(10) - Profile.circle(7), Path.polyline([(0, 0, 0), (0, 0, 50), (40, 0, 50)], radius=15))
    centreline = (50 - 15) + (40 - 15) + math.pi / 2 * 15
    assert t.volume == pytest.approx(math.pi * (5 ** 2 - 3.5 ** 2) * centreline, rel=1e-5)
    assert f.feature.metrics["sweep"]["profile_radius"] == pytest.approx(5)
    assert {"sweep1.start", "sweep1.end", "sweep1.side"} <= set(t.references())
    s = Part("spring"); s.sweep(Profile.circle(2), Path.helix(radius=10, pitch=5, height=20))
    assert s.volume == pytest.approx(math.pi * 1 * Path.helix(radius=10, pitch=5, height=20).length, rel=1e-4)
    a = Part("ring"); a.sweep(Profile.rect(3, 3), Path.arc((10, 0, 0), (0, 10, 0), (-10, 0, 0)))
    assert a.volume == pytest.approx(9 * math.pi * 10, rel=1e-5)
    sp = Part("handle"); sp.sweep(Profile.ellipse(12, 8), Path.spline([(0, 0, 0), (20, 0, 25), (40, 0, 0)]))
    assert sp.is_valid() and sp.solid_count == 1


def test_sweep_rejects_bends_tighter_than_the_profile():
    with pytest.raises(CadError) as e:
        Part("bad").sweep(Profile.circle(20), Path.polyline([(0, 0, 0), (0, 0, 50), (40, 0, 50)], radius=5))
    assert e.value.code == "SWEEP_FAILED" and "10" in e.value.message
    with pytest.raises(CadError):
        Path.polyline([(0, 0, 0), (0, 0, 10), (5, 0, 10)], radius=20)   # radius does not fit the corner


def test_draft_tapers_walls_from_the_bottom():
    b = Part("box"); b.box(40, 30, 20); b.hole(10, at=(0, 0))
    f = b.draft(2)
    taper = 2 * 20 * math.tan(math.radians(2))
    top = cross_section(b.shape, "z", 20 - 1e-6)["regions"][0]
    assert top["size"][0] == pytest.approx(40 - taper, abs=1e-3) and b.bbox.size[0] == pytest.approx(40, abs=1e-6)
    assert f.feature.metrics["draft"]["faces"] == 5 and b.is_valid()
    with pytest.raises(CadError):
        b.draft(60)

"""Regression tests for defects found by the geometry stress suites (stress/)."""
import math
import sys
from pathlib import Path

import pytest

from cad import CadError, Part, _occ

ROOT = Path(__file__).resolve().parents[1]


def test_volume_accurate_on_trimmed_sphere():  # S01: default integration was off by 0.35 mm3
    a = Part("A"); a.box(46.0, 44.0, 41.9, align="center")
    b = Part("B"); b.sphere(25.53, at=(19.0, -4.0, 3.0))
    u, i, c = a.copy(), a.copy(), a.copy()
    u.union(b); i.intersect(b); c.cut(b)
    assert abs(u.volume + i.volume - a.volume - b.volume) < 1e-6 * (a.volume + b.volume)
    assert abs(c.volume - (a.volume - i.volume)) < 1e-6 * a.volume
    assert b.volume == pytest.approx(math.pi / 6 * 25.53 ** 3, rel=1e-9)


def test_union_box_sphere_stays_valid():  # S01: face merging after fuse produced an invalid solid
    a = Part("A"); a.box(15.764, 10.736, 41.433, align="center")
    b = Part("B"); b.sphere(8.513, at=(4.401, -0.144, 0.697))
    a.union(b)
    assert a.is_valid() and a.solid_count == 1


def test_fillet_never_changes_solid_count():  # S02: star-profile fillet returned 2 solids
    from cad import Profile

    pts = []
    for k in range(10):
        r = 30.0 if k % 2 == 0 else 30.0 * 0.45
        pts.append((r * math.cos(math.pi * k / 5), r * math.sin(math.pi * k / 5)))
    p = Part("star"); p.extrude(Profile.polygon(pts), 10)
    v = p.volume
    try:
        p.fillet(p.edges().vertical(), 5.0)
        assert p.solid_count == 1 and p.is_valid()
    except CadError as e:
        assert e.code == "FILLET_FAILED" and e.hint
        assert p.volume == pytest.approx(v)


def test_operation_cannot_silently_remove_the_body():  # S02: a fillet left zero solids and was accepted
    p = Part("p"); p.box(10, 10, 10)
    with pytest.raises(CadError):
        p.fillet(p.edges(), 5.0)
    assert p.solid_count == 1


def test_batch_positions_one_boolean():  # S04: 1000 bosses timed out when added one at a time
    p = Part("p"); p.box(70, 70, 4)
    pts = [(-30 + i * 6, -30 + j * 6, 4) for j in range(11) for i in range(11)]
    f = p.cylinder(3, 5, at=pts)
    assert p.solid_count == 1 and len(p.faces(f"{f.id}.side")) == len(pts)
    assert p.volume == pytest.approx(70 * 70 * 4 + len(pts) * math.pi * 1.5 ** 2 * 5, rel=1e-9)
    q = Part("q"); q.box(40, 20, 2); q.box(1, 18, 5, at=[(x, 0, 2) for x in (-10, 0, 10)], align=("center", "center", "min"))
    assert q.volume == pytest.approx(40 * 20 * 2 + 3 * 18 * 5)


def test_phase_timings_recorded():
    p = Part("p"); p.box(40, 40, 4)
    f = p.hole_pattern(3, spacing=(10, 10), count=(3, 3))
    assert {"tools", "boolean", "validate", "references"} <= set(f.feature.phases_ms)


def test_shape_list_matches_iteration():  # S04: iterating OCP lists cost 2.8 ms per call
    from OCP.collections import List_TopoDS_Shape

    p = Part("p"); p.box(1, 2, 3)
    fs = _occ.faces(p.shape)
    lst = List_TopoDS_Shape()
    for f in fs:
        lst.Append(f)
    out = _occ.shape_list(lst)
    assert len(out) == 6 and all(a.IsSame(b) for a, b in zip(out, fs)) and lst.Size() == 6


def test_body_split_warning():  # S05: merged holes severed the plate silently
    p = Part("p"); p.box(40, 12, 4)
    f = p.holes(4, [(0, y) for y in (-6, -3, 0, 3, 6)])  # a row of merged holes across the full width
    assert p.solid_count > 1
    assert any(w.code == "BODY_SPLIT" for w in f.warnings)


def test_stress_harness_isolates_crashes_and_timeouts():
    sys.path.insert(0, str(ROOT / "stress"))
    from cadstress.harness import run_cases

    out = run_cases([{"id": "ok", "code": "result={'x':1}"},
                     {"id": "segv", "code": "import ctypes; ctypes.string_at(0)"},
                     {"id": "hang", "code": "while True: pass", "timeout_s": 2},
                     {"id": "after", "code": "result={'y':2}"}], workers=2, timeout_s=2)
    assert out["ok"]["status"] == "ran" and out["after"]["status"] == "ran"
    assert out["segv"]["status"] == "crash" and out["hang"]["status"] == "timeout"

"""Rigid shaft coupler: revolved body with two bores and radial set-screw holes.

Demonstrates: revolve of a stepped profile on the XZ plane, holes along an
axis with explicit 3D start points, holes() verification.
"""
from cad import Parameter, Part, Profile

od = Parameter("outer_diameter", 20, min=8, max=80)
length = Parameter("length", 30, min=10, max=120)
bore_a = Parameter("bore_a", 5, min=2, max=40)
bore_b = Parameter("bore_b", 8, min=2, max=40)


def build():
    c = Part("coupler")
    # half-profile in the XZ plane (u = radius along X, v = height along Z), revolved about Z
    c.revolve(Profile.rect_corners((0, 0), (od / 2, length)), name="body")
    c.hole(bore_a, at=(0, 0, length), depth=length / 2, direction="-z", name="bore_a")
    c.hole(bore_b, at=(0, 0, 0), depth=length / 2, direction="+z", name="bore_b")
    # M3 set screws: radial, drilled from +X toward the axis, one per half
    for i, z in enumerate((length * 0.25, length * 0.75)):
        c.hole(2.5, at=(od / 2, 0, z), depth=od / 2, direction="-x", name=f"set_screw{i + 1}")
    c.chamfer(c.edges().circular(radius=od / 2), 0.8)
    c.assert_valid()
    diams = sorted(h["diameter"] for h in c.holes())
    assert diams[-2:] == [bore_a, bore_b] or sorted([bore_a, bore_b]) == diams[-2:], diams
    return c

"""Helical ISO metric threads (60-degree flanks) for printed bolts and threaded holes.

The thread tooth is lofted (ruled) between two helical bands drawn on coaxial
cylinders, the construction of OCCT's bottle tutorial.  It is built one turn at a
time: booleans that trim a multi-turn helical surface with a plane produce invalid
solids (found while building this), while one-turn pieces trim and fuse cleanly.

Profile (simplified ISO 68-1): tooth depth 0.6134 P from the bolt's minor radius to
its major radius, crest flat P/8, flanks at 30 degrees from the radial direction.
A threaded hole cuts the bolt's tooth shape shifted outward radially by
``clearance`` (bore and groove both grow by it), so a printed or metal bolt of the
same size turns in it; the 30-degree flanks get about half the clearance as play.
(Widening the groove axially instead makes it wider than the pitch on fine threads,
so successive turns overlap and the solid is invalid: found with M4.)
"""

from __future__ import annotations

import math
import re

from .errors import INVALID_ARGUMENT, CadError

COARSE_PITCH = {2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 14: 2.0,
                16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0, 27: 3.0, 30: 3.5, 33: 3.5, 36: 4.0, 42: 4.5, 48: 5.0}
DEPTH = 0.6134          # tooth depth / pitch (external thread, ISO 17/24 H)
TAN30 = math.tan(math.radians(30))


def parse(size: str, pitch: float | None = None) -> tuple[float, float]:
    """("M8" | "M8x1" | "M40x3", pitch override) -> (major diameter, pitch)."""
    m = re.fullmatch(r"\s*[mM]?\s*(\d+(?:\.\d+)?)\s*(?:[xX×]\s*(\d+(?:\.\d+)?))?\s*", str(size))
    if not m:
        raise CadError(INVALID_ARGUMENT, f"thread size {size!r} not understood", hint='e.g. "M8", "M8x1" (fine pitch), "M40x3"')
    d = float(m.group(1))
    p = pitch or (float(m.group(2)) if m.group(2) else COARSE_PITCH.get(d if d != int(d) else int(d)))
    if p is None:
        raise CadError(INVALID_ARGUMENT, f"no standard coarse pitch for M{d:g}", hint=f'give it: "M{d:g}x<pitch>"')
    if not 0 < p < d / 2:
        raise CadError(INVALID_ARGUMENT, f"pitch {p} does not suit a {d:g} mm thread")
    return d, p


def _band(r: float, w: float, pitch: float, u0: float, u1: float):
    """Closed wire on the cylinder of radius r: a helical band of axial width w between angles u0, u1."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepLib import BRepLib
    from OCP.GC import GC_MakeSegment2d
    from OCP.Geom import Geom_CylindricalSurface
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Pnt2d

    surf = Geom_CylindricalSurface(gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), r)
    k = pitch / (2 * math.pi)
    pts = [gp_Pnt2d(u0, u0 * k - w / 2), gp_Pnt2d(u1, u1 * k - w / 2), gp_Pnt2d(u1, u1 * k + w / 2), gp_Pnt2d(u0, u0 * k + w / 2)]
    mw = BRepBuilderAPI_MakeWire()
    for a, b in zip(pts, pts[1:] + pts[:1]):
        mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeSegment2d(a, b).Value(), surf).Edge())
    wire = mw.Wire()
    BRepLib.BuildCurves3d_s(wire)
    return wire


def tooth_pieces(r_in: float, r_out: float, w_in: float, w_out: float, pitch: float, z0: float, z1: float) -> list:
    """One-turn tooth solids along +Z (local frame) covering z0..z1, trimmed flat at both ends."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt, gp_Trsf, gp_Vec

    from . import _occ

    start = z0 - pitch  # begin a turn early so the trimmed start is full depth
    turns = math.ceil((z1 - start) / pitch) + 1
    big = 4 * r_out + 10
    below = BRepPrimAPI_MakeBox(gp_Pnt(-big / 2, -big / 2, z0 - 3 * pitch), big, big, 3 * pitch).Shape()
    above = BRepPrimAPI_MakeBox(gp_Pnt(-big / 2, -big / 2, z1), big, big, 3 * pitch).Shape()
    shift = gp_Trsf()
    shift.SetTranslation(gp_Vec(0, 0, start))
    out = []
    for i in range(turns):
        u0, u1 = 2 * math.pi * i, 2 * math.pi * (i + 1)
        ts = BRepOffsetAPI_ThruSections(True, True)
        ts.AddWire(_band(r_in, w_in, pitch, u0, u1))
        ts.AddWire(_band(r_out, w_out, pitch, u0, u1))
        ts.Build()
        piece = BRepBuilderAPI_Transform(ts.Shape(), shift, True).Shape()
        lo, hi = _occ.bbox(piece)
        if hi[2] <= z0 + 1e-9 or lo[2] >= z1 - 1e-9:
            continue
        if lo[2] < z0:
            piece = BRepAlgoAPI_Cut(piece, below).Shape()
        if hi[2] > z1:
            piece = BRepAlgoAPI_Cut(piece, above).Shape()
        if _occ.solids(piece):
            out.append(piece)
    return out


def external_profile(d: float, pitch: float) -> dict:
    h = DEPTH * pitch
    r_maj = d / 2
    r_min = r_maj - h
    w_crest = pitch / 8
    return {"major_d": d, "minor_d": round(2 * r_min, 4), "pitch": pitch, "depth": round(h, 4), "crest": w_crest,
            "root": w_crest + 2 * h * TAN30}


def bolt_tools(d: float, pitch: float, length: float, eps: float = 0.05) -> tuple:
    """(core cylinder, tooth pieces) for an external thread along +Z from 0 to length."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    pr = external_profile(d, pitch)
    r_min, r_maj = pr["minor_d"] / 2, d / 2
    core = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), r_min, length).Shape()
    teeth = tooth_pieces(r_min - eps, r_maj, pr["root"] + 2 * eps * TAN30, pr["crest"], pitch, 0.0, length)
    return core, teeth


def hole_tools(d: float, pitch: float, z0: float, z1: float, clearance: float, eps: float = 0.05) -> tuple:
    """(bore cylinder, groove pieces) to cut an internal thread along +Z between z0 and z1."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    pr = external_profile(d, pitch)
    nut_minor = d - 1.0825 * pitch            # ISO D1
    r_bore = nut_minor / 2 + clearance
    r_out = d / 2 + clearance
    # groove = the bolt's tooth moved out radially by the clearance; its inner band sits inside the bore
    r_in = r_bore - eps
    w_in = pr["crest"] + 2 * (r_out - r_in) * TAN30   # = 0.75 P + small: always narrower than the pitch
    w_out = pr["crest"]
    bore = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, z0), gp_Dir(0, 0, 1)), r_bore, z1 - z0).Shape()
    grooves = tooth_pieces(r_in, r_out, w_in, w_out, pitch, z0, z1)
    return bore, grooves, {"bore_d": round(2 * r_bore, 4), "nut_minor_d": round(nut_minor, 4)}

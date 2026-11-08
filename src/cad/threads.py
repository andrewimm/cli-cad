"""Helical ISO metric threads (60-degree flanks) for printed bolts and threaded holes.

The thread tooth is a trapezoid swept along a helix, its plane kept radial, as one
continuous solid (see tooth_pieces for why not lofted one-turn pieces).

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


def _helix(r: float, pitch: float, height: float, z0: float):
    """Wire: a right-hand helix of radius r from (r, 0, z0), rising ``height``."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepLib import BRepLib
    from OCP.GC import GC_MakeSegment2d
    from OCP.Geom import Geom_CylindricalSurface
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Pnt2d

    surf = Geom_CylindricalSurface(gp_Ax3(gp_Pnt(0, 0, z0), gp_Dir(0, 0, 1)), r)
    seg = GC_MakeSegment2d(gp_Pnt2d(0, 0), gp_Pnt2d(2 * math.pi * height / pitch, height)).Value()
    edge = BRepBuilderAPI_MakeEdge(seg, surf).Edge()
    BRepLib.BuildCurves3d_s(edge, 1e-6)
    return BRepBuilderAPI_MakeWire(edge).Wire()


def tooth_pieces(r_in: float, r_out: float, w_in: float, w_out: float, pitch: float, z0: float, z1: float,
                 *, trim: bool = True) -> list:
    """The tooth along +Z (local frame) covering z0..z1, trimmed flat at both ends: a trapezoid
    swept along a helix with its plane kept radial (binormal mode).

    A continuous sweep matters: lofting one-turn pieces and fusing them leaves microscopic
    seams, and later booleans on such threads go wrong (a cut through the thread returned
    more volume than the whole part; found by sectioning a printed bottle).
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Dir, gp_Pnt

    from . import _occ

    start = z0 - pitch  # begin early so the trimmed start is full depth
    spine = _helix(r_in, pitch, (z1 - start) + pitch, start)
    poly = BRepBuilderAPI_MakePolygon()
    for x, z in ((r_in, start - w_in / 2), (r_out, start - w_out / 2), (r_out, start + w_out / 2), (r_in, start + w_in / 2)):
        poly.Add(gp_Pnt(x, 0, z))
    poly.Close()
    mk = BRepOffsetAPI_MakePipeShell(spine)
    mk.SetMode(gp_Dir(0, 0, 1))
    mk.Add(poly.Wire(), False, False)
    mk.Build()
    if not mk.IsDone():
        return []
    mk.MakeSolid()
    tooth = mk.Shape()
    if _occ.volume_fast(tooth) < 0:
        tooth.Reverse()
    if not trim:  # the raw sweep, about one pitch beyond z0 and z1
        return [tooth]
    big = 4 * r_out + 10
    below = BRepPrimAPI_MakeBox(gp_Pnt(-big / 2, -big / 2, z0 - 4 * pitch), big, big, 4 * pitch).Shape()
    above = BRepPrimAPI_MakeBox(gp_Pnt(-big / 2, -big / 2, z1), big, big, 4 * pitch).Shape()
    tooth = BRepAlgoAPI_Cut(BRepAlgoAPI_Cut(tooth, below).Shape(), above).Shape()
    return [tooth] if _occ.solids(tooth) else []


def external_profile(d: float, pitch: float) -> dict:
    h = DEPTH * pitch
    r_maj = d / 2
    r_min = r_maj - h
    w_crest = pitch / 8
    return {"major_d": d, "minor_d": round(2 * r_min, 4), "pitch": pitch, "depth": round(h, 4), "crest": w_crest,
            "root": w_crest + 2 * h * TAN30}


def _with_core(r_core: float, tooth_args: tuple, pitch: float, z0: float, z1: float):
    """A cylinder of radius r_core united with the swept tooth, trimmed flat to z0..z1.

    The union is made before trimming, with the core running well past the tooth: when the core's end faces lie
    in the same planes as the trimmed tooth's, the kernel's union often drops the core entirely (seen for M28x3
    on macOS and M8 on Linux), and a coincident-face union is fragile in general."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    from . import _occ
    from .errors import BOOLEAN_FAILED
    from .part import _fuse_all

    teeth = tooth_pieces(*tooth_args, pitch, z0, z1, trim=False)
    if not teeth:
        return None
    a, b = z0 - 3 * pitch, z1 + 3 * pitch
    core = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, a), gp_Dir(0, 0, 1)), r_core, b - a).Shape()
    whole = _fuse_all([core] + teeth)
    keep = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, z0), gp_Dir(0, 0, 1)), tooth_args[1] + 5, z1 - z0).Shape()
    out = BRepAlgoAPI_Common(whole, keep).Shape()
    core_vol = 3.141592653589793 * r_core ** 2 * (z1 - z0)
    if not _occ.solids(out) or _occ.volume(out) < core_vol * (1 - 1e-6):
        raise CadError(BOOLEAN_FAILED, "building the thread solid failed (the kernel lost material)",
                       hint="try a slightly different length or pitch")
    return out


def bolt_tools(d: float, pitch: float, length: float, eps: float = 0.05):
    """The threaded rod (core and tooth as one solid) along +Z from 0 to length."""
    pr = external_profile(d, pitch)
    r_min, r_maj = pr["minor_d"] / 2, d / 2
    return _with_core(r_min, (r_min - eps, r_maj, pr["root"] + 2 * eps * TAN30, pr["crest"]), pitch, 0.0, length)


def hole_tools(d: float, pitch: float, z0: float, z1: float, clearance: float, eps: float = 0.05) -> tuple:
    """(cutting tool: bore and groove as one solid, info) for an internal thread along +Z between z0 and z1."""
    pr = external_profile(d, pitch)
    nut_minor = d - 1.0825 * pitch            # ISO D1
    r_bore = nut_minor / 2 + clearance
    r_out = d / 2 + clearance
    # groove = the bolt's tooth moved out radially by the clearance; its inner band sits inside the bore
    r_in = r_bore - eps
    w_in = pr["crest"] + 2 * (r_out - r_in) * TAN30   # = 0.75 P + small: always narrower than the pitch
    w_out = pr["crest"]
    tool = _with_core(r_bore, (r_in, r_out, w_in, w_out), pitch, z0, z1)
    return tool, {"bore_d": round(2 * r_bore, 4), "nut_minor_d": round(nut_minor, 4)}

"""3D paths for sweeps: polylines (optionally with bend radii), splines, arcs, helices.

A Path is an OCCT wire plus a description.  ``Part.sweep(profile, path)`` drags a 2D
profile along it; the profile is drawn in the plane perpendicular to the path at its
start, centred on the path start.
"""

from __future__ import annotations

import math
from typing import Sequence

from . import _occ
from .errors import INVALID_ARGUMENT, CadError

Vec3 = Sequence[float]


class Path:
    def __init__(self, wire, description: dict):
        self.wire = wire
        self.description = description

    # ------------------------------------------------------------------ constructors
    @staticmethod
    def polyline(points: Sequence[Vec3], *, radius: float = 0.0) -> "Path":
        """Straight segments through ``points``; ``radius`` rounds every corner into an arc
        (a bent tube or rod; the radius must exceed the profile's radius)."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from OCP.GC import GC_MakeArcOfCircle
        from OCP.gp import gp_Pnt

        pts = [_occ.vec(p) for p in points]
        if len(pts) < 2:
            raise CadError(INVALID_ARGUMENT, "a polyline needs at least 2 points")
        for a, b in zip(pts, pts[1:]):
            if math.dist(a, b) < 1e-9:
                raise CadError(INVALID_ARGUMENT, f"repeated point {a} in polyline")
        mw = BRepBuilderAPI_MakeWire()
        if radius <= 0 or len(pts) == 2:
            for a, b in zip(pts, pts[1:]):
                mw.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())
            return Path(mw.Wire(), {"type": "polyline", "points": [list(p) for p in pts], "radius": radius})
        # corner arcs: trim each segment by the tangent length at its ends
        cur = pts[0]
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            u = _unit([b[k] - a[k] for k in range(3)])
            w = _unit([c[k] - b[k] for k in range(3)])
            cos_t = max(-1.0, min(1.0, sum(x * y for x, y in zip(u, w))))
            turn = math.acos(cos_t)
            if turn < 1e-9:
                continue
            if turn > math.pi - 1e-6:
                raise CadError(INVALID_ARGUMENT, f"the polyline doubles back at {list(b)}")
            t = radius * math.tan(turn / 2)
            if t > min(math.dist(a, b), math.dist(b, c)) / (1 if i in (1, len(pts) - 2) else 2) + 1e-9:
                raise CadError(INVALID_ARGUMENT, f"bend radius {radius} does not fit the corner at {list(b)}",
                               hint="use a smaller radius or longer segments")
            p1 = [b[k] - u[k] * t for k in range(3)]
            p2 = [b[k] + w[k] * t for k in range(3)]
            bis = _unit([w[k] - u[k] for k in range(3)])
            dist_c = radius / math.cos(turn / 2)
            center = [b[k] + bis[k] * dist_c for k in range(3)]
            mid_dir = _unit([b[k] - center[k] for k in range(3)])
            mid = [center[k] + mid_dir[k] * radius for k in range(3)]
            if math.dist(cur, p1) > 1e-9:
                mw.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*cur), gp_Pnt(*p1)).Edge())
            arc = GC_MakeArcOfCircle(gp_Pnt(*p1), gp_Pnt(*mid), gp_Pnt(*p2)).Value()
            mw.Add(BRepBuilderAPI_MakeEdge(arc).Edge())
            cur = p2
        if math.dist(cur, pts[-1]) > 1e-9:
            mw.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*cur), gp_Pnt(*pts[-1])).Edge())
        return Path(mw.Wire(), {"type": "polyline", "points": [list(p) for p in pts], "radius": radius})

    @staticmethod
    def spline(points: Sequence[Vec3], *, closed: bool = False) -> "Path":
        """A smooth curve through ``points`` (C2 interpolation)."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from OCP.GeomAPI import GeomAPI_Interpolate
        from OCP.collections import HArray1_gp_Pnt as TColgp_HArray1OfPnt
        from OCP.gp import gp_Pnt

        pts = [_occ.vec(p) for p in points]
        if len(pts) < 2:
            raise CadError(INVALID_ARGUMENT, "a spline needs at least 2 points")
        arr = TColgp_HArray1OfPnt(1, len(pts))
        for i, p in enumerate(pts):
            arr.SetValue(i + 1, gp_Pnt(*p))
        it = GeomAPI_Interpolate(arr, closed, 1e-7)
        it.Perform()
        if not it.IsDone():
            raise CadError(INVALID_ARGUMENT, "could not fit a spline through these points (repeated points?)")
        w = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(it.Curve()).Edge()).Wire()
        return Path(w, {"type": "spline", "points": [list(p) for p in pts], "closed": closed})

    @staticmethod
    def arc(start: Vec3, through: Vec3, end: Vec3) -> "Path":
        """A circular arc from ``start`` through ``through`` to ``end``."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from OCP.GC import GC_MakeArcOfCircle
        from OCP.gp import gp_Pnt

        arc = GC_MakeArcOfCircle(gp_Pnt(*_occ.vec(start)), gp_Pnt(*_occ.vec(through)), gp_Pnt(*_occ.vec(end)))
        if not arc.IsDone():
            raise CadError(INVALID_ARGUMENT, "the three arc points are collinear")
        w = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(arc.Value()).Edge()).Wire()
        return Path(w, {"type": "arc", "points": [list(_occ.vec(p)) for p in (start, through, end)]})

    @staticmethod
    def helix(*, radius: float, pitch: float, height: float, center: Vec3 = (0, 0, 0), left_hand: bool = False) -> "Path":
        """A helix about the vertical axis through ``center``, starting at angle 0 (+X side) at
        the centre's height and rising ``height`` mm (a spring's centreline)."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from OCP.BRepLib import BRepLib
        from OCP.GC import GC_MakeSegment2d
        from OCP.Geom import Geom_CylindricalSurface
        from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Pnt2d

        if radius <= 0 or pitch <= 0 or height <= 0:
            raise CadError(INVALID_ARGUMENT, "helix radius, pitch and height must be positive")
        c = _occ.vec(center)
        surf = Geom_CylindricalSurface(gp_Ax3(gp_Pnt(*c), gp_Dir(0, 0, 1)), radius)
        turns = height / pitch
        u1 = 2 * math.pi * turns * (-1 if left_hand else 1)
        seg = GC_MakeSegment2d(gp_Pnt2d(0, 0), gp_Pnt2d(u1, height)).Value()
        edge = BRepBuilderAPI_MakeEdge(seg, surf).Edge()
        BRepLib.BuildCurves3d_s(edge, 1e-6)
        w = BRepBuilderAPI_MakeWire(edge).Wire()
        return Path(w, {"type": "helix", "radius": radius, "pitch": pitch, "height": height, "center": list(c),
                        "left_hand": left_hand})

    # ------------------------------------------------------------------ queries
    @property
    def length(self) -> float:
        return _occ.length(self.wire)

    def start(self) -> tuple[tuple, tuple]:
        """(point, unit tangent) at the start of the path."""
        from OCP.BRepAdaptor import BRepAdaptor_CompCurve
        from OCP.gp import gp_Pnt, gp_Vec

        c = BRepAdaptor_CompCurve(self.wire)
        p, v = gp_Pnt(), gp_Vec()
        c.D1(c.FirstParameter(), p, v)
        return (p.X(), p.Y(), p.Z()), _unit((v.X(), v.Y(), v.Z()))

    def min_bend_radius(self, samples: int = 200) -> float:
        """Smallest radius of curvature along the path (inf for straight segments)."""
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepLProp import BRepLProp_CLProps

        best = math.inf
        edges = _occ.edges(self.wire)
        n = max(4, samples // max(1, len(edges)))
        for e in edges:
            if _occ.curve_type(e) == "line":
                continue
            c = BRepAdaptor_Curve(e)
            for i in range(n + 1):
                t = c.FirstParameter() + (c.LastParameter() - c.FirstParameter()) * i / n
                pr = BRepLProp_CLProps(c, t, 2, 1e-9)
                if pr.IsTangentDefined():
                    k = pr.Curvature()
                    if k > 1e-12:
                        best = min(best, 1 / k)
        return best


def _unit(v) -> tuple:
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-15:
        raise CadError(INVALID_ARGUMENT, "zero-length direction in path")
    return tuple(c / n for c in v)

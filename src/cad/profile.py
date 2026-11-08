"""2D profiles and sketch planes.

A :class:`Profile` is a closed planar region expressed in local 2D coordinates
(u, v) in millimetres.  It is placed in 3D by a :class:`Plane` when used by
``Part.extrude`` or ``Part.revolve``.

Profiles combine with ``+`` (union) and ``-`` (subtract)::

    plate = Profile.rounded_rect(60, 40, radius=5) - Profile.circle(10)

Standard planes (right-handed: normal = u x v)::

    "XY"  u=+X  v=+Y  normal=+Z
    "XZ"  u=+X  v=+Z  normal=-Y   (extrude toward the back is -Y; use negative
                                   distance or symmetric=True for +Y)
    "YZ"  u=+Y  v=+Z  normal=+X
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_Transform,
)
from OCP.gp import gp_Ax2, gp_Ax3, gp_Circ, gp_Dir, gp_Pnt, gp_Trsf
from OCP.GC import GC_MakeArcOfCircle
from OCP.TopoDS import TopoDS_Shape

from . import _occ
from .errors import INVALID_ARGUMENT, CadError

Vec2 = tuple[float, float]


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        raise CadError(INVALID_ARGUMENT, f"zero-length vector {v!r}")
    return tuple(c / n for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


@dataclass(frozen=True)
class Plane:
    """A sketch plane: ``origin`` plus orthonormal ``u`` (x_dir) and ``normal``.

    ``v`` is derived as normal x u, so (u, v, normal) is right-handed.
    """

    origin: tuple[float, float, float]
    normal: tuple[float, float, float]
    u: tuple[float, float, float]

    @property
    def v(self):
        return _cross(self.normal, self.u)

    @staticmethod
    def named(name: str, offset: float = 0.0) -> "Plane":
        """'XY', 'XZ' or 'YZ', optionally offset along its normal."""
        key = name.upper()
        table = {
            "XY": ((0, 0, 1), (1, 0, 0)),
            "XZ": ((0, -1, 0), (1, 0, 0)),
            "YZ": ((1, 0, 0), (0, 1, 0)),
        }
        if key not in table:
            raise CadError(INVALID_ARGUMENT, f"unknown plane {name!r}", hint="use 'XY', 'XZ', 'YZ' or Plane(...)")
        n, u = table[key]
        o = tuple(offset * c for c in n)
        return Plane(o, tuple(float(c) for c in n), tuple(float(c) for c in u))

    @staticmethod
    def make(origin=(0, 0, 0), normal=(0, 0, 1), u=None) -> "Plane":
        """Arbitrary plane.  ``u`` defaults to global X (or Y if normal is ~X)."""
        n = _norm(_occ.vec(normal))
        if u is None:
            u = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
        u = _occ.vec(u)
        d = sum(a * b for a, b in zip(u, n))
        u = _norm(tuple(a - d * b for a, b in zip(u, n)))
        return Plane(tuple(float(c) for c in _occ.vec(origin)), n, u)

    def offset(self, distance: float) -> "Plane":
        o = tuple(a + distance * b for a, b in zip(self.origin, self.normal))
        return Plane(o, self.normal, self.u)

    def to_world(self, p: Sequence[float]) -> tuple[float, float, float]:
        x, y = float(p[0]), float(p[1])
        z = float(p[2]) if len(p) > 2 else 0.0
        v = self.v
        return tuple(o + x * a + y * b + z * c for o, a, b, c in zip(self.origin, self.u, v, self.normal))

    def trsf(self) -> gp_Trsf:
        """Transform taking local XY (z=0) coordinates onto this plane."""
        t = gp_Trsf()
        t.SetTransformation(gp_Ax3(gp_Pnt(*self.origin), gp_Dir(*self.normal), gp_Dir(*self.u)), gp_Ax3())
        return t

    def describe(self) -> dict:
        return {"origin": list(self.origin), "normal": list(self.normal), "u": list(self.u), "v": list(self.v)}


def as_plane(plane: "str | Plane", offset: float = 0.0) -> Plane:
    if isinstance(plane, Plane):
        return plane.offset(offset) if offset else plane
    if isinstance(plane, str):
        return Plane.named(plane, offset)
    raise CadError(INVALID_ARGUMENT, f"expected a plane name or Plane, got {type(plane).__name__}")


class Profile:
    """A closed 2D region in local (u, v) coordinates, millimetres."""

    def __init__(self, face: TopoDS_Shape, description: dict):
        self._face = face
        self.description = description

    # ------------------------------------------------------------------ constructors
    @staticmethod
    def rect(width: float, height: float, center: Vec2 = (0, 0)) -> "Profile":
        """Axis-aligned rectangle ``width`` (u) x ``height`` (v) centred on ``center``."""
        _positive(width=width, height=height)
        cx, cy = center
        w, h = width / 2, height / 2
        pts = [(cx - w, cy - h), (cx + w, cy - h), (cx + w, cy + h), (cx - w, cy + h)]
        p = Profile.polygon(pts)
        p.description = {"type": "rect", "width": width, "height": height, "center": list(center)}
        return p

    @staticmethod
    def rect_corners(p1: Vec2, p2: Vec2) -> "Profile":
        """Axis-aligned rectangle spanning two opposite corners."""
        (x1, y1), (x2, y2) = p1, p2
        p = Profile.rect(abs(x2 - x1), abs(y2 - y1), ((x1 + x2) / 2, (y1 + y2) / 2))
        p.description = {"type": "rect_corners", "p1": list(p1), "p2": list(p2)}
        return p

    @staticmethod
    def circle(diameter: float, center: Vec2 = (0, 0)) -> "Profile":
        _positive(diameter=diameter)
        circ = gp_Circ(gp_Ax2(gp_Pnt(center[0], center[1], 0), gp_Dir(0, 0, 1)), diameter / 2)
        edge = BRepBuilderAPI_MakeEdge(circ).Edge()
        wire = BRepBuilderAPI_MakeWire(edge).Wire()
        face = BRepBuilderAPI_MakeFace(wire, True).Face()
        return Profile(face, {"type": "circle", "diameter": diameter, "center": list(center)})

    @staticmethod
    def polygon(points: Sequence[Vec2]) -> "Profile":
        """Closed polygon through ``points`` (do not repeat the first point)."""
        pts = [tuple(map(float, p)) for p in points]
        if len(pts) >= 2 and math.dist(pts[0], pts[-1]) < 1e-9:
            pts = pts[:-1]
        if len(pts) < 3:
            raise CadError(INVALID_ARGUMENT, "polygon needs at least 3 distinct points")
        mp = BRepBuilderAPI_MakePolygon()
        for x, y in pts:
            mp.Add(gp_Pnt(x, y, 0))
        mp.Close()
        if not mp.IsDone():
            raise CadError(INVALID_ARGUMENT, "could not build polygon (duplicate or collinear points?)")
        mf = BRepBuilderAPI_MakeFace(mp.Wire(), True)
        if not mf.IsDone():
            raise CadError(INVALID_ARGUMENT, "polygon is not a valid planar region (self-intersecting?)")
        return Profile(mf.Face(), {"type": "polygon", "points": [list(p) for p in pts]})

    @staticmethod
    def rounded_rect(width: float, height: float, radius: float, center: Vec2 = (0, 0)) -> "Profile":
        """Rectangle with all four corners rounded by ``radius``."""
        _positive(width=width, height=height)
        if radius <= 0:
            return Profile.rect(width, height, center)
        if radius * 2 > min(width, height) + 1e-9:
            raise CadError(
                INVALID_ARGUMENT,
                f"corner radius {radius} is too large for a {width} x {height} rectangle",
                hint=f"radius must be <= {min(width, height) / 2}",
            )
        cx, cy = center
        w, h, r = width / 2, height / 2, radius
        segs = []

        def line(a, b):
            if math.dist(a, b) > 1e-9:
                segs.append(BRepBuilderAPI_MakeEdge(gp_Pnt(*a, 0), gp_Pnt(*b, 0)).Edge())

        def arc(a, m, b):
            segs.append(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(gp_Pnt(*a, 0), gp_Pnt(*m, 0), gp_Pnt(*b, 0)).Value()).Edge())

        k = r * (1 - math.sqrt(0.5))
        x0, x1, y0, y1 = cx - w, cx + w, cy - h, cy + h
        line((x0 + r, y0), (x1 - r, y0))
        arc((x1 - r, y0), (x1 - k, y0 + k), (x1, y0 + r))
        line((x1, y0 + r), (x1, y1 - r))
        arc((x1, y1 - r), (x1 - k, y1 - k), (x1 - r, y1))
        line((x1 - r, y1), (x0 + r, y1))
        arc((x0 + r, y1), (x0 + k, y1 - k), (x0, y1 - r))
        line((x0, y1 - r), (x0, y0 + r))
        arc((x0, y0 + r), (x0 + k, y0 + k), (x0 + r, y0))
        mw = BRepBuilderAPI_MakeWire()
        for e in segs:
            mw.Add(e)
        face = BRepBuilderAPI_MakeFace(mw.Wire(), True).Face()
        return Profile(
            face, {"type": "rounded_rect", "width": width, "height": height, "radius": radius, "center": list(center)}
        )

    @staticmethod
    def slot(length: float, width: float, center: Vec2 = (0, 0), angle: float = 0.0) -> "Profile":
        """Obround slot: overall ``length`` (end to end) along u rotated by ``angle`` degrees."""
        _positive(length=length, width=width)
        if length < width:
            raise CadError(INVALID_ARGUMENT, "slot length must be >= width (length is end-to-end)")
        p = Profile.rounded_rect(length, width, width / 2 - 1e-9 if length == width else width / 2)
        if angle:
            p = p.rotated(angle)
        p = p.translated(center)
        p.description = {"type": "slot", "length": length, "width": width, "center": list(center), "angle": angle}
        return p

    @staticmethod
    def regular_polygon(sides: int, diameter: float | None = None, center: Vec2 = (0, 0), angle: float = 0.0,
                        *, across_flats: float | None = None) -> "Profile":
        """Regular polygon, sized by ``diameter`` (corner to corner, i.e. the circumscribed
        circle) or ``across_flats`` (distance between opposite flats, the wrench size).

        With ``angle=0`` the first corner lies on +u; for a hexagon that puts the
        flats perpendicular to v (at v = +-across_flats/2).
        """
        if sides < 3:
            raise CadError(INVALID_ARGUMENT, "regular polygon needs at least 3 sides")
        if (diameter is None) == (across_flats is None):
            raise CadError(INVALID_ARGUMENT, "give exactly one of diameter= (corner to corner) or across_flats=")
        if across_flats is not None:
            diameter = across_flats / math.cos(math.pi / sides)
        r = diameter / 2
        pts = [
            (center[0] + r * math.cos(math.radians(angle) + 2 * math.pi * i / sides),
             center[1] + r * math.sin(math.radians(angle) + 2 * math.pi * i / sides))
            for i in range(sides)
        ]
        p = Profile.polygon(pts)
        p.description = {"type": "regular_polygon", "sides": sides, "diameter": diameter, "center": list(center)}
        return p

    # ------------------------------------------------------------------ combination
    def __add__(self, other: "Profile") -> "Profile":
        op = BRepAlgoAPI_Fuse(self._face, other._face)
        op.SimplifyResult()
        return Profile(op.Shape(), {"type": "union", "of": [self.description, other.description]})

    def __sub__(self, other: "Profile") -> "Profile":
        op = BRepAlgoAPI_Cut(self._face, other._face)
        op.SimplifyResult()
        return Profile(op.Shape(), {"type": "difference", "of": [self.description, other.description]})

    def translated(self, offset: Vec2) -> "Profile":
        t = gp_Trsf()
        from OCP.gp import gp_Vec

        t.SetTranslation(gp_Vec(offset[0], offset[1], 0))
        return Profile(BRepBuilderAPI_Transform(self._face, t, True).Shape(), {"type": "translated", "by": list(offset), "of": self.description})

    def rotated(self, angle_deg: float, center: Vec2 = (0, 0)) -> "Profile":
        from OCP.gp import gp_Ax1

        t = gp_Trsf()
        t.SetRotation(gp_Ax1(gp_Pnt(center[0], center[1], 0), gp_Dir(0, 0, 1)), math.radians(angle_deg))
        return Profile(BRepBuilderAPI_Transform(self._face, t, True).Shape(), {"type": "rotated", "angle": angle_deg, "of": self.description})

    def offset(self, distance: float) -> "Profile":
        """Grow (positive) or shrink (negative) the region by ``distance`` mm on every edge.

        Outer corners stay sharp for rectangles when shrinking and become rounded
        when growing (arc joins).  Useful for clearances and walls::

            cavity = Profile.rounded_rect(95, 65, 3.5)
            lip = cavity.offset(-0.25) - cavity.offset(-2.25)
        """
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
        from OCP.GeomAbs import GeomAbs_Arc

        faces = _occ.faces(self._face)
        if not faces:
            raise CadError(INVALID_ARGUMENT, "cannot offset an empty profile")
        result = None
        for f in faces:
            mk = BRepOffsetAPI_MakeOffset(f, GeomAbs_Arc)
            mk.Perform(distance)
            if not mk.IsDone():
                raise CadError(INVALID_ARGUMENT, f"profile offset by {distance} failed",
                               hint="a negative offset larger than half the narrowest width collapses the region")
            shape = mk.Shape()
            wires = _occ.wires(shape)
            if not wires:
                raise CadError(INVALID_ARGUMENT, f"profile offset by {distance} produced nothing")
            # largest wire is the outer boundary, the rest are holes
            wire_faces = sorted(((abs(_occ.area(BRepBuilderAPI_MakeFace(w, True).Face())), w) for w in wires),
                                key=lambda t: -t[0])
            mf = BRepBuilderAPI_MakeFace(wire_faces[0][1], True)
            outer = Profile(mf.Face(), {})
            for _, w in wire_faces[1:]:
                outer = outer - Profile(BRepBuilderAPI_MakeFace(w, True).Face(), {})
            result = outer if result is None else result + outer
        result.description = {"type": "offset", "distance": distance, "of": self.description}
        return result

    @property
    def area(self) -> float:
        return _occ.area(self._face)

    def placed(self, plane: Plane) -> TopoDS_Shape:
        """The profile face(s) moved onto ``plane`` in world coordinates."""
        return BRepBuilderAPI_Transform(self._face, plane.trsf(), True).Shape()


def _positive(**kw):
    for k, v in kw.items():
        if not isinstance(v, (int, float)) or v <= 0:
            raise CadError(INVALID_ARGUMENT, f"{k} must be a positive number of millimetres, got {v!r}")

"""Thin helpers over OCP (Open CASCADE Python bindings).

Everything that touches raw OCCT types lives here or in modules that import
from here, so the rest of the package stays readable and the binding surface is
easy to audit when OCP changes.
"""

from __future__ import annotations

import math
from typing import Iterable, Iterator, Sequence

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import (
    GeomAbs_BSplineSurface,
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Line,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Pnt, gp_Vec
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_REVERSED,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape
from OCP.TopTools import TopTools_ShapeMapHasher  # noqa: F401  (re-export for callers)

Vec3 = tuple[float, float, float]


def _silence_kernel_messages() -> None:
    """OCCT prints transfer statistics to stdout; agents need clean stdout for JSON."""
    try:
        from OCP.Message import Message

        Message.DefaultMessenger_s().ChangePrinters().Clear()
    except Exception:  # pragma: no cover - best effort
        pass


_silence_kernel_messages()

_SURFACE_TYPES = {
    GeomAbs_Plane: "plane",
    GeomAbs_Cylinder: "cylinder",
    GeomAbs_Cone: "cone",
    GeomAbs_Sphere: "sphere",
    GeomAbs_Torus: "torus",
    GeomAbs_BSplineSurface: "bspline",
}
_CURVE_TYPES = {GeomAbs_Line: "line", GeomAbs_Circle: "circle"}


# --------------------------------------------------------------------------- topology


def iter_sub(shape: TopoDS_Shape, kind) -> Iterator[TopoDS_Shape]:
    """Yield unique sub-shapes of ``kind`` (TopAbs_FACE, ...) in a stable order."""
    seen: dict[int, list[TopoDS_Shape]] = {}
    exp = TopExp_Explorer(shape, kind)
    while exp.More():
        s = exp.Current()
        bucket = seen.setdefault(hash(s), [])
        if not any(s.IsSame(o) for o in bucket):
            bucket.append(s)
            yield s
        exp.Next()


def faces(shape: TopoDS_Shape) -> list:
    return [TopoDS.Face(s) for s in iter_sub(shape, TopAbs_FACE)]


def edges(shape: TopoDS_Shape) -> list:
    return [TopoDS.Edge(s) for s in iter_sub(shape, TopAbs_EDGE)]


def solids(shape: TopoDS_Shape) -> list:
    return [TopoDS.Solid(s) for s in iter_sub(shape, TopAbs_SOLID)]


def shells(shape: TopoDS_Shape) -> list:
    return [TopoDS.Shell(s) for s in iter_sub(shape, TopAbs_SHELL)]


def wires(shape: TopoDS_Shape) -> list:
    from OCP.TopAbs import TopAbs_WIRE

    return [TopoDS.Wire(s) for s in iter_sub(shape, TopAbs_WIRE)]


def vertices(shape: TopoDS_Shape) -> list:
    return [TopoDS.Vertex(s) for s in iter_sub(shape, TopAbs_VERTEX)]


def compound(shapes: Iterable[TopoDS_Shape]) -> TopoDS_Compound:
    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    for s in shapes:
        b.Add(comp, s)
    return comp


class ShapeSet:
    """Set of shapes compared with ``IsSame`` (ignores orientation)."""

    def __init__(self, shapes: Iterable[TopoDS_Shape] = ()):
        self._d: dict[int, list[TopoDS_Shape]] = {}
        for s in shapes:
            self.add(s)

    def add(self, s: TopoDS_Shape) -> None:
        bucket = self._d.setdefault(hash(s), [])
        if not any(s.IsSame(o) for o in bucket):
            bucket.append(s)

    def __contains__(self, s: TopoDS_Shape) -> bool:
        return any(s.IsSame(o) for o in self._d.get(hash(s), ()))

    def __len__(self) -> int:
        return sum(len(b) for b in self._d.values())

    def get(self, s: TopoDS_Shape):
        """The stored shape that IsSame ``s`` (or None)."""
        for o in self._d.get(hash(s), ()):
            if s.IsSame(o):
                return o
        return None


def edge_face_map(shape: TopoDS_Shape) -> dict[int, list]:
    """Map hash(edge) -> list of (edge, [faces]) for adjacency queries."""
    out: dict[int, list] = {}
    for f in faces(shape):
        for e in edges(f):
            bucket = out.setdefault(hash(e), [])
            for entry in bucket:
                if entry[0].IsSame(e):
                    if not any(f.IsSame(g) for g in entry[1]):
                        entry[1].append(f)
                    break
            else:
                bucket.append((e, [f]))
    return out


def faces_of_edge(efmap: dict[int, list], edge) -> list:
    for e, fs in efmap.get(hash(edge), ()):
        if e.IsSame(edge):
            return fs
    return []


# --------------------------------------------------------------------------- properties


def volume(shape: TopoDS_Shape) -> float:
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, p)
    return p.Mass()


def area(shape: TopoDS_Shape) -> float:
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, p)
    return p.Mass()


def length(shape: TopoDS_Shape) -> float:
    p = GProp_GProps()
    BRepGProp.LinearProperties_s(shape, p)
    return p.Mass()


def center_of_mass(shape: TopoDS_Shape) -> Vec3:
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, p)
    c = p.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def face_centroid(face) -> Vec3:
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, p)
    c = p.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def edge_centroid(edge) -> Vec3:
    p = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, p)
    c = p.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def bbox(shape: TopoDS_Shape, optimal: bool = True) -> tuple[Vec3, Vec3]:
    b = Bnd_Box()
    if optimal:
        BRepBndLib.AddOptimal_s(shape, b, False, False)
    else:
        BRepBndLib.Add_s(shape, b)
    if b.IsVoid():
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    lo, hi = b.CornerMin(), b.CornerMax()
    return (lo.X(), lo.Y(), lo.Z()), (hi.X(), hi.Y(), hi.Z())


def is_valid(shape: TopoDS_Shape) -> bool:
    return BRepCheck_Analyzer(shape).IsValid()


def distance(a: TopoDS_Shape, b: TopoDS_Shape) -> tuple[float, Vec3, Vec3]:
    d = BRepExtrema_DistShapeShape(a, b)
    d.Perform()
    if not d.IsDone():
        raise RuntimeError("distance computation failed")
    p1, p2 = d.PointOnShape1(1), d.PointOnShape2(1)
    return d.Value(), (p1.X(), p1.Y(), p1.Z()), (p2.X(), p2.Y(), p2.Z())


# --------------------------------------------------------------------------- geometry kinds


def surface_type(face) -> str:
    return _SURFACE_TYPES.get(BRepAdaptor_Surface(face).GetType(), "other")


def curve_type(edge) -> str:
    return _CURVE_TYPES.get(BRepAdaptor_Curve(edge).GetType(), "other")


def face_normal_at(face, u: float, v: float) -> Vec3:
    surf = BRepAdaptor_Surface(face)
    props = BRepLProp_SLProps(surf, u, v, 1, 1e-6)
    if not props.IsNormalDefined():
        return (0.0, 0.0, 0.0)
    n = props.Normal()
    if face.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    return (n.X(), n.Y(), n.Z())


def face_normal(face) -> Vec3:
    """Outward normal at the parametric middle of the face."""
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    return face_normal_at(face, (umin + umax) / 2, (vmin + vmax) / 2)


def cylinder_info(face) -> dict | None:
    """Axis/radius of a cylindrical face, and whether it is a hole (concave)."""
    surf = BRepAdaptor_Surface(face)
    if surf.GetType() != GeomAbs_Cylinder:
        return None
    cyl = surf.Cylinder()
    ax = cyl.Axis()
    loc, d = ax.Location(), ax.Direction()
    r = cyl.Radius()
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    u, v = (umin + umax) / 2, (vmin + vmax) / 2
    p = surf.Value(u, v)
    n = face_normal_at(face, u, v)
    # radial vector from axis to the surface point
    w = gp_Vec(loc, p)
    dv = gp_Vec(d)
    radial = w - dv * w.Dot(dv)
    concave = (radial.X() * n[0] + radial.Y() * n[1] + radial.Z() * n[2]) < 0
    # axial extent of the face
    lo, hi = math.inf, -math.inf
    for vert in vertices(face):
        q = BRep_Tool.Pnt_s(vert)
        t = gp_Vec(loc, q).Dot(dv)
        lo, hi = min(lo, t), max(hi, t)
    if lo == math.inf:  # seamless full cylinder without vertices: fall back to v-range
        lo, hi = vmin, vmax
    base = loc.Translated(dv * lo)
    return {
        "radius": r,
        "diameter": 2 * r,
        "axis": (d.X(), d.Y(), d.Z()),
        "axis_point": (base.X(), base.Y(), base.Z()),
        "length": hi - lo,
        "angle": umax - umin,
        "concave": concave,
    }


def circle_info(edge) -> dict | None:
    c = BRepAdaptor_Curve(edge)
    if c.GetType() != GeomAbs_Circle:
        return None
    circ = c.Circle()
    loc, d = circ.Location(), circ.Axis().Direction()
    return {
        "radius": circ.Radius(),
        "center": (loc.X(), loc.Y(), loc.Z()),
        "axis": (d.X(), d.Y(), d.Z()),
    }


def edge_tangent(edge) -> Vec3:
    """Unit tangent at the middle of an edge (honouring edge orientation)."""
    c = BRepAdaptor_Curve(edge)
    t = (c.FirstParameter() + c.LastParameter()) / 2
    p, v = gp_Pnt(), gp_Vec()
    c.D1(t, p, v)
    if v.Magnitude() < 1e-12:
        return (0.0, 0.0, 0.0)
    v.Normalize()
    if edge.Orientation() == TopAbs_REVERSED:
        v.Reverse()
    return (v.X(), v.Y(), v.Z())


def edge_endpoints(edge) -> tuple[Vec3, Vec3]:
    v1, v2 = TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)
    p1, p2 = BRep_Tool.Pnt_s(v1), BRep_Tool.Pnt_s(v2)
    return (p1.X(), p1.Y(), p1.Z()), (p2.X(), p2.Y(), p2.Z())


def edge_midpoint(edge) -> Vec3:
    c = BRepAdaptor_Curve(edge)
    p = c.Value((c.FirstParameter() + c.LastParameter()) / 2)
    return (p.X(), p.Y(), p.Z())


def edge_convexity(edge, face_a, face_b) -> float:
    """Signed convexity of an edge between two faces.

    Returns < 0 for a convex (outside) edge, > 0 for a concave (inside) edge,
    ~0 for tangent (smooth) junctions.  Computed as dot(d_a, n_b) where d_a is
    the in-face direction of ``face_a`` perpendicular to the edge and n_b is the
    outward normal of ``face_b`` at the edge midpoint.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve2d
    from OCP.gp import gp_Pnt2d, gp_Vec2d

    def oriented_in(face):
        for e in edges(face):
            if e.IsSame(edge):
                return e
        return edge

    ea = oriented_in(face_a)
    c = BRepAdaptor_Curve(ea)
    tmid = (c.FirstParameter() + c.LastParameter()) / 2
    p, tan = gp_Pnt(), gp_Vec()
    c.D1(tmid, p, tan)
    if tan.Magnitude() < 1e-12:
        return 0.0
    tan.Normalize()
    if ea.Orientation() == TopAbs_REVERSED:
        tan.Reverse()

    def normal_at_point(face, edge_in_face):
        c2 = BRepAdaptor_Curve2d(edge_in_face, face)
        uv = gp_Pnt2d()
        c2.D0(tmid, uv)
        return face_normal_at(face, uv.X(), uv.Y())

    try:
        na = normal_at_point(face_a, ea)
        nb = normal_at_point(face_b, oriented_in(face_b))
    except Exception:
        na, nb = face_normal(face_a), face_normal(face_b)
    na_v = gp_Vec(*na)
    # material lies to the left of the oriented edge when looking along the normal
    d_a = na_v.Crossed(tan)
    return d_a.X() * nb[0] + d_a.Y() * nb[1] + d_a.Z() * nb[2]


def first_hit(shape: TopoDS_Shape, origin, direction) -> float | None:
    """Parameter of the first intersection of the ray origin + t*direction (t >= 0) with ``shape``."""
    from OCP.gp import gp_Dir, gp_Lin
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape, 1e-7)
    inter.Perform(gp_Lin(gp_Pnt(*origin), gp_Dir(*direction)), -1e-6, 1e12)
    ts = [inter.WParameter(i) for i in range(1, inter.NbPnt() + 1)]
    return min(ts) if ts else None


def fix_shape(shape: TopoDS_Shape) -> TopoDS_Shape:
    from OCP.ShapeFix import ShapeFix_Shape

    fixer = ShapeFix_Shape(shape)
    fixer.Perform()
    return fixer.Shape()


def vec(v: Sequence[float]) -> Vec3:
    if len(v) == 2:
        return (float(v[0]), float(v[1]), 0.0)
    if len(v) != 3:
        raise ValueError(f"expected a 2- or 3-component vector, got {v!r}")
    return (float(v[0]), float(v[1]), float(v[2]))

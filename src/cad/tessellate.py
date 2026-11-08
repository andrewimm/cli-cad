"""BRep -> triangle mesh + feature-edge polylines (renderer input)."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepLib import BRepLib_ToolTriangulatedShape
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GCPnts import GCPnts_TangentialDeflection
from OCP.TopAbs import TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location

from . import _occ


@dataclass
class Mesh:
    vertices: np.ndarray  # (N, 3) float64, world mm
    normals: np.ndarray  # (N, 3) float64, unit outward
    triangles: np.ndarray  # (M, 3) int64
    face_ids: np.ndarray  # (M,) int64 — index of the BRep face (in _occ.faces order)
    edges: list[np.ndarray] = field(default_factory=list)  # polylines (K, 3)
    linear_deflection: float = 0.0
    angular_deflection: float = 0.0

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if len(self.vertices) == 0:
            z = np.zeros(3)
            return z, z
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def to_npz(self, path) -> None:
        lens = np.array([len(e) for e in self.edges], dtype=np.int64)
        pts = np.concatenate(self.edges) if self.edges else np.zeros((0, 3))
        np.savez_compressed(
            path,
            vertices=self.vertices,
            normals=self.normals,
            triangles=self.triangles,
            face_ids=self.face_ids,
            edge_lens=lens,
            edge_pts=pts,
            deflection=np.array([self.linear_deflection, self.angular_deflection]),
        )

    @staticmethod
    def from_npz(path) -> "Mesh":
        d = np.load(path)
        lens, pts = d["edge_lens"], d["edge_pts"]
        edges, i = [], 0
        for n in lens:
            edges.append(pts[i : i + n])
            i += n
        lin, ang = d["deflection"]
        return Mesh(d["vertices"], d["normals"], d["triangles"], d["face_ids"], edges, float(lin), float(ang))


def default_deflection(shape) -> float:
    lo, hi = _occ.bbox(shape, optimal=False)
    diag = math.dist(lo, hi)
    return min(max(diag * 0.0015, 0.005), 0.5)


def tessellate(shape, linear_deflection: float | None = None, angular_deflection: float = 0.25) -> Mesh:
    """Triangulate ``shape``.  ``linear_deflection`` defaults to ~0.15% of the bbox diagonal."""
    lin = linear_deflection or default_deflection(shape)
    _occ.mesh_shape(shape, lin, angular_deflection)
    verts, norms, tris, fids = [], [], [], []
    offset = 0
    faces = _occ.faces(shape)
    for fi, face in enumerate(faces):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        identity = loc.IsIdentity()
        n = tri.NbNodes()
        if not tri.HasNormals():
            BRepLib_ToolTriangulatedShape.ComputeNormals_s(face, tri)
        reversed_ = face.Orientation() == TopAbs_REVERSED
        pv = np.empty((n, 3))
        nv = np.empty((n, 3))
        for i in range(1, n + 1):
            p = tri.Node(i)
            d = tri.Normal(i)
            if not identity:
                p = p.Transformed(trsf)
                d = d.Transformed(trsf)
            pv[i - 1] = (p.X(), p.Y(), p.Z())
            nv[i - 1] = (d.X(), d.Y(), d.Z())
        if reversed_:
            nv = -nv
        m = tri.NbTriangles()
        tv = np.empty((m, 3), dtype=np.int64)
        for i in range(1, m + 1):
            a, b, c = tri.Triangle(i).Get()
            tv[i - 1] = (a, c, b) if reversed_ else (a, b, c)
        verts.append(pv)
        norms.append(nv)
        tris.append(tv - 1 + offset)
        fids.append(np.full(m, fi, dtype=np.int64))
        offset += n
    if verts:
        V, N = np.concatenate(verts), np.concatenate(norms)
        T, F = np.concatenate(tris), np.concatenate(fids)
    else:
        V = N = np.zeros((0, 3))
        T = np.zeros((0, 3), dtype=np.int64)
        F = np.zeros(0, dtype=np.int64)
    lens = np.linalg.norm(N, axis=1, keepdims=True)
    N = N / np.where(lens > 0, lens, 1)
    return Mesh(V, N, T, F, _edge_polylines(shape, lin, angular_deflection), lin, angular_deflection)


def _edge_polylines(shape, lin: float, ang: float) -> list[np.ndarray]:
    efmap = _occ.edge_face_map(shape)
    out = []
    for e in _occ.edges(shape):
        if BRep_Tool.Degenerated_s(e):
            continue
        fs = _occ.faces_of_edge(efmap, e)
        # seam edges (the closing line of a cylinder or cone) are not visual edges
        if len(fs) == 1 and BRep_Tool.IsClosed_s(e, fs[0]):
            continue
        try:
            curve = BRepAdaptor_Curve(e)
            disc = GCPnts_TangentialDeflection(curve, ang, lin)
            pts = [disc.Value(i) for i in range(1, disc.NbPoints() + 1)]
        except Exception:
            continue
        if len(pts) >= 2:
            out.append(np.array([(p.X(), p.Y(), p.Z()) for p in pts]))
    return out


def brep_bytes(shape) -> bytes:
    """Canonical BREP serialisation without triangulation (stable for hashing)."""
    import io

    from OCP.BRepTools import BRepTools
    from OCP.TopTools import TopTools_FormatVersion

    buf = io.BytesIO()
    BRepTools.Write_s(shape, buf, False, False, TopTools_FormatVersion.TopTools_FormatVersion_VERSION_1)
    return buf.getvalue()


def shape_digest(shape) -> str:
    """Content hash of a shape for cache keys."""
    return hashlib.sha256(brep_bytes(shape)).hexdigest()

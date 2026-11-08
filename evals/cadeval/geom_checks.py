"""Geometric helpers for the richer check types (envelopes, thickness, exports)."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from cad import Part, _occ


# --------------------------------------------------------------------------- reference solids


def make_solid(spec: dict):
    """A reference solid from a task-file spec.

    {"box": {"min": [x, y, z], "max": [x, y, z]}}
    {"cylinder": {"center": [x, y, z], "axis": [x, y, z], "diameter": d, "from": t0, "to": t1}}
      (the cylinder spans center + t*axis for t in [from, to])
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    if "box" in spec:
        lo, hi = spec["box"]["min"], spec["box"]["max"]
        return BRepPrimAPI_MakeBox(gp_Pnt(*map(float, lo)), gp_Pnt(*map(float, hi))).Shape()
    if "cylinder" in spec:
        c = spec["cylinder"]
        ax = np.asarray(c["axis"], dtype=float)
        ax = ax / np.linalg.norm(ax)
        t0, t1 = float(c["from"]), float(c["to"])
        base = np.asarray(c["center"], dtype=float) + t0 * ax
        return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*base), gp_Dir(*ax)), float(c["diameter"]) / 2, t1 - t0).Shape()
    raise ValueError(f"unknown solid spec {spec!r}")


def common_volume(a, b) -> float:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    op = BRepAlgoAPI_Common(a, b)
    return _occ.volume(op.Shape()) if op.IsDone() else float("nan")


# --------------------------------------------------------------------------- thickness


def thickness_samples(part: Part, per_face: int = 5) -> list[tuple[float, tuple, int]]:
    """Local wall thickness at points sampled on every face.

    For each sample, a ray is cast inward (against the outward normal) and the
    distance to the next boundary crossing is the local thickness.  Returns
    (thickness, point, face_index) tuples.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d
    from OCP.TopAbs import TopAbs_IN

    shape = part.shape
    out = []
    for fi, f in enumerate(_occ.faces(shape)):
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f)
        surf = BRepAdaptor_Surface(f)
        for i in range(per_face):
            for j in range(per_face):
                u = umin + (i + 0.5) / per_face * (umax - umin)
                v = vmin + (j + 0.5) / per_face * (vmax - vmin)
                if BRepClass_FaceClassifier(f, gp_Pnt2d(u, v), 1e-7).State() != TopAbs_IN:
                    continue
                n = _occ.face_normal_at(f, u, v)
                if n == (0.0, 0.0, 0.0):
                    continue
                p = surf.Value(u, v)
                origin = (p.X() - n[0] * 1e-4, p.Y() - n[1] * 1e-4, p.Z() - n[2] * 1e-4)
                t = _occ.first_hit(shape, origin, (-n[0], -n[1], -n[2]))
                if t is not None:
                    out.append((t + 1e-4, (p.X(), p.Y(), p.Z()), fi))
    return out


# --------------------------------------------------------------------------- exports


def _read_stl(path: Path) -> np.ndarray:
    """Triangles (N, 3, 3) from a binary or ASCII STL."""
    data = path.read_bytes()
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        verts = [tuple(map(float, line.split()[1:4])) for line in data.decode(errors="ignore").splitlines()
                 if line.strip().startswith("vertex")]
        return np.asarray(verts, dtype=float).reshape(-1, 3, 3)
    n = int.from_bytes(data[80:84], "little")
    rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
    return rec["v"].astype(float)


def stl_report(path: Path, weld: float = 1e-4) -> dict:
    tris = _read_stl(path)
    pts = tris.reshape(-1, 3)
    keys = np.round(pts / weld).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_inverse=True)
    f = idx.reshape(-1, 3)
    degenerate = int(np.sum((f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2])))
    f = f[~((f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2]))]
    directed = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    undirected = np.sort(directed, axis=1)
    _, ucount = np.unique(undirected, axis=0, return_counts=True)
    _, dcount = np.unique(directed, axis=0, return_counts=True)
    v = tris
    signed = float(np.sum(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2]))) / 6.0)
    pts_all = tris.reshape(-1, 3)
    return {
        "bbox_min": [round(float(c), 4) for c in pts_all.min(axis=0)] if len(pts_all) else None,
        "bbox_max": [round(float(c), 4) for c in pts_all.max(axis=0)] if len(pts_all) else None,
        "triangles": int(len(tris)),
        "degenerate_triangles": degenerate,
        "boundary_edges": int(np.sum(ucount == 1)),
        "non_manifold_edges": int(np.sum(ucount > 2)),
        "inconsistent_orientation_edges": int(np.sum(dcount > 1)),
        "signed_volume": round(signed, 4),
    }


def export_report(part: Part, formats: list[str], stl_tolerance: float = 0.01) -> dict:
    out: dict = {}
    with tempfile.TemporaryDirectory() as d:
        if "step" in formats:
            p = Path(d) / f"{part.name}.step"
            part.export(str(p))
            from OCP.IFSelect import IFSelect_RetDone
            from OCP.STEPControl import STEPControl_Reader

            r = STEPControl_Reader()
            ok = r.ReadFile(str(p)) == IFSelect_RetDone
            shape = None
            if ok:
                r.TransferRoots()
                shape = r.OneShape()
            vol = _occ.volume(shape) if shape is not None else 0.0
            out["step"] = {
                "reimported": bool(ok and shape is not None),
                "valid": bool(shape is not None and _occ.is_valid(shape)),
                "solids": len(_occ.solids(shape)) if shape is not None else 0,
                "volume_rel_error": round(abs(vol - part.volume) / max(part.volume, 1e-9), 8),
            }
            out["step"]["ok"] = out["step"]["reimported"] and out["step"]["valid"] and \
                out["step"]["solids"] == part.solid_count and out["step"]["volume_rel_error"] < 1e-4
        if "stl" in formats:
            p = Path(d) / f"{part.name}.stl"
            part.export(str(p), tolerance=stl_tolerance)
            rep = stl_report(p)
            rep["volume_rel_error"] = round(abs(rep["signed_volume"] - part.volume) / max(part.volume, 1e-9), 6)
            rep["ok"] = rep["triangles"] > 0 and rep["boundary_edges"] == 0 and rep["non_manifold_edges"] == 0 \
                and rep["inconsistent_orientation_edges"] == 0 and rep["signed_volume"] > 0 and rep["volume_rel_error"] < 0.02
            out["stl"] = rep
    return out


def fits(size, volume) -> bool:
    """True if a box of ``size`` fits in ``volume`` in some axis-aligned orientation."""
    return all(a <= b + 1e-6 for a, b in zip(sorted(size), sorted(volume)))


def hole_access_volume(hole: dict, direction, diameter: float, length: float, obstacles) -> float:
    """Volume of obstacles inside a cylinder running from the hole's exit end along ``direction``."""
    d = np.asarray(direction, dtype=float)
    d = d / np.linalg.norm(d)
    ax = np.asarray(hole["axis"], dtype=float)
    start = np.asarray(hole["position"], dtype=float)
    if np.dot(ax, d) > 0:  # position is the low end of the axis; the exit is at the far end
        start = start + ax * hole["depth"]
    spec = {"cylinder": {"center": list(start + d * 0.05), "axis": list(d), "diameter": diameter, "from": 0.0, "to": length}}
    cyl = make_solid(spec)
    return sum(common_volume(cyl, o) for o in obstacles)

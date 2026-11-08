"""Design-check analyses shared by the Python API and the CLI: wall thickness and clearances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import _occ

if TYPE_CHECKING:
    from .part import Part


def thickness_samples(part: "Part", per_face: int = 5) -> list[dict]:
    """Local wall thickness sampled on every face.

    From points spread over each face, a ray is cast inward (against the outward
    normal); the distance to where it leaves the material is the local
    thickness.  Thin ligaments beside holes, thin floors and thin walls all show
    up as small values.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d
    from OCP.TopAbs import TopAbs_IN

    shape = part.shape
    out = []
    for f in _occ.faces(shape):
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f)
        surf = BRepAdaptor_Surface(f)
        names = None
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
                eps = 1e-4
                origin = (p.X() - n[0] * eps, p.Y() - n[1] * eps, p.Z() - n[2] * eps)
                t = _occ.first_hit(shape, origin, (-n[0], -n[1], -n[2]))
                if t is None:
                    continue
                if names is None:
                    names = part._names_of(f, "face")
                out.append({"thickness": t + eps, "point": (p.X(), p.Y(), p.Z()), "normal": n, "faces": names})
    return out


def thickness_report(part: "Part", percentile: float = 2.0, per_face: int = 5, worst: int = 5) -> dict:
    samples = sorted(thickness_samples(part, per_face), key=lambda s: s["thickness"])
    if not samples:
        return {"part": part.name, "samples": 0}
    k = min(len(samples) - 1, max(0, int(len(samples) * percentile / 100.0)))
    r = lambda v: [round(c, 3) + 0.0 for c in v]  # noqa: E731
    return {
        "part": part.name,
        "samples": len(samples),
        "min": round(samples[0]["thickness"], 4),
        f"p{percentile:g}": round(samples[k]["thickness"], 4),
        "thinnest": [{"thickness": round(s["thickness"], 3), "at": r(s["point"]), "measured_along": r([-c for c in s["normal"]]),
                      "faces": s["faces"]} for s in samples[:worst]],
    }


def clearance_matrix(parts: dict[str, "Part"], min_distance: float | None = None) -> dict:
    """Minimum distance and overlap volume for every pair of parts (references included)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    names = sorted(parts)
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            d, pa, pb = _occ.distance(parts[a].shape, parts[b].shape)
            overlap = 0.0
            if d < 1e-7:
                op = BRepAlgoAPI_Common(parts[a].shape, parts[b].shape)
                overlap = _occ.volume(op.Shape()) if op.IsDone() else float("nan")
            row = {
                "a": a,
                "b": b,
                "min_distance": round(d, 4),
                "overlap_volume": round(overlap, 4),
                "closest_points": [[round(c, 3) + 0.0 for c in pa], [round(c, 3) + 0.0 for c in pb]],
                "state": "overlap" if overlap > 1e-6 else ("touching" if d < 1e-6 else "clear"),
            }
            if min_distance is not None:
                row["ok"] = d >= min_distance - 1e-6
            ref = parts[a] if parts[a].reference else parts[b] if parts[b].reference else None
            if ref is not None:
                other = parts[b] if ref is parts[a] else parts[a]
                row["reference_faces"] = _face_clearances(ref, other)
            pairs.append(row)
    pairs.sort(key=lambda r: (-r["overlap_volume"], r["min_distance"]))
    out = {"pairs": pairs}
    if min_distance is not None:
        out["min_required"] = min_distance
        out["violations"] = [p for p in pairs if not p["ok"]]
    return out


def _face_clearances(ref: "Part", other: "Part", per_face: int = 5) -> list[dict]:
    """Gap from each face of a reference body to ``other``, measured along the face's outward normal.

    Rays are cast outward from points spread over the face; the nearest hit is the
    face's clearance (0 = contact).  Faces whose rays hit nothing are "open".
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d
    from OCP.TopAbs import TopAbs_IN

    rows = []
    for f in _occ.faces(ref.shape):
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f)
        surf = BRepAdaptor_Surface(f)
        best = None
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
                t = _occ.first_hit(other.shape, (p.X() - n[0] * 1e-6, p.Y() - n[1] * 1e-6, p.Z() - n[2] * 1e-6), n)
                if t is not None and (best is None or t < best):
                    best = max(0.0, t - 1e-6)
        rows.append({
            "faces": ref._names_of(f, "face") or [f"{_occ.surface_type(f)} face"],
            "normal": [round(c, 3) + 0.0 for c in _occ.face_normal(f)],
            "centroid": [round(c, 3) + 0.0 for c in _occ.face_centroid(f)],
            "gap": round(best, 4) if best is not None else None,
        })
    rows.sort(key=lambda r: (r["gap"] is None, r["gap"] if r["gap"] is not None else 0))
    return rows

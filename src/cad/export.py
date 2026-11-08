"""STEP / STL / BREP export."""

from __future__ import annotations

import os
from pathlib import Path

from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.StlAPI import StlAPI_Writer
from OCP.TopoDS import TopoDS_Shape

from .errors import EXPORT_FAILED, INVALID_ARGUMENT, CadError

FORMATS = {".step": "step", ".stp": "step", ".stl": "stl", ".brep": "brep"}


def export_shape(
    shape: TopoDS_Shape,
    path: str | os.PathLike,
    *,
    name: str | None = None,
    tolerance: float = 0.01,
    angular_tolerance: float = 0.2,
    ascii: bool = False,
) -> str:
    """Export ``shape`` to ``path``; format chosen from the extension.

    STL meshing: ``tolerance`` is the maximum chordal deviation in mm,
    ``angular_tolerance`` in radians.
    """
    p = Path(path)
    fmt = FORMATS.get(p.suffix.lower())
    if fmt is None:
        raise CadError(INVALID_ARGUMENT, f"unsupported export extension {p.suffix!r}", hint=f"use one of {sorted(FORMATS)}")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    try:
        if fmt == "step":
            w = STEPControl_Writer()
            Interface_Static.SetCVal_s("write.step.unit", "MM")
            Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
            if name:
                Interface_Static.SetCVal_s("write.step.product.name", name)
            if w.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone:
                raise CadError(EXPORT_FAILED, "STEP transfer failed")
            if w.Write(str(tmp)) != IFSelect_RetDone:
                raise CadError(EXPORT_FAILED, f"could not write {p}")
        elif fmt == "stl":
            from . import _occ

            _occ.mesh_shape(shape, tolerance, angular_tolerance)
            w = StlAPI_Writer()
            w.ASCIIMode = ascii
            if not w.Write(shape, str(tmp)):
                raise CadError(EXPORT_FAILED, f"could not write {p}")
        else:
            if not BRepTools.Write_s(shape, str(tmp)):
                raise CadError(EXPORT_FAILED, f"could not write {p}")
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink()
    return str(p)


def stl_check(path: str | os.PathLike) -> dict:
    """Printability check of a binary/ASCII STL: watertight, manifold, consistently oriented."""
    import numpy as np

    data = Path(path).read_bytes()
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        verts = [tuple(map(float, line.split()[1:4])) for line in data.decode(errors="ignore").splitlines()
                 if line.strip().startswith("vertex")]
        tris = np.asarray(verts, dtype=float).reshape(-1, 3, 3)
    else:
        n = int.from_bytes(data[80:84], "little")
        rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
        tris = rec["v"].astype(float)
    if len(tris) == 0:
        return {"triangles": 0, "watertight": False}
    _, idx = np.unique(np.round(tris.reshape(-1, 3) / 1e-4).astype(np.int64), axis=0, return_inverse=True)
    f = idx.reshape(-1, 3)
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    directed = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    _, ucount = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)
    _, dcount = np.unique(directed, axis=0, return_counts=True)
    volume = float(np.sum(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2]))) / 6.0)
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    watertight = bool(np.all(ucount == 2) and np.all(dcount == 1) and volume > 0)
    return {"triangles": int(len(tris)), "watertight": watertight, "open_edges": int(np.sum(ucount == 1)),
            "non_manifold_edges": int(np.sum(ucount > 2)), "volume_mm3": round(volume, 3),
            "size_mm": [round(float(c), 3) for c in hi - lo], "units": "mm"}


def read_brep(path: str | os.PathLike) -> TopoDS_Shape:
    from OCP.BRep import BRep_Builder

    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()):
        raise CadError(INVALID_ARGUMENT, f"could not read BREP file {path}")
    return shape

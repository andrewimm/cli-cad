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
            BRepMesh_IncrementalMesh(shape, tolerance, False, angular_tolerance, True)
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


def read_brep(path: str | os.PathLike) -> TopoDS_Shape:
    from OCP.BRep import BRep_Builder

    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()):
        raise CadError(INVALID_ARGUMENT, f"could not read BREP file {path}")
    return shape

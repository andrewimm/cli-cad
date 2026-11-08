"""Import geometry from files: STEP / IGES (exact, with body names and colours), BREP, STL.

Everything comes in as millimetres: STEP and IGES carry their units and are
converted; STL and BREP have none and are taken as mm (pass ``scale=25.4`` for an
inch STL).  STL meshes are sewn into a solid (one planar face per merged group of
triangles), which is fine for reference geometry and simple booleans but heavy for
dense meshes, so they are capped at ``max_triangles``.

Reading is cached in memory by (path, size, mtime) and on disk under the
project's .cad/cache/imports, keyed by the file's content hash.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import _occ
from .errors import INVALID_ARGUMENT, NOT_FOUND, OPERATION_FAILED, CadError

FORMATS = {".step": "step", ".stp": "step", ".iges": "iges", ".igs": "iges", ".brep": "brep", ".brp": "brep", ".stl": "stl"}
MAX_TRIANGLES = 100_000


@dataclass
class Body:
    name: str
    shape: object
    color: str | None = None
    path: list[str] = field(default_factory=list)  # assembly path, outermost first


_memo: dict[tuple, tuple[list[Body], dict]] = {}


def file_format(path: str | os.PathLike) -> str:
    fmt = FORMATS.get(Path(path).suffix.lower())
    if fmt is None:
        raise CadError(INVALID_ARGUMENT, f"cannot import {Path(path).name!r}: unknown format",
                       hint=f"supported: {', '.join(sorted(FORMATS))}")
    return fmt


def read(path: str | os.PathLike, *, max_triangles: int = MAX_TRIANGLES) -> tuple[list[Body], dict]:
    """Bodies (one per solid) and file info.  Raises NOT_FOUND / INVALID_ARGUMENT / OPERATION_FAILED."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise CadError(NOT_FOUND, f"file {str(path)!r} not found",
                       hint="paths are relative to the project directory (where cad.toml is)")
    fmt = file_format(p)
    st = p.stat()
    key = (str(p.resolve()), st.st_size, st.st_mtime_ns, max_triangles)
    if key in _memo:
        return _memo[key]
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    cached = _disk_cache_get(digest)
    if cached is not None and cached[1].get("triangles", 0) > max_triangles:
        cached = None  # re-read so the triangle limit is enforced with its error
    if cached is not None:
        bodies, info = cached
    else:
        reader = {"step": _read_step, "iges": _read_iges, "brep": _read_brep, "stl": _read_stl}[fmt]
        bodies, info = reader(p, max_triangles) if fmt == "stl" else reader(p)
        if not bodies:
            raise CadError(OPERATION_FAILED, f"{p.name} contains no solid bodies",
                           hint="surface-only models cannot be imported as parts", details=info)
        info = {"format": fmt, **info}
        _disk_cache_put(digest, bodies, info)
    info = {**info, "file": str(path), "sha256": digest}
    _memo[key] = (bodies, info)
    return bodies, info


def describe(path: str | os.PathLike) -> dict:
    """What a file contains: bodies with names, sizes, volumes; for `cad info`."""
    bodies, info = read(path)
    out = []
    lo_all, hi_all = [float("inf")] * 3, [float("-inf")] * 3
    for b in bodies:
        lo, hi = _occ.bbox(b.shape)
        lo_all = [min(a, c) for a, c in zip(lo_all, lo)]
        hi_all = [max(a, c) for a, c in zip(hi_all, hi)]
        out.append({"name": b.name, "path": "/".join(b.path + [b.name]), "color": b.color,
                    "bbox_min": [round(v, 4) for v in lo], "bbox_max": [round(v, 4) for v in hi],
                    "size": [round(h - l, 4) for l, h in zip(lo, hi)], "volume": round(_occ.volume(b.shape), 4),
                    "faces": len(_occ.faces(b.shape)), "valid": _occ.is_valid(b.shape)})
    return {**info, "units": "mm", "bodies": out, "bbox_min": [round(v, 4) for v in lo_all],
            "bbox_max": [round(v, 4) for v in hi_all], "size": [round(h - l, 4) for l, h in zip(lo_all, hi_all)]}


def select(bodies: list[Body], solid, path) -> list[Body]:
    """Pick bodies by name (exact, then case-insensitive substring), index, or list of either."""
    if solid is None:
        return bodies
    wanted = solid if isinstance(solid, (list, tuple)) else [solid]
    out = []
    for w in wanted:
        if isinstance(w, int):
            if not -len(bodies) <= w < len(bodies):
                raise CadError(INVALID_ARGUMENT, f"{Path(path).name} has {len(bodies)} bodies; index {w} is out of range")
            out.append(bodies[w])
            continue
        exact = [b for b in bodies if b.name == w or "/".join(b.path + [b.name]) == w]
        hits = exact or [b for b in bodies if str(w).lower() in "/".join(b.path + [b.name]).lower()]
        if not hits:
            raise CadError(NOT_FOUND, f"no body named {w!r} in {Path(path).name}",
                           hint="list them with `cad info <file>`", details={"bodies": [b.name for b in bodies]})
        out.extend(h for h in hits if h not in out)
    return out


# ---------------------------------------------------------------------- readers
def _read_step(p: Path):
    from OCP.STEPCAFControl import STEPCAFControl_Reader

    doc = _new_doc()
    r = STEPCAFControl_Reader()
    r.SetNameMode(True)
    r.SetColorMode(True)
    if str(r.ReadFile(str(p))) != "IFSelect_ReturnStatus.IFSelect_RetDone":
        raise CadError(OPERATION_FAILED, f"could not read STEP file {p.name}", hint="is it a valid ISO 10303-21 file?")
    if not r.Transfer(doc):
        raise CadError(OPERATION_FAILED, f"could not translate STEP file {p.name}")
    return _bodies_from_doc(doc, p.stem), {"units_in_file": _step_units(p)}


def _read_iges(p: Path):
    from OCP.IGESCAFControl import IGESCAFControl_Reader

    doc = _new_doc()
    r = IGESCAFControl_Reader()
    r.SetNameMode(True)
    r.SetColorMode(True)
    if str(r.ReadFile(str(p))) != "IFSelect_ReturnStatus.IFSelect_RetDone" or not r.Transfer(doc):
        raise CadError(OPERATION_FAILED, f"could not read IGES file {p.name}")
    bodies = _bodies_from_doc(doc, p.stem)
    if not bodies:  # IGES is often trimmed surfaces: try sewing them into solids
        from OCP.XCAFDoc import XCAFDoc_DocumentTool

        shape = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main()).GetOneShape()
        bodies = [Body(f"{p.stem}_{i + 1}", s) for i, s in enumerate(_sew_to_solids(shape))]
    return bodies, {}


def _read_brep(p: Path):
    from .export import read_brep

    shape = read_brep(str(p))
    solids = _occ.solids(shape)
    return [Body(p.stem if len(solids) == 1 else f"{p.stem}_{i + 1}", s) for i, s in enumerate(solids)], {}


def _read_stl(p: Path, max_triangles: int):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeShapeOnMesh
    from OCP.RWStl import RWStl

    tri = RWStl.ReadFile_s(str(p))
    if tri is None or tri.NbTriangles() == 0:
        raise CadError(OPERATION_FAILED, f"could not read STL file {p.name}")
    n = tri.NbTriangles()
    if n > max_triangles:
        raise CadError(INVALID_ARGUMENT, f"{p.name} has {n} triangles (limit {max_triangles})",
                       hint="decimate the mesh (e.g. in a slicer or MeshLab), import a STEP instead, "
                            "or pass max_triangles= if you really need it")
    mk = BRepBuilderAPI_MakeShapeOnMesh(tri)
    mk.Build()
    shells = _sew_to_solids(mk.Shape(), unify=True)
    info = {"triangles": n}
    bodies = [Body(p.stem if len(shells) == 1 else f"{p.stem}_{i + 1}", s) for i, s in enumerate(shells)]
    if not bodies:
        raise CadError(OPERATION_FAILED, f"the mesh in {p.name} is not closed, so it has no inside",
                       hint="repair it (holes, flipped or duplicate triangles) and export again", details=info)
    return bodies, info


def _sew_to_solids(shape, unify: bool = False) -> list:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopoDS import TopoDS

    sew = BRepBuilderAPI_Sewing(1e-6)
    sew.Add(shape)
    sew.Perform()
    sewn = sew.SewedShape()
    out = []
    for sh in _occ.shells(sewn):
        if not sh.Closed() if hasattr(sh, "Closed") else False:
            continue
        mk = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sh) if hasattr(TopoDS, "Shell_s") else TopoDS.Shell(sh))
        if not mk.IsDone():
            continue
        solid = mk.Solid()
        cls = BRepClass3d_SolidClassifier(solid)
        cls.PerformInfinitePoint(1e-7)
        if str(cls.State()).endswith("IN"):  # inside out: flip
            solid.Reverse()
        if unify:
            u = ShapeUpgrade_UnifySameDomain(solid, True, True, True)
            u.Build()
            solid = u.Shape()
            solid = _occ.solids(solid)[0] if _occ.solids(solid) else solid
        if BRepCheck_Analyzer(solid).IsValid() and _occ.volume_fast(solid) > 0:
            out.append(solid)
    return out


def _new_doc():
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application

    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(doc)
    return doc


def _label_name(label) -> str | None:
    from OCP.TDataStd import TDataStd_Name

    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        s = attr.Get().ToExtString() if hasattr(attr.Get(), "ToExtString") else str(attr.Get())
        return s.strip() or None
    return None


def _label_color(ct, label, shape) -> str | None:
    from OCP.Quantity import Quantity_Color
    from OCP.XCAFDoc import XCAFDoc_ColorType

    c = Quantity_Color()
    for kind in (XCAFDoc_ColorType.XCAFDoc_ColorGen, XCAFDoc_ColorType.XCAFDoc_ColorSurf):
        for target in (label, shape):
            try:
                if ct.GetColor(target, kind, c):
                    return "#%02x%02x%02x" % tuple(round(255 * v) for v in (c.Red(), c.Green(), c.Blue()))
            except Exception:
                continue
    return None


def _bodies_from_doc(doc, default_name: str) -> list[Body]:
    from OCP.collections import Sequence_TDF_Label
    from OCP.TDF import TDF_Label
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    out: list[Body] = []

    def walk(label, loc, path, inherited_name, inherited_color):
        name = _label_name(label) or inherited_name
        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        color = _label_color(ct, label, shape) or inherited_color
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            comps = Sequence_TDF_Label()
            XCAFDoc_ShapeTool.GetComponents_s(label, comps, False)
            for i in range(1, comps.Length() + 1):
                comp = comps.Value(i)
                ref = TDF_Label()
                XCAFDoc_ShapeTool.GetReferredShape_s(comp, ref)
                cloc = XCAFDoc_ShapeTool.GetLocation_s(comp)
                walk(ref, loc.Multiplied(cloc), path + ([name] if name else []),
                     _label_name(comp), _label_color(ct, comp, XCAFDoc_ShapeTool.GetShape_s(comp)) or color)
            return
        placed = shape.Moved(loc) if not loc.IsIdentity() else shape
        solids = _occ.solids(placed)
        for k, s in enumerate(solids):
            n = name or default_name
            out.append(Body(n if len(solids) == 1 else f"{n}_{k + 1}", s, color, list(path)))

    free = Sequence_TDF_Label()
    st.GetFreeShapes(free)
    for i in range(1, free.Length() + 1):
        walk(free.Value(i), TopLoc_Location(), [], None, None)
    # unique names: suffix duplicates (two identical screws -> screw, screw_2)
    seen: dict[str, int] = {}
    for b in out:
        seen[b.name] = seen.get(b.name, 0) + 1
        if seen[b.name] > 1:
            b.name = f"{b.name}_{seen[b.name]}"
    return out


def _step_units(p: Path) -> str:
    head = p.read_bytes()[:400_000].decode("latin-1", "replace").upper()
    if "'INCH'" in head:
        return "inch"
    if "SI_UNIT(.MILLI.,.METRE.)" in head:
        return "mm"
    if "SI_UNIT(.CENTI.,.METRE.)" in head:
        return "cm"
    if "SI_UNIT($,.METRE.)" in head:
        return "m"
    return "unknown"


# ---------------------------------------------------------------------- disk cache
_cache_dir: Path | None = None


def set_cache_dir(path: Path | None) -> None:
    global _cache_dir
    _cache_dir = path


def _disk_cache_get(digest: str):
    import json

    if _cache_dir is None:
        return None
    d = _cache_dir / digest[:32]
    try:
        meta = json.loads((d / "bodies.json").read_text())
        from .export import read_brep

        bodies = [Body(b["name"], _occ.solids(read_brep(str(d / f"{i}.brep")))[0], b["color"], b["path"])
                  for i, b in enumerate(meta["bodies"])]
        return bodies, meta["info"]
    except Exception:
        return None


def _disk_cache_put(digest: str, bodies: list[Body], info: dict) -> None:
    import json
    import tempfile

    from .tessellate import brep_bytes

    if _cache_dir is None:
        return
    try:
        _cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=_cache_dir))
        for i, b in enumerate(bodies):
            (tmp / f"{i}.brep").write_bytes(brep_bytes(b.shape))
        (tmp / "bodies.json").write_text(json.dumps({"info": info, "bodies": [
            {"name": b.name, "color": b.color, "path": b.path} for b in bodies]}))
        os.replace(tmp, _cache_dir / digest[:32])
    except OSError:
        pass

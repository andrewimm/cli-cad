"""3MF export (3D Manufacturing Format) with materials.

Layouts:

* ``objects`` (default): one mesh object per part, each a separate build item at its
  modelled position.  Slicers load them as separate objects (e.g. a box and its lid).
  If two parts' footprints on the bed would overlap or touch (feet under a case: slicers
  drop every object onto the bed), all parts are laid out side by side instead
  (``arrange``), each resting on Z = 0, and the report says so.
* ``multimaterial``: one assembly object whose components are the parts' meshes, in
  place, plus Bambu Studio's ``Metadata/model_settings.config`` naming each part and
  its filament (material slot k -> filament k+1), so the slicer loads one object with
  one part per material, ready for an AMS / multi-material printer.

Every part's mesh object references its material's colour in a 3MF Materials-extension
``<m:colorgroup>`` (the same mechanism Fusion uses for multi-colour exports; Bambu
Studio assigns filaments from it) and carries ``cad:material`` metadata with the
material name.  Slicers ignore the colours when choosing extruders, except Bambu Studio,
so each file also states every part's extruder in the formats the common slicers read:

* Bambu Studio and OrcaSlicer: ``Metadata/model_settings.config`` (both layouts);
* Cura: ``cura:extruder_nr`` metadata on each mesh object (0-based; both layouts);
* PrusaSlicer: ``Metadata/Slic3r_PE_model.config`` (objects layout).

PrusaSlicer turns every 3MF component into a separate object and drops each onto the
bed, so the multimaterial layout falls apart there.  ``target="prusa"`` writes the
assembly as PrusaSlicer's own layout instead: one mesh object whose triangle ranges are
the parts ("volumes"), each with its extruder.  Cura cannot assign extruders within one
mesh, which is why that layout is not the default.

Verified with Bambu Studio 2.07, OrcaSlicer 2.5, PrusaSlicer 2.9.4 and Cura 5.14's 3MF
parser (``scripts/slicer_compat``).

Meshes are welded (shared vertices), outward oriented and checked to be closed
two-manifolds before writing, as the 3MF core specification requires.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from . import _occ
from .errors import EXPORT_FAILED, INVALID_ARGUMENT, CadError

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MATERIAL_NS = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
CAD_NS = "https://github.com/cad-agent/cad/3mf/2026"
CURA_NS = "http://software.ultimaker.com/xml/cura/3mf/2015/10"
MODES = ("objects", "multimaterial")
TARGETS = ("any", "prusa")
IDENTITY = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
ARRANGE_MIN_GAP = 1.0   # mm between footprints below which objects mode lays the parts out
ARRANGE_GAP = 5.0       # mm between parts once laid out

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="config" ContentType="application/vnd.ms-package.3dmanufacturing-config+xml"/>
</Types>
"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def welded_mesh(shape, tolerance: float = 0.01, angular: float = 0.2) -> tuple[np.ndarray, np.ndarray]:
    """(vertices, triangles) with shared vertices, outward triangle winding."""
    from .tessellate import tessellate

    m = tessellate(shape, tolerance, angular)
    if len(m.triangles) == 0:
        raise CadError(EXPORT_FAILED, "tessellation produced no triangles")
    q = np.round(m.vertices / 1e-6).astype(np.int64)
    _, first, inverse = np.unique(q, axis=0, return_index=True, return_inverse=True)
    verts = m.vertices[first]
    tris = inverse.reshape(-1)[m.triangles]
    keep = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
    return verts, tris[keep]


def manifold_report(verts: np.ndarray, tris: np.ndarray) -> dict:
    directed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    _, ucount = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)
    _, dcount = np.unique(directed, axis=0, return_counts=True)
    v = verts[tris]
    volume = float(np.sum(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2]))) / 6.0)
    return {"open_edges": int(np.sum(ucount == 1)), "non_manifold_edges": int(np.sum(ucount > 2)),
            "flipped_edges": int(np.sum(dcount > 1)), "volume": volume,
            "closed": bool(np.all(ucount == 2) and np.all(dcount == 1) and volume > 0)}


def _color(c: str | None, fallback: str) -> str:
    return ((c or fallback).upper() + "FF") if (c or fallback).startswith("#") else "#808080FF"


def _mesh_xml(verts, tris, tri_attr: str = "") -> str:
    vs = "".join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in verts)
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"{tri_attr}/>' for a, b, c in tris)
    return f"<mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh>"


def orient_for_print(parts: dict, mode: str = "objects") -> tuple[dict, list[str]]:
    """Parts positioned for printing (Part.print_on).  In objects mode each part turns on its own;
    in multimaterial mode the parts are one print, so they turn together (one orientation)."""
    downs = {n: p.print_down for n, p in parts.items() if getattr(p, "print_down", None)}
    if not downs:
        return parts, []
    if mode != "multimaterial":
        return {n: p.as_printed() for n, p in parts.items()}, [f"{n}: printed on its {_dir_name(d)} face" for n, d in downs.items()]
    distinct = {tuple(round(c, 6) for c in d) for d in downs.values()}
    if len(distinct) > 1:
        raise CadError(INVALID_ARGUMENT, "multi-material parts print as one object but have different print_on() orientations",
                       details={"print_on": {n: list(d) for n, d in downs.items()}})
    from .part import Part

    down = next(iter(downs.values()))
    ref = Part("_orient")
    ref._shape = _occ.compound([p.shape for p in parts.values()])
    ref.print_down = down
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    trsf = _whole_trsf(ref.shape, down)  # one rotation + drop for the whole assembly
    out = {}
    for n, p in parts.items():
        q = Part._rehydrate(p.name, BRepBuilderAPI_Transform(p.shape, trsf, True).Shape(), p.color, None, None, p.reference,
                            p.material.to_dict() if p.material else None)
        out[n] = q
    return out, [f"all parts: printed on the {_dir_name(down)} side"]


def footprint_conflicts(boxes: dict, min_gap: float = ARRANGE_MIN_GAP) -> list[tuple[str, str]]:
    """Pairs of parts whose footprints (X/Y bounding boxes) overlap or come closer than ``min_gap``."""
    names = list(boxes)
    out = []
    for i, a in enumerate(names):
        (alo, ahi) = boxes[a]
        for b in names[i + 1:]:
            (blo, bhi) = boxes[b]
            if all(alo[k] < bhi[k] + min_gap and blo[k] < ahi[k] + min_gap for k in (0, 1)):
                out.append((a, b))
    return out


def arrange(boxes: dict, gap: float = ARRANGE_GAP) -> dict:
    """Side-by-side layout of footprints: {name: (lo, hi)} -> {name: (dx, dy, dz)} moving each part into rows
    (deepest first) that fill a roughly square area, the whole layout centred on the origin, every part on Z = 0."""
    import math as _m

    size = {n: (hi[0] - lo[0], hi[1] - lo[1]) for n, (lo, hi) in boxes.items()}
    order = sorted(boxes, key=lambda n: (-size[n][1], -size[n][0], n))
    row_limit = max(max(w for w, _ in size.values()),
                    _m.sqrt(sum((w + gap) * (d + gap) for w, d in size.values())) * 1.25)
    spots, x, y, row_depth = {}, 0.0, 0.0, 0.0
    for n in order:
        w, d = size[n]
        if x > 0 and x + w > row_limit:
            x, y, row_depth = 0.0, y + row_depth + gap, 0.0
        spots[n] = (x, y)
        x += w + gap
        row_depth = max(row_depth, d)
    width = max(spots[n][0] + size[n][0] for n in spots)
    depth = max(spots[n][1] + size[n][1] for n in spots)
    out = {}
    for n, (lo, hi) in boxes.items():
        sx, sy = spots[n]
        out[n] = (sx - width / 2 - lo[0], depth / 2 - sy - size[n][1] - lo[1], -lo[2])  # first row at the back
    return out


def _whole_trsf(before, down):
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    import math as _m

    n = down
    target = (0.0, 0.0, -1.0)
    dot = sum(a * b for a, b in zip(n, target))
    t = gp_Trsf()
    if dot < 1 - 1e-12:
        if dot < -1 + 1e-12:
            t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), _m.pi)
        else:
            axis = (n[1] * target[2] - n[2] * target[1], n[2] * target[0] - n[0] * target[2], n[0] * target[1] - n[1] * target[0])
            t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), _m.acos(max(-1.0, min(1.0, dot))))
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    lo, _ = _occ.bbox(BRepBuilderAPI_Transform(before, t, True).Shape())
    t2 = gp_Trsf()
    t2.SetTranslation(gp_Vec(0, 0, -lo[2]))
    return t2.Multiplied(t)


def _dir_name(d) -> str:
    axes = {(0, 0, -1): "bottom (-Z)", (0, 0, 1): "top (+Z)", (0, -1, 0): "front (-Y)", (0, 1, 0): "back (+Y)",
            (-1, 0, 0): "left (-X)", (1, 0, 0): "right (+X)"}
    key = tuple(int(round(c)) if abs(abs(c) - round(abs(c))) < 1e-6 else None for c in d)
    return axes.get(key, f"({', '.join(f'{c:.3g}' for c in d)})")


def export_3mf(parts: dict, path: str | os.PathLike, *, mode: str = "objects", tolerance: float = 0.01,
               angular_tolerance: float = 0.2, title: str | None = None, check_overlap: bool = True,
               target: str = "any") -> dict:
    """Write ``parts`` ({name: Part}) to one .3mf file.  Returns a report (materials, objects, warnings).

    ``target="prusa"`` changes only the multimaterial layout (see the module docstring)."""
    from . import __version__
    from .materials import Material
    from .renderer import PALETTE

    if mode not in MODES:
        raise CadError(INVALID_ARGUMENT, f"unknown 3MF mode {mode!r}", hint=f"use one of {MODES}")
    if target not in TARGETS:
        raise CadError(INVALID_ARGUMENT, f"unknown 3MF target {target!r}", hint=f"use one of {TARGETS}")
    if not parts:
        raise CadError(INVALID_ARGUMENT, "nothing to export")
    assembled = parts  # overlap / contact checks use the design pose, not the print layout
    parts, orient_notes = orient_for_print(parts, mode)
    # material slots, in first-use order; parts without a material get a per-part default slot
    slots: list[Material] = []
    slot_of: dict[str, int] = {}
    for i, (name, p) in enumerate(parts.items()):
        mat = p.material or Material(f"{name} (no material)", color=_hex(p.color, PALETTE[i % len(PALETTE)]))
        key = (mat.name, mat.color)
        idx = next((k for k, m in enumerate(slots) if (m.name, m.color) == key), None)
        if idx is None:
            slots.append(mat)
            idx = len(slots) - 1
        slot_of[name] = idx
    meshes = {}
    report = {"mode": mode, "target": target, "objects": [], "materials": [], "warnings": [], "oriented_for_print": orient_notes}
    for name, p in parts.items():
        v, t = welded_mesh(p.shape, tolerance, angular_tolerance)
        mr = manifold_report(v, t)
        if not mr["closed"]:
            raise CadError(EXPORT_FAILED, f"mesh of part '{name}' is not a closed manifold "
                           f"({mr['open_edges']} open, {mr['non_manifold_edges']} non-manifold edges)",
                           hint="check the part with assert_valid(); try a smaller --tolerance")
        meshes[name] = (v, t)
        report["objects"].append({"part": name, "material": slots[slot_of[name]].name, "triangles": int(len(t)),
                                  "vertices": int(len(v)), "volume_mm3": round(mr["volume"], 3)})
    report["arranged"] = None
    if mode == "objects" and len(meshes) > 1:
        boxes = {n: (v.min(0), v.max(0)) for n, (v, _) in meshes.items()}
        conflicts = footprint_conflicts(boxes)
        if conflicts:
            moves = arrange(boxes)
            meshes = {n: (v + np.array(moves[n]), t) for n, (v, t) in meshes.items()}
            report["arranged"] = {
                "reason": "footprints overlap on the bed: " + ", ".join(f"{a}/{b}" for a, b in conflicts[:4])
                          + (f" (+{len(conflicts) - 4} more)" if len(conflicts) > 4 else ""),
                "gap_mm": ARRANGE_GAP, "moved_mm": {n: [round(c, 3) for c in moves[n]] for n in meshes}}
    if check_overlap and len(parts) > 1:
        names = list(parts)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ov = assembled[a].interference(assembled[b])
                if ov > 1e-6:
                    report["warnings"].append({"code": "MATERIAL_OVERLAP" if mode == "multimaterial" else "PARTS_OVERLAP",
                                               "message": f"parts '{a}' and '{b}' overlap by {ov:.3f} mm3"
                                               + ("; two materials claim the same volume" if mode == "multimaterial" else ""),
                                               "parts": [a, b], "volume_mm3": round(ov, 4)})
    if mode == "objects" and len(slots) > 1 and len(parts) > 1:
        names = list(parts)
        touching = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
                    if slot_of[a] != slot_of[b] and assembled[a].distance_to(assembled[b]) < 1e-6]
        if touching:
            apart = "they are laid out apart as separate objects; " if report["arranged"] else ""
            report["warnings"].append({"code": "CONSIDER_MULTIMATERIAL",
                                       "message": f"parts in different materials touch ({', '.join(f'{a}/{b}' for a, b in touching[:4])}); "
                                                  f"{apart}to print them together as one piece use --3mf-mode multimaterial "
                                                  "(or threemf_mode = \"multimaterial\" in cad.toml)",
                                       "parts": [list(t) for t in touching]})
    for k, m in enumerate(slots):
        report["materials"].append({"slot": k, "name": m.name, "color": _color(m.color, "#808080")[:7],
                                    "density": m.density, "kind": m.kind, "extruder": k + 1,
                                    "parts": [n for n, s in slot_of.items() if s == k]})
    colors = "".join(f'<m:color color="{_color(m.color, "#808080")}"/>' for m in slots)
    meta = [f'<metadata name="Application">cad {escape(__version__)}</metadata>']
    if title:
        meta.append(f"<metadata name=\"Title\">{escape(title)}</metadata>")
    label = title or "assembly"
    extruder = {n: slot_of[n] + 1 for n in meshes}  # material slot k -> extruder / filament k+1
    configs: dict[str, str] = {}

    def metadata(name: str) -> str:
        m = slots[slot_of[name]]
        return ('<metadatagroup>'
                f'<metadata name="cad:material">{escape(m.name)}</metadata>'
                + (f'<metadata name="cad:density_g_cm3">{m.density}</metadata>' if m.density else "")
                + f'<metadata name="cura:extruder_nr" preserve="1">{extruder[name] - 1}</metadata>'
                + "</metadatagroup>")

    objects, items = [], []
    if mode == "multimaterial" and target == "prusa":
        # one mesh; each part is a range of its triangles (a PrusaSlicer "volume")
        verts, tris, volumes, first = [], [], [], 0
        offset = 0
        for name, (v, t) in meshes.items():
            verts.append(v)
            tris.append(t + offset)
            offset += len(v)
            volumes.append((first, first + len(t) - 1, name, extruder[name]))
            first += len(t)
        first_part = next(iter(meshes))
        objects.append(f'<object id="2" type="model" name={quoteattr(label)} pid="1" pindex="{slot_of[first_part]}">'
                       + _mesh_xml(np.vstack(verts), np.vstack(tris)) + "</object>")
        items = ['<item objectid="2"/>']
        configs["Metadata/Slic3r_PE_model.config"] = _prusa_config([(2, label, extruder[first_part], volumes)])
    else:
        ids = {}
        for oid, (name, (v, t)) in enumerate(meshes.items(), start=2):
            ids[name] = oid
            objects.append(f'<object id="{oid}" type="model" name={quoteattr(name)} pid="1" pindex="{slot_of[name]}">'
                           + metadata(name) + _mesh_xml(v, t) + "</object>")
        if mode == "objects":
            items = [f'<item objectid="{ids[n]}"/>' for n in meshes]
            configs["Metadata/model_settings.config"] = _bambu_config(
                [(ids[n], n, extruder[n], [(ids[n], n, extruder[n])]) for n in meshes])
            configs["Metadata/Slic3r_PE_model.config"] = _prusa_config(
                [(ids[n], n, extruder[n], [(0, len(meshes[n][1]) - 1, n, extruder[n])]) for n in meshes])
        else:
            aid = len(meshes) + 2
            objects.append(f'<object id="{aid}" type="model" name={quoteattr(label)}><components>'
                           + "".join(f'<component objectid="{ids[n]}"/>' for n in meshes) + "</components></object>")
            items = [f'<item objectid="{aid}"/>']
            configs["Metadata/model_settings.config"] = _bambu_config(
                [(aid, label, 1, [(ids[n], n, extruder[n]) for n in meshes])])
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}" '
             f'xmlns:m="{MATERIAL_NS}" xmlns:cad="{CAD_NS}" xmlns:cura="{CURA_NS}">'
             + "".join(meta) + f'<resources><m:colorgroup id="1">{colors}</m:colorgroup>' + "".join(objects)
             + "</resources><build>" + "".join(items) + "</build></model>\n")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", model)
        for name, text in configs.items():
            z.writestr(name, text)
    os.replace(tmp, p)
    report["path"] = str(p)
    report["bytes"] = p.stat().st_size
    return report


def _bambu_config(objects) -> str:
    """Bambu Studio / OrcaSlicer model settings: objects [(id, name, extruder, parts [(id, name, extruder)])]."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n']
    for oid, name, ext, parts in objects:
        out.append(f'  <object id="{oid}">\n    <metadata key="name" value={quoteattr(name)}/>\n'
                   f'    <metadata key="extruder" value="{ext}"/>\n')
        for pid, pname, pext in parts:
            out.append(f'    <part id="{pid}" subtype="normal_part">\n'
                       f'      <metadata key="name" value={quoteattr(pname)}/>\n'
                       f'      <metadata key="matrix" value="{IDENTITY}"/>\n'
                       f'      <metadata key="extruder" value="{pext}"/>\n    </part>\n')
        out.append("  </object>\n")
    return "".join(out) + "</config>\n"


def _prusa_config(objects) -> str:
    """PrusaSlicer model settings: objects [(id, name, extruder, volumes [(first, last triangle, name, extruder)])]."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n']
    for oid, name, ext, volumes in objects:
        out.append(f' <object id="{oid}" instances_count="1">\n'
                   f'  <metadata type="object" key="name" value={quoteattr(name)}/>\n'
                   f'  <metadata type="object" key="extruder" value="{ext}"/>\n')
        for first, last, vname, vext in volumes:
            out.append(f'  <volume firstid="{first}" lastid="{last}">\n'
                       f'   <metadata type="volume" key="name" value={quoteattr(vname)}/>\n'
                       f'   <metadata type="volume" key="volume_type" value="ModelPart"/>\n'
                       f'   <metadata type="volume" key="extruder" value="{vext}"/>\n  </volume>\n')
        out.append(" </object>\n")
    return "".join(out) + "</config>\n"


def _hex(color, fallback) -> str:
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        return color
    if isinstance(color, (tuple, list)) and len(color) == 3:
        vals = [float(c) * (255 if max(color) <= 1 else 1) for c in color]
        return "#" + "".join(f"{int(round(c)):02x}" for c in vals)
    r, g, b = fallback
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
